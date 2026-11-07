#!/usr/bin/env python3
"""Process exported group001 ZED model comparisons into corridor replay pages."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=int, default=2, help="first recording number (default: 2)")
    parser.add_argument("--last", type=int, default=48, help="last recording number (default: 48)")
    parser.add_argument(
        "--tag",
        default="20261103",
        help="Windows exchange folder suffix (default: 20261103)",
    )
    parser.add_argument(
        "--exchange-root",
        type=Path,
        default=Path("/data/experiment_data/kaiseki1103/exchange"),
    )
    parser.add_argument("--output-root", type=Path, default=PROJECT_DIR / "results")
    parser.add_argument('--input-tag',help='Input export tag; overrides --tag without changing the analysis version')
    parser.add_argument('--analysis-tag',help='New v2 run name, independent of the input tag')
    parser.add_argument('--tracking-config',type=Path)
    parser.add_argument('--annotations',type=Path)
    parser.add_argument(
        "--calibration",
        type=Path,
        default=PROJECT_DIR / "results/recording_001/zed_depth_review/zed_corridor_candidate.json",
    )
    parser.add_argument(
        "--lidar-candidate",
        type=Path,
        default=PROJECT_DIR / "results/recording_001/lidar_corridor_candidate.json",
    )
    args = parser.parse_args()

    if args.first < 1 or args.last < args.first:
        parser.error("recording range must satisfy 1 <= --first <= --last")
    if args.tracking_config:
        if not args.analysis_tag or Path(args.analysis_tag).name!=args.analysis_tag or args.analysis_tag in ['.','..']:
            parser.error('--tracking-config requires a single new --analysis-tag directory name')
        command=[sys.executable,'-m','body.process_tracking_v2',
                 '--exchange-root',str(args.exchange_root),'--input-tag',args.input_tag or args.tag,
                 '--recordings',','.join(map(str,range(args.first,args.last+1))),
                 '--output',str(args.output_root/'tracking_v2'/args.analysis_tag),
                 '--calibration',str(args.calibration),'--config',str(args.tracking_config)]
        if args.annotations:
            command.extend(['--annotations',str(args.annotations)])
        return subprocess.run(command).returncode
    if args.analysis_tag or args.annotations:
        parser.error('--analysis-tag and --annotations require --tracking-config')
    for required in (args.calibration, args.lidar_candidate):
        if not required.is_file():
            parser.error(f"required group001 calibration file not found: {required}")

    processor = "body.process_zed_model_comparison"
    succeeded: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    failed: list[str] = []

    for number in range(args.first, args.last + 1):
        recording = f"recording_{number:03d}"
        exchange_dir = args.exchange_root / recording / f"model_comparison_{args.input_tag or args.tag}"
        output_dir = args.output_root / recording / f"model_comparison_{args.tag}"
        if not exchange_dir.is_dir():
            print(f"[missing] {exchange_dir}")
            missing.append(recording)
            continue
        if output_dir.exists():
            if (output_dir / "index.html").is_file() and (output_dir / "selected/index.html").is_file():
                print(f"[skip] {recording}: report already exists at {output_dir}")
                skipped.append(recording)
            else:
                print(f"[incomplete output] {recording}: choose a new --tag or remove this partial output: {output_dir}")
                failed.append(recording)
            continue

        label = f"2026-11-02 / group001 / {recording}"
        command = [
            sys.executable,
            "-m",
            processor,
            str(exchange_dir),
            "--output-dir",
            str(output_dir),
            "--calibration",
            str(args.calibration),
            "--lidar-candidate",
            str(args.lidar_candidate),
            "--recording-label",
            label,
        ]
        print(f"[process] {recording}")
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"[failed] {recording}: processor exited with status {exc.returncode}")
            failed.append(recording)
        else:
            succeeded.append(recording)

    print("\nBatch summary")
    print(f"processed: {len(succeeded)} {', '.join(succeeded)}")
    print(f"already complete: {len(skipped)} {', '.join(skipped)}")
    print(f"missing exchange data: {len(missing)} {', '.join(missing)}")
    print(f"failed or incomplete: {len(failed)} {', '.join(failed)}")
    return 1 if missing or failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
