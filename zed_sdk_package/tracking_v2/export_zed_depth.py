#!/usr/bin/env python3
"""Export sparse metric depth points and review images from an SVO2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("svo", type=Path, help="local .svo or .svo2 path on a ZED SDK PC")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--every-seconds", type=float, default=0.5)
    parser.add_argument("--frame-indices", nargs="+", type=int, help="zero-based acquired frame indices to save instead of periodic sampling")
    parser.add_argument("--match-body-depth-settings", action="store_true", help="use the same depth range and SDK runtime defaults as export_tracking.py")
    parser.add_argument("--pixel-stride", type=int, default=8)
    parser.add_argument("--depth-mode", default="NEURAL")
    parser.add_argument("--setup-id", required=True, help="unique ID for this physical camera setup")
    parser.add_argument("--jpeg-quality", type=int, default=88)
    parser.add_argument("--point-archive-mode", choices=("compressed", "stored"), default="compressed", help="NPZ compression; stored uses more local disk space")
    args = parser.parse_args()
    if not args.svo.is_file():
        parser.error(f"SVO file does not exist: {args.svo}")
    if args.every_seconds <= 0 or args.pixel_stride <= 0 or not 1 <= args.jpeg_quality <= 100:
        parser.error("--every-seconds and --pixel-stride must be positive; --jpeg-quality must be in [1, 100]")
    if args.frame_indices is not None and (min(args.frame_indices) < 0 or len(args.frame_indices) != len(set(args.frame_indices))):
        parser.error("--frame-indices must contain unique nonnegative indices")
    if not args.setup_id.strip():
        parser.error("--setup-id cannot be blank")
    if args.depth_mode.upper() not in {"NEURAL", "ULTRA", "PERFORMANCE"}:
        parser.error("--depth-mode must be NEURAL, ULTRA, or PERFORMANCE")
    if args.output.exists():
        parser.error(f"output directory already exists; choose a new path: {args.output}")
    timing_start = time.perf_counter()
    source_sha256 = sha256_file(args.svo)
    source_hash_seconds = time.perf_counter() - timing_start
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "images").mkdir()

    sdk_start = time.perf_counter()
    import pyzed.sl as sl

    init = sl.InitParameters()
    init.set_from_svo_file(str(args.svo.resolve()))
    init.svo_real_time_mode = False
    init.coordinate_units = sl.UNIT.METER
    init.coordinate_system = sl.COORDINATE_SYSTEM.IMAGE
    if args.match_body_depth_settings:
        init.depth_minimum_distance = 0.25
        init.depth_maximum_distance = 25.0
    try:
        init.depth_mode = getattr(sl.DEPTH_MODE, args.depth_mode.upper())
    except AttributeError as exc:
        parser.error(f"unknown SDK depth mode: {args.depth_mode!r}")
        raise exc

    camera = sl.Camera()
    status = camera.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise RuntimeError(f"ZED failed to open SVO: {status}")
    sdk_init_seconds = time.perf_counter() - sdk_start

    depth = sl.Mat()
    image = sl.Mat()
    runtime = sl.RuntimeParameters()
    if not args.match_body_depth_settings:
        runtime.confidence_threshold = 50
    else:
        runtime.measure3D_reference_frame = sl.REFERENCE_FRAME.CAMERA
    requested_frames = set(args.frame_indices) if args.frame_indices is not None else None
    frames: list[dict] = []
    point_parts: list[np.ndarray] = []
    frame_index_parts: list[np.ndarray] = []
    next_sample_s = 0.0
    first_timestamp_ns = None
    frame_index = 0
    frames_start = time.perf_counter()
    try:
        info = camera.get_camera_information()
        cfg = info.camera_configuration
        width, height = int(cfg.resolution.width), int(cfg.resolution.height)
        intr = cfg.calibration_parameters.left_cam
        fx, fy, cx, cy = map(float, (intr.fx, intr.fy, intr.cx, intr.cy))
        expected_frames = int(camera.get_svo_number_of_frames())
        while True:
            grab_status = camera.grab(runtime)
            if grab_status == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
                break
            if grab_status != sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(f"grab failed at frame {frame_index}: {grab_status}")
            svo_position = int(camera.get_svo_position())
            if svo_position != frame_index:
                raise RuntimeError(f"SVO frame position mismatch: expected {frame_index}, got {svo_position}")
            stamp_ns = int(camera.get_timestamp(sl.TIME_REFERENCE.IMAGE).get_nanoseconds())
            if first_timestamp_ns is None:
                first_timestamp_ns = stamp_ns
            elapsed_s = (stamp_ns - first_timestamp_ns) / 1e9
            selected = frame_index in requested_frames if requested_frames is not None else elapsed_s + 1e-6 >= next_sample_s
            if selected:
                status = camera.retrieve_measure(depth, sl.MEASURE.DEPTH, sl.MEM.CPU)
                if status != sl.ERROR_CODE.SUCCESS:
                    raise RuntimeError(f"retrieve_measure(DEPTH) failed at frame {frame_index}: {status}")
                depth_m = np.asarray(depth.get_data(), dtype=np.float32).squeeze()
                if depth_m.shape != (height, width):
                    raise RuntimeError(f"unexpected depth image shape at frame {frame_index}: {depth_m.shape}")
                vv, uu = np.mgrid[0:height:args.pixel_stride, 0:width:args.pixel_stride]
                zz = depth_m[vv, uu]
                valid = np.isfinite(zz) & (zz > 0.25) & (zz < 30.0)
                u = uu[valid].astype(np.float32)
                v = vv[valid].astype(np.float32)
                z = zz[valid].astype(np.float32)
                xyz = np.column_stack(((u - cx) * z / fx, (v - cy) * z / fy, z))
                sample_index = len(frames)
                point_parts.append(xyz.astype(np.float32, copy=False))
                frame_index_parts.append(np.full(len(xyz), sample_index, dtype=np.int32))

                status = camera.retrieve_image(image, sl.VIEW.LEFT, sl.MEM.CPU)
                if status != sl.ERROR_CODE.SUCCESS:
                    raise RuntimeError(f"retrieve_image(VIEW.LEFT) failed at frame {frame_index}: {status}")
                bgra = np.asarray(image.get_data())
                if bgra.ndim != 3 or bgra.shape[2] != 4:
                    raise RuntimeError(f"expected a BGRA image, got {bgra.shape}")
                image_file = f"images/frame_{frame_index:08d}.jpg"
                bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
                if not cv2.imwrite(str(args.output / image_file), bgr, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality]):
                    raise OSError(f"could not save {image_file}")
                image_sha256 = sha256_file(args.output / image_file)
                frames.append(
                    {
                        "sample_index": sample_index,
                        "frame_index": frame_index,
                        "svo_frame_index": svo_position,
                        "image_timestamp_ns": stamp_ns,
                        "elapsed_s": elapsed_s,
                        "image_file": image_file,
                        "image_width": int(bgr.shape[1]),
                        "image_height": int(bgr.shape[0]),
                        "image_sha256": image_sha256,
                        "valid_depth_points": int(len(xyz)),
                    }
                )
                next_sample_s = elapsed_s + args.every_seconds
            frame_index += 1
    finally:
        camera.close()
    frames_seconds = time.perf_counter() - frames_start

    if frame_index != expected_frames:
        raise RuntimeError(f"incomplete SVO: read {frame_index} of {expected_frames} frames")
    if requested_frames is not None and {f['frame_index'] for f in frames} != requested_frames:
        raise RuntimeError("one or more requested frame indices were not present in the SVO")
    if not frames:
        raise RuntimeError("no SVO frames or valid depth samples were read")
    archive_start = time.perf_counter()
    points = np.concatenate(point_parts) if point_parts else np.empty((0, 3), np.float32)
    point_frame_index = np.concatenate(frame_index_parts) if frame_index_parts else np.empty((0,), np.int32)
    save_archive = np.savez_compressed if args.point_archive_mode == "compressed" else np.savez
    save_archive(
        args.output / "zed_depth_points.npz",
        points_camera_image_m=points,
        point_frame_index=point_frame_index,
        frame_indices=np.asarray([f["sample_index"] for f in frames], dtype=np.int32),
        frame_timestamps_ns=np.asarray([f["image_timestamp_ns"] for f in frames], dtype=np.int64),
    )
    archive_seconds = time.perf_counter() - archive_start
    with (args.output / "frames.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(frames[0]))
        writer.writeheader()
        writer.writerows(frames)
    camera_json = {
        "source_svo": str(args.svo.resolve()),
        "source_svo_sha256": source_sha256,
        "sdk_version": str(sl.Camera.get_sdk_version()),
        "camera_model": str(getattr(info.camera_model, "name", info.camera_model)),
        "serial_number": int(info.serial_number),
        "setup_id": args.setup_id,
        "width": width,
        "height": height,
        "resolution": {"width": width, "height": height},
        "fps": float(cfg.fps),
        "intrinsics_left": {"fx": fx, "fy": fy, "cx": cx, "cy": cy},
        "image_view": "VIEW.LEFT (rectified)",
        "coordinate_system": "IMAGE (x right, y down, z forward)",
        "coordinate_units": "meter",
        "point_coordinate_system": "ZED IMAGE (x right, y down, z forward)",
        "units": "meter",
        "depth_mode": args.depth_mode.upper(),
        "sample_period_s": args.every_seconds,
        "requested_frame_indices": sorted(requested_frames) if requested_frames is not None else None,
        "match_body_depth_settings": args.match_body_depth_settings,
        "depth_minimum_distance": float(init.depth_minimum_distance),
        "depth_maximum_distance": float(init.depth_maximum_distance),
        "runtime_confidence_threshold": float(runtime.confidence_threshold),
        "pixel_stride": args.pixel_stride,
        "point_archive_mode": args.point_archive_mode,
        "total_svo_frames_read": frame_index,
        "depth_sample_frames": len(frames),
        "valid_depth_points": int(len(points)),
        "first_image_timestamp_ns": int(frames[0]["image_timestamp_ns"]),
        "last_image_timestamp_ns": int(frames[-1]["image_timestamp_ns"]),
        "elapsed_s": float(frames[-1]["elapsed_s"]),
        "processing_timing_seconds": {"source_hash": source_hash_seconds, "sdk_init": sdk_init_seconds,
                                      "grab_and_save_images": frames_seconds, "point_archive": archive_seconds},
    }
    (args.output / "camera.json").write_text(
        json.dumps(camera_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    file_hashes = {
        "camera.json": sha256_file(args.output / "camera.json"),
        "frames.csv": sha256_file(args.output / "frames.csv"),
        "zed_depth_points.npz": sha256_file(args.output / "zed_depth_points.npz"),
    }
    file_hashes.update({
        frame["image_file"]: frame["image_sha256"] for frame in frames
    })
    manifest = {
        "source_svo": str(args.svo.resolve()),
        "source_svo_sha256": source_sha256,
        "setup_id": args.setup_id,
        "status": "complete",
        "sample_count": len(frames),
        "total_svo_frames_read": frame_index,
        "files_sha256": file_hashes,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
