#!/usr/bin/env python3
"""Export and validate BODY_34 tracking for every SVO/SVO2 under a folder."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import fnmatch
import os
from pathlib import Path
import subprocess
import sys

from exchange_copy import copy_batch, stage_worker_scripts


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True, help="local folder containing SVO/SVO2 recordings")
    parser.add_argument("--exchange-root", type=Path, required=True, help="shared mirror destination; copied after local export finishes")
    parser.add_argument(
        "--local-root", type=Path, default=Path.home() / "kaiseki1103_exchange",
        help="primary local output folder (default: <user home>\\kaiseki1103_exchange)",
    )
    parser.add_argument("--setup-id", required=True, help="one setup ID shared by all recordings in this batch")
    parser.add_argument(
        "--include-parent-pattern",
        help="optional case-insensitive glob for the SVO's parent directory, e.g. 'recording_*' to skip calibration folders",
    )
    parser.add_argument(
        "--start-index", type=int, default=1,
        help="1-based index in the sorted recording list; keeps original recording_NNN names (default: 1)",
    )
    args = parser.parse_args()

    if not args.input_root.is_dir():
        parser.error(f"input folder does not exist: {args.input_root}")
    if not args.setup_id.strip():
        parser.error("--setup-id cannot be blank")
    if args.start_index < 1:
        parser.error("--start-index must be 1 or greater")
    local_batch = args.local_root / args.exchange_root.name
    if local_batch.exists():
        parser.error(f"local output already exists; choose a new tag to preserve it: {local_batch}")

    recordings = sorted(
        (path for path in args.input_root.rglob("*")
         if path.is_file() and path.suffix.lower() in {".svo", ".svo2"}
         and (args.include_parent_pattern is None or fnmatch.fnmatchcase(
             path.parent.name.casefold(), args.include_parent_pattern.casefold()
         ))),
        key=lambda path: path.relative_to(args.input_root).as_posix().casefold(),
    )
    if not recordings:
        parser.error(f"no .svo or .svo2 files found under: {args.input_root}")
    indexed_recordings = [
        (index, source)
        for index, source in enumerate(recordings, start=1)
        if index >= args.start_index
    ]
    if not indexed_recordings:
        parser.error(
            f"--start-index {args.start_index} is beyond the {len(recordings)} discovered recordings"
        )

    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import pyzed.sl as sl
    except ImportError as exc:
        parser.error(
            "This Python cannot load the installed ZED SDK, OpenCV, and NumPy. "
            "Run this with the Python environment already configured for ZED SDK. "
            f"Import error: {exc}"
        )

    print(f"Python: {sys.executable}")
    print(f"ZED SDK: {sl.Camera.get_sdk_version()}")
    print(f"Input root: {args.input_root.resolve()}")
    print(f"Found recordings: {len(recordings)}")
    if args.include_parent_pattern:
        print(f"Included parent-directory pattern: {args.include_parent_pattern}")
    print(f"Selected recordings: {len(indexed_recordings)} (recording_{args.start_index:03d} onward)")
    print(f"Local output: {local_batch}")
    print(f"Shared mirror target: {args.exchange_root}")
    print(f"Setup ID: {args.setup_id}")

    package = Path(__file__).resolve().parent
    args.local_root.mkdir(parents=True, exist_ok=True)
    try:
        worker_root = stage_worker_scripts(
            package, args.local_root,
            ["export_tracking.py", "validate_export.py", "exchange_copy.py", "sync_exchange.py"],
        )
    except OSError as exc:
        parser.error(f"could not stage SDK worker scripts onto local disk: {exc}")
    exporter = worker_root / "export_tracking.py"
    validator = worker_root / "validate_export.py"
    local_batch.mkdir(parents=True, exist_ok=False)
    inventory = [
        {
            "recording": f"recording_{index:03d}",
            "source_relative_path": source.relative_to(args.input_root).as_posix(),
            "svo_path": str(source.resolve()),
            "setup_id": args.setup_id,
        }
        for index, source in indexed_recordings
    ]
    write_csv(local_batch / "input_inventory.csv", inventory,
              ["recording", "source_relative_path", "svo_path", "setup_id"])
    summary: list[dict] = []
    summary_fields = [
        "recording", "source_svo", "setup_id", "status", "export_exit_code",
        "validation_exit_code", "started_at", "log", "validation_log",
    ]
    env = os.environ.copy()
    env["CUDA_CACHE_DISABLE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def run_logged(command: list[str], log_path: Path) -> int:
        with log_path.open("x", encoding="utf-8") as stream:
            stream.write(f"command: {subprocess.list2cmdline(command)}\n\n")
            stream.flush()
            try:
                completed = subprocess.run(
                    command, stdout=stream, stderr=subprocess.STDOUT, env=env, check=False
                )
                exit_code = completed.returncode
            except OSError as exc:
                stream.write(f"Could not start Python command: {exc}\n")
                exit_code = 1
            stream.write(f"\nexit_code: {exit_code}\n")
            stream.flush()
        return exit_code

    for index, source in indexed_recordings:
        recording = f"recording_{index:03d}"
        record_root = local_batch / recording
        body_dir = record_root / "body"
        record_root.mkdir()
        export_log = record_root / "body.log"
        validation_log = record_root / "body.validation.log"
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        command = [
            sys.executable, str(exporter), str(source), "--output", str(body_dir),
            "--mode", "body", "--setup-id", args.setup_id,
            "--image-period-s", "0.1", "--depth-mode", "NEURAL",
            "--detection-confidence", "35", "--minimum-keypoints", "8",
            "--prediction-timeout-s", "0.2", "--skeleton-smoothing", "0",
        ]
        print(f"[{recording}] exporting {source}", flush=True)
        export_code = run_logged(command, export_log)
        validation_code: int | str = ""
        status = "export_failed"
        if export_code == 0:
            validation_code = run_logged(
                [sys.executable, str(validator), str(body_dir)], validation_log
            )
            status = "validated_full_svo" if validation_code == 0 else "validation_failed"
        print(f"[{recording}] {status}", flush=True)
        summary.append(
            {
                "recording": recording,
                "source_svo": str(source.resolve()),
                "setup_id": args.setup_id,
                "status": status,
                "export_exit_code": export_code,
                "validation_exit_code": validation_code,
                "started_at": started_at,
                "log": str(export_log.relative_to(local_batch)),
                "validation_log": str(validation_log.relative_to(local_batch)) if validation_code != "" else "",
            }
        )

    try:
        write_csv(local_batch / "batch_summary.csv", summary, summary_fields)
    except OSError as exc:
        print(f"Could not write final batch CSV under {local_batch}: {exc}", file=sys.stderr)
        print("Per-recording logs include each command exit code.", file=sys.stderr)
        return 1

    mirrored, mirror_message = copy_batch(local_batch, args.exchange_root)
    print(mirror_message, flush=True)
    failed = [row for row in summary if row["status"] != "validated_full_svo"]
    print(f"Exports validated: {len(summary) - len(failed)} / {len(summary)}")
    print(f"Local batch summary: {local_batch / 'batch_summary.csv'}")
    if not mirrored:
        print("Reconnect the shared folder later and run sync_exchange.py to mirror this local batch.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
