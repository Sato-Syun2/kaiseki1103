#!/usr/bin/env python3
"""Export sparse depth from multiple SVOs to local storage, then mirror the batch."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from exchange_copy import copy_batch, stage_worker_scripts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_depth_export(root: Path, source: Path, setup_id: str) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "complete":
        raise ValueError("depth export manifest is not complete")
    if manifest.get("setup_id") != setup_id:
        raise ValueError("depth export setup ID differs from the requested setup")
    if manifest.get("source_svo") != str(source.resolve()):
        raise ValueError("depth export source path differs from the requested SVO")
    file_hashes = manifest.get("files_sha256")
    if not isinstance(file_hashes, dict) or not file_hashes:
        raise ValueError("depth export manifest has no output hashes")
    resolved_root = root.resolve()
    for relative_name, expected in file_hashes.items():
        path = (root / relative_name).resolve()
        if not path.is_relative_to(resolved_root) or not path.is_file():
            raise ValueError(f"missing or unsafe depth asset path: {relative_name}")
        if sha256_file(path) != expected:
            raise ValueError(f"SHA-256 mismatch: {relative_name}")
    if int(manifest.get("sample_count", 0)) < 1 or int(manifest.get("total_svo_frames_read", 0)) < 1:
        raise ValueError("depth export contains no sampled SVO frames")
    return {
        "status": "valid",
        "sample_count": manifest["sample_count"],
        "total_svo_frames_read": manifest["total_svo_frames_read"],
        "verified_files": len(file_hashes),
        "source_svo_sha256": manifest.get("source_svo_sha256"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange-root", type=Path, required=True, help="shared mirror destination")
    parser.add_argument(
        "--local-root", type=Path, default=Path.home() / "kaiseki1103_exchange",
        help="primary local output folder (default: <user home>\\kaiseki1103_exchange)",
    )
    parser.add_argument(
        "--job", nargs=3, action="append", required=True,
        metavar=("JOB_ID", "SVO_PATH", "SETUP_ID"),
        help="repeat per calibration SVO; each export is stored under JOB_ID/depth_export",
    )
    parser.add_argument("--every-seconds", type=float, default=0.5)
    parser.add_argument("--pixel-stride", type=int, default=8)
    parser.add_argument("--depth-mode", choices=("NEURAL", "ULTRA", "PERFORMANCE"), default="NEURAL")
    args = parser.parse_args()

    if args.every_seconds <= 0 or args.pixel_stride <= 0:
        parser.error("--every-seconds and --pixel-stride must be positive")
    job_ids = [job[0] for job in args.job]
    if len(set(job_ids)) != len(job_ids):
        parser.error("JOB_ID values must be unique")
    jobs: list[tuple[str, Path, str]] = []
    for job_id, raw_source, setup_id in args.job:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id) or job_id in {".", ".."}:
            parser.error(f"unsafe JOB_ID: {job_id!r}")
        source = Path(raw_source)
        if not source.is_file():
            parser.error(f"SVO file does not exist: {source}")
        if not setup_id.strip():
            parser.error(f"SETUP_ID cannot be blank for {job_id}")
        jobs.append((job_id, source, setup_id))

    local_batch = args.local_root / args.exchange_root.name
    if local_batch.exists():
        parser.error(f"local output already exists; choose a new tag to preserve it: {local_batch}")

    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import pyzed.sl as sl
    except ImportError as exc:
        parser.error(
            "This Python cannot load the installed ZED SDK, OpenCV, and NumPy. "
            f"Import error: {exc}"
        )

    print(f"Python: {sys.executable}")
    print(f"ZED SDK: {sl.Camera.get_sdk_version()}")
    print(f"Jobs: {len(jobs)}")
    print(f"Local output: {local_batch}")
    print(f"Shared mirror target: {args.exchange_root}")

    package = Path(__file__).resolve().parent
    args.local_root.mkdir(parents=True, exist_ok=True)
    try:
        worker_root = stage_worker_scripts(
            package, args.local_root, ["export_zed_depth.py", "exchange_copy.py", "sync_exchange.py"]
        )
    except OSError as exc:
        parser.error(f"could not stage depth exporter onto local disk: {exc}")
    exporter = worker_root / "export_zed_depth.py"
    local_batch.mkdir(parents=True, exist_ok=False)

    inventory_path = local_batch / "input_inventory.csv"
    with inventory_path.open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["job_id", "source_svo", "setup_id"])
        writer.writerows((job_id, str(source.resolve()), setup_id) for job_id, source, setup_id in jobs)

    summary: list[dict] = []
    env = os.environ.copy()
    env["CUDA_CACHE_DISABLE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for job_id, source, setup_id in jobs:
        job_root = local_batch / job_id
        job_root.mkdir()
        output = job_root / "depth_export"
        log_path = job_root / "depth_export.log"
        validation_log = job_root / "depth_export.validation.json"
        command = [
            sys.executable, str(exporter), str(source), "--output", str(output),
            "--setup-id", setup_id, "--every-seconds", str(args.every_seconds),
            "--pixel-stride", str(args.pixel_stride), "--depth-mode", args.depth_mode,
        ]
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"[{job_id}] exporting {source}", flush=True)
        with log_path.open("x", encoding="utf-8") as stream:
            stream.write(f"command: {subprocess.list2cmdline(command)}\n\n")
            stream.flush()
            try:
                completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, check=False)
                export_code = completed.returncode
            except OSError as exc:
                stream.write(f"Could not start Python command: {exc}\n")
                export_code = 1
            stream.write(f"\nexit_code: {export_code}\n")
            stream.flush()

        validation_code: int | str = ""
        status = "export_failed"
        if export_code == 0:
            try:
                validation = validate_depth_export(output, source, setup_id)
                validation_log.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                validation_code = 0
                status = "validated_depth_export"
            except Exception as exc:
                validation_log.write_text(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                validation_code = 1
                status = "validation_failed"
        print(f"[{job_id}] {status}", flush=True)
        summary.append({
            "job_id": job_id,
            "source_svo": str(source.resolve()),
            "setup_id": setup_id,
            "status": status,
            "export_exit_code": export_code,
            "validation_exit_code": validation_code,
            "started_at": started_at,
            "log": str(log_path.relative_to(local_batch)),
            "validation_log": str(validation_log.relative_to(local_batch)) if validation_code != "" else "",
        })

    summary_path = local_batch / "batch_summary.csv"
    fields = ["job_id", "source_svo", "setup_id", "status", "export_exit_code", "validation_exit_code", "started_at", "log", "validation_log"]
    with summary_path.open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary)

    mirrored, mirror_message = copy_batch(local_batch, args.exchange_root)
    print(mirror_message, flush=True)
    failed = [row for row in summary if row["status"] != "validated_depth_export"]
    print(f"Depth exports validated: {len(summary) - len(failed)} / {len(summary)}")
    print(f"Local batch summary: {summary_path}")
    if not mirrored:
        print("Reconnect the shared folder later and run the staged sync_exchange.py to mirror this local batch.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
