#!/usr/bin/env python3
"""Build a standalone synchronized video, skeleton, and corridor-trajectory replay."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def vec3(value) -> np.ndarray | None:
    if not isinstance(value, list) or len(value) < 3 or any(v is None for v in value[:3]):
        return None
    point = np.asarray(value[:3], dtype=float)
    return point if np.isfinite(point).all() else None


def to_corridor(point: np.ndarray, calibration: dict) -> list[float] | None:
    if point is None:
        return None
    floor = calibration["floor_plane_camera_image"]
    basis = calibration["corridor_basis_camera_image"]
    down = np.asarray(floor["normal_down"], dtype=float)
    floor_origin = -float(floor["offset_m"]) * down
    delta = point - floor_origin
    axes = [
        np.asarray(basis["X_into_hallway"], dtype=float),
        np.asarray(
            basis.get(
                "Y_positive_toward_ZED_visible_far_wall",
                basis.get("Y_positive_away_from_visible_wall"),
            ),
            dtype=float,
        ),
        np.asarray(basis["Z_up"], dtype=float),
    ]
    return [float(delta @ axis) for axis in axes]


def build_sensor_alignment(calibration: dict, lidar: dict) -> dict:
    visible_far_wall_y = float(calibration["visible_wall_Y_m"])
    corridor_width = float(lidar["wall_gap_m"])
    near_wall_y = visible_far_wall_y - corridor_width
    lidar_near = abs(float(lidar["wall_planes"][0]["lateral_offset_from_lidar_m"]))
    camera_height = float(calibration["camera_height_above_floor_m"])
    lidar_height = float(lidar["lidar_height_above_floor_m"])
    return {
        "method": "match ZED-visible far wall to the far LiDAR wall; infer the camera-side wall from corridor width",
        "lidar_position_in_camera_corridor_m": {
            "X": None,
            "Y": float(near_wall_y + lidar_near),
            "Z": float(lidar_height - camera_height),
        },
        "zed_visible_far_wall_Y_m": visible_far_wall_y,
        "camera_side_near_wall_Y_m_inferred": near_wall_y,
        "lidar_wall_gap_m": corridor_width,
        "lidar_near_wall_distance_m": lidar_near,
        "longitudinal_offset_status": "undetermined from parallel side walls and floor",
        "provisional": True,
        "assumptions": [
            "The ZED wall fit and LiDAR wall fits refer to the same two physical corridor boundaries.",
            "The LiDAR near-wall plane and inferred camera-side wall are the same boundary.",
            "The shared floor estimates represent the same floor height and both sensors stayed fixed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", type=Path, help="ZED replay export with camera.json, frames.csv, bodies.csv and images/")
    parser.add_argument(
        "--calibration",
        type=Path,
        help="defaults to ../zed_depth_review/zed_corridor_candidate.json",
    )
    parser.add_argument(
        "--lidar-candidate",
        type=Path,
        help="defaults to ../lidar_corridor_candidate.json",
    )
    parser.add_argument(
        "--time-alignment",
        type=Path,
        help="defaults to ../lidar_time_alignment_candidate.json",
    )
    parser.add_argument(
        "--recording-label",
        default="2026-11-02 / group001 / recording001",
        help="label displayed in the replay metadata",
    )
    args = parser.parse_args()

    export_dir = args.export_dir
    calibration_path = args.calibration or export_dir.parent / "zed_depth_review" / "zed_corridor_candidate.json"
    lidar_path = args.lidar_candidate or export_dir.parent / "lidar_corridor_candidate.json"
    time_path = args.time_alignment or export_dir.parent / "lidar_time_alignment_candidate.json"
    template_path = Path(__file__).with_name("group001_replay_template.html")
    if not template_path.is_file():
        raise FileNotFoundError(template_path)
    if not calibration_path.is_file() or not lidar_path.is_file():
        raise FileNotFoundError("ZED corridor and LiDAR corridor calibration files are required.")

    camera = json.loads((export_dir / "camera.json").read_text(encoding="utf-8"))
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    lidar = json.loads(lidar_path.read_text(encoding="utf-8"))
    time_alignment = json.loads(time_path.read_text(encoding="utf-8")) if time_path.is_file() else None
    frame_rows = read_csv(export_dir / "frames.csv")
    body_rows = read_csv(export_dir / "bodies.csv")
    if not frame_rows:
        raise RuntimeError("The ZED export has no sampled frames.")
    origin_ns = int(frame_rows[0]["image_timestamp_ns"])

    frames = []
    sample_index_to_time: dict[int, float] = {}
    for row in frame_rows:
        sample_index = int(row["sample_index"])
        timestamp_ns = int(row["image_timestamp_ns"])
        elapsed_s = (timestamp_ns - origin_ns) / 1e9
        sample_index_to_time[sample_index] = elapsed_s
        image_path = export_dir / row["image_file"]
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        frames.append(
            {
                "sample_index": sample_index,
                "frame_index": int(row["frame_index"]),
                "timestamp_ns": timestamp_ns,
                "t": elapsed_s,
                "image": row["image_file"].replace("\\", "/"),
                "body_count": int(row["body_count"]),
            }
        )

    bodies = []
    track_map: dict[str, list[dict]] = {}
    for row in body_rows:
        sample_index = int(row["sample_index"])
        if sample_index not in sample_index_to_time:
            continue
        try:
            pixels_raw = json.loads(row["keypoints_2d_json"])
            joints_raw = json.loads(row["keypoints_3d_camera_json"])
            confidence = json.loads(row["keypoint_confidence_json"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed body arrays at sample {sample_index}") from exc
        joints = [to_corridor(vec3(p), calibration) if vec3(p) is not None else None for p in joints_raw]
        pelvis_conf = confidence[0] if confidence else None
        state = row["tracking_state"].upper()
        valid_root = bool(joints and joints[0] and state == "OK" and pelvis_conf is not None and float(pelvis_conf) >= 20)
        body = {
            "sample_index": sample_index,
            "frame_index": int(row["frame_index"]),
            "t": sample_index_to_time[sample_index],
            "id": int(row["body_id"]),
            "state": row["tracking_state"],
            "confidence": float(row["confidence"]) if row["confidence"] else None,
            "pixels": pixels_raw,
            "joints": joints,
            "joint_confidence": confidence,
            "root_valid": valid_root,
        }
        bodies.append(body)
        if valid_root:
            track_map.setdefault(str(body["id"]), []).append(
                {
                    "t": body["t"], "x": joints[0][0], "y": joints[0][1], "z": joints[0][2],
                    "confidence": body["confidence"], "sample_index": sample_index,
                }
            )

    palette = ["#0b8a67", "#285db5", "#cc6b16", "#a4488f", "#12899a", "#9c4c39"]
    first_seen = sorted(track_map, key=lambda identity: track_map[identity][0]["t"])
    labels = {identity: f"人{index + 1}（ZED ID {identity}）" for index, identity in enumerate(first_seen)}
    tracks = [
        {
            "id": int(identity),
            "label": labels[identity],
            "color": palette[index % len(palette)],
            "points": sorted(track_map[identity], key=lambda point: point["t"]),
        }
        for index, identity in enumerate(first_seen)
    ]
    alignment = build_sensor_alignment(calibration, lidar)
    x_values = [p["x"] for track in tracks for p in track["points"]]
    x_bounds = [min([0.0, *x_values]) - 0.5, max([15.0, *x_values]) + 1.0]
    wall_b = float(calibration["visible_wall_Y_m"])
    wall_a = wall_b - float(lidar["wall_gap_m"])
    result = {
        "recording": args.recording_label,
        "timeline_origin_ns": str(origin_ns),
        "duration_s": frames[-1]["t"],
        "camera": camera,
        "corridor": {
            "origin": "ZED optical-center projection onto the floor; camera X=0, floor Z=0",
            "positive_X": "from the camera into the observed hallway",
            "positive_Y": "from the camera-side near wall toward the ZED-visible far wall",
            "positive_Z": "up",
            "wall_y_m": [wall_a, wall_b],
            "wall_gap_m_from_lidar": float(lidar["wall_gap_m"]),
            "x_bounds_m": x_bounds,
            "camera_height_m": float(calibration["camera_height_above_floor_m"]),
            "camera_axes_in_zed_image_frame": calibration["corridor_basis_camera_image"],
            "sensor_alignment": alignment,
            "provisional_calibration": True,
        },
        "frames": frames,
        "body_observations": bodies,
        "tracks": tracks,
        "lidar_time_alignment": {
            "method": "use Livox PointCloud2 header timestamps and ZED image timestamps on the shared epoch clock",
            "lidar_first_header_relative_to_camera_s": (
                (int(time_alignment["lidar_first_pointcloud_header_timestamp_ns"]) - origin_ns) / 1e9
                if time_alignment else None
            ),
            "lidar_first_mcap_record_relative_to_camera_s": (
                (int(time_alignment["lidar_first_pointcloud_mcap_record_timestamp_ns"]) - origin_ns) / 1e9
                if time_alignment else None
            ),
            "header_vs_record_median_delay_s": time_alignment.get("median_record_minus_header_s") if time_alignment else None,
            "note": "LiDAR detections are not rendered as person tracks in this version; LiDAR supplies corridor width and floor geometry.",
        },
    }
    (export_dir / "corridor_trajectories.json").write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    with (export_dir / "corridor_trajectories.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["t_s", "body_id", "label", "X_m", "Y_m", "pelvis_Z_m", "confidence", "sample_index"])
        writer.writeheader()
        for track in tracks:
            for point in track["points"]:
                writer.writerow({
                    "t_s": f"{point['t']:.6f}", "body_id": track["id"], "label": track["label"],
                    "X_m": f"{point['x']:.4f}", "Y_m": f"{point['y']:.4f}",
                    "pelvis_Z_m": f"{point['z']:.4f}", "confidence": point["confidence"],
                    "sample_index": point["sample_index"],
                })

    template = template_path.read_text(encoding="utf-8")
    html = template.replace("__REPLAY_DATA__", json.dumps(result, ensure_ascii=False).replace("<", "\\u003c"))
    (export_dir / "index.html").write_text(html, encoding="utf-8")
    print(json.dumps({
        "index_html": str(export_dir / "index.html"),
        "trajectory_csv": str(export_dir / "corridor_trajectories.csv"),
        "sampled_frames": len(frames),
        "body_observations": len(bodies),
        "tracks": [{"label": track["label"], "valid_positions": len(track["points"])} for track in tracks],
        "lidar_position_candidate": alignment["lidar_position_in_camera_corridor_m"],
        "lidar_first_header_relative_to_camera_s": result["lidar_time_alignment"]["lidar_first_header_relative_to_camera_s"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
