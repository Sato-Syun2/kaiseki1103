#!/usr/bin/env python3
"""Export the 2026-11-04 test_002 and test_005 recordings on a ZED SDK PC."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
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


OPERATIONS = ("test_002_depth", "test_005_depth", "test_002_body")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recording-root",
        type=Path,
        help="folder containing test_002; if omitted, prefer the local SSD and fall back to the shared folder",
    )
    parser.add_argument(
        "--test-002-svo",
        type=Path,
        help="optional explicit test_002 SVO path (for example, a local SSD copy)",
    )
    parser.add_argument(
        "--test-005-svo",
        type=Path,
        default=Path(r"F:\experiment_data\20261104_test\test_005\test_005.svo2"),
        help="test_005 SVO path (default: user-specified local external SSD path)",
    )
    parser.add_argument(
        "--exchange-root",
        type=Path,
        default=Path(r"\\tsclient\_data_experiment_data\kaiseki1103\exchange\test_20261104_candidate"),
        help="new shared mirror destination; export remains local if the share disconnects",
    )
    parser.add_argument(
        "--local-root", type=Path, default=Path.home() / "kaiseki1103_exchange",
        help="primary local output folder (default: <user home>\\kaiseki1103_exchange)",
    )
    parser.add_argument("--setup-id-002", default="test_hallway_20261104_test002_candidate")
    parser.add_argument("--setup-id-005", default="test_hallway_20261104_test005_candidate")
    parser.add_argument(
        "--operations", nargs="+", choices=OPERATIONS, default=list(OPERATIONS),
        metavar="OPERATION",
        help="selected exports; default: all three operations",
    )
    args = parser.parse_args()

    if not args.setup_id_002.strip() or not args.setup_id_005.strip():
        parser.error("setup IDs must not be blank")
    if len(set(args.operations)) != len(args.operations):
        parser.error("--operations cannot contain duplicates")

    local_test2 = Path(r"F:\experiment_data\20261104_test\test_002\test_002.svo2")
    shared_test2 = Path(r"\\tsclient\_data_experiment_data\recordings\20261104_test\test_002\test_002.svo2")
    if args.test_002_svo:
        test2 = args.test_002_svo
    elif args.recording_root:
        test2 = args.recording_root / "test_002" / "test_002.svo2"
    elif local_test2.is_file():
        test2 = local_test2
    else:
        test2 = shared_test2
        print(f"Local test_002 copy not found; falling back to shared input: {test2}")
    test5 = args.test_005_svo
    for source in (test2, test5):
        if not source.is_file():
            if source == test5:
                parser.error(f"test_005 SVO not found: {source}; set --test-005-svo to its local SSD path")
            parser.error(f"test_002 SVO not found: {source}; set --recording-root or --test-002-svo")
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
            "Run this with the Python environment already configured for ZED SDK. "
            f"Import error: {exc}"
        )

    print(f"Python: {sys.executable}")
    print(f"ZED SDK: {sl.Camera.get_sdk_version()}")
    print(f"test_002 SVO: {test2}")
    print(f"test_005 SVO: {test5}")
    print(f"Local output: {local_batch}")
    print(f"Shared mirror target: {args.exchange_root}")

    package = Path(__file__).resolve().parent
    args.local_root.mkdir(parents=True, exist_ok=True)
    required_tools = []
    required_tools.extend(["exchange_copy.py", "sync_exchange.py"])
    if "test_002_depth" in args.operations or "test_005_depth" in args.operations:
        required_tools.append("export_zed_depth.py")
    if "test_002_body" in args.operations:
        required_tools.extend(["export_tracking.py", "validate_export.py"])
    try:
        worker_root = stage_worker_scripts(package, args.local_root, required_tools)
    except OSError as exc:
        parser.error(f"could not stage SDK worker scripts onto local disk: {exc}")
    test2_root = local_batch / "test_002"
    test5_root = local_batch / "test_005"
    test2_depth = test2_root / "depth_export"
    test2_body = test2_root / "body"
    test5_depth = test5_root / "depth_export"
    local_batch.mkdir(parents=True, exist_ok=False)
    test2_root.mkdir()
    test5_root.mkdir()

    inventory = [
        {"recording": "test_002", "svo_path": str(test2), "setup_id": args.setup_id_002},
        {"recording": "test_005", "svo_path": str(test5), "setup_id": args.setup_id_005},
    ]
    inventory_fields = ["recording", "svo_path", "setup_id"]
    write_csv(local_batch / "input_inventory.csv", inventory, inventory_fields)

    summary: list[dict] = []
    summary_fields = [
        "operation", "source_svo", "output", "status", "exit_code", "started_at", "log"
    ]
    summary_path = local_batch / "batch_summary.csv"
    env = os.environ.copy()
    env["CUDA_CACHE_DISABLE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def run(operation: str, source: Path, output: Path, log: Path, command: list[str]) -> bool:
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"[{operation}] starting; log: {log}", flush=True)
        with log.open("w", encoding="utf-8") as stream:
            stream.write(f"operation: {operation}\nsource_svo: {source}\noutput: {output}\n")
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
            stream.write(f"\nexporter_exit_code: {exit_code}\n")
            stream.flush()
        summary.append(
            {
                "operation": operation,
                "source_svo": str(source),
                "output": str(output),
                "status": "success" if exit_code == 0 else "failed",
                "exit_code": exit_code,
                "started_at": started_at,
                "log": str(log.relative_to(local_batch)),
            }
        )
        print(f"[{operation}] {summary[-1]['status']} (exit {exit_code})", flush=True)
        return exit_code == 0

    depth_tool = worker_root / "export_zed_depth.py"
    body_tool = worker_root / "export_tracking.py"
    validator = worker_root / "validate_export.py"

    if "test_002_depth" in args.operations:
        run(
            "test_002_depth", test2, test2_depth, test2_root / "depth_export.log",
            [sys.executable, str(depth_tool), str(test2), "--output", str(test2_depth),
             "--setup-id", args.setup_id_002, "--every-seconds", "0.5",
             "--pixel-stride", "8", "--depth-mode", "NEURAL"],
        )
    if "test_005_depth" in args.operations:
        run(
            "test_005_depth", test5, test5_depth, test5_root / "depth_export.log",
            [sys.executable, str(depth_tool), str(test5), "--output", str(test5_depth),
             "--setup-id", args.setup_id_005, "--every-seconds", "0.5",
             "--pixel-stride", "8", "--depth-mode", "NEURAL"],
        )
    body_succeeded = True
    if "test_002_body" in args.operations:
        body_succeeded = run(
            "test_002_body", test2, test2_body, test2_root / "body.log",
            [sys.executable, str(body_tool), str(test2), "--output", str(test2_body),
             "--mode", "body", "--setup-id", args.setup_id_002,
             "--image-period-s", "0.1", "--depth-mode", "NEURAL",
             "--detection-confidence", "35", "--minimum-keypoints", "8",
             "--prediction-timeout-s", "0.2", "--skeleton-smoothing", "0"],
        )
        if body_succeeded:
            run(
                "test_002_body_validation", test2, test2_body,
                test2_root / "body.validation.log",
                [sys.executable, str(validator), str(test2_body)],
            )
        else:
            summary.append(
                {
                    "operation": "test_002_body_validation", "source_svo": str(test2),
                    "output": str(test2_body), "status": "skipped", "exit_code": "",
                    "started_at": "", "log": "",
                }
            )

    try:
        write_csv(summary_path, summary, summary_fields)
    except OSError as exc:
        print(f"Could not write batch summary {summary_path}: {exc}", file=sys.stderr)
        print("Per-operation logs contain exporter_exit_code for recovery.", file=sys.stderr)
        return 1

    mirrored, mirror_message = copy_batch(local_batch, args.exchange_root)
    print(mirror_message, flush=True)
    if not mirrored:
        print("Reconnect the shared folder later and run the staged sync_exchange.py to mirror this local batch.")
    failed = [row for row in summary if row["status"] == "failed"]
    if failed:
        print(f"One or more exports failed. Review the local summary and recording logs: {summary_path}")
        return 1
    print(f"SDK exports complete. Local batch: {local_batch}")
    print("Setup IDs are separate by default; share one only when the camera setup is confirmed unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
