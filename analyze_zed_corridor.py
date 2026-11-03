#!/usr/bin/env python3
"""Estimate the camera-relative floor and visible corridor wall from exported ZED depth."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def repeated_voxel_centers(points: np.ndarray, frame_ids: np.ndarray, voxel_m: float = 0.06) -> np.ndarray:
    """Keep voxel centers observed in at least three distinct sampled frames."""
    voxel = np.floor(points / voxel_m).astype(np.int32)
    _, inverse = np.unique(voxel, axis=0, return_inverse=True)
    frame_span = int(frame_ids.max()) + 1
    paired = np.unique(inverse.astype(np.int64) * frame_span + frame_ids.astype(np.int64))
    frame_counts = np.bincount((paired // frame_span).astype(np.int32), minlength=int(inverse.max()) + 1)
    sums = np.zeros((len(frame_counts), 3), dtype=np.float64)
    counts = np.zeros(len(frame_counts), dtype=np.int32)
    np.add.at(sums, inverse, points)
    np.add.at(counts, inverse, 1)
    recurrent = frame_counts >= 3
    return sums[recurrent] / counts[recurrent, None]


def fit_plane_ransac(
    points: np.ndarray,
    *,
    kind: str,
    floor_normal: np.ndarray | None = None,
    threshold_m: float = 0.08,
    iterations: int = 2200,
    seed: int = 20261103,
) -> tuple[np.ndarray, float, np.ndarray]:
    """Fit a large floor- or side-wall-like plane and return its inlier mask."""
    rng = np.random.default_rng(seed)
    best_count = 0
    best_model: tuple[np.ndarray, float] | None = None
    for _ in range(iterations):
        sample = points[rng.choice(len(points), size=3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        norm = float(np.linalg.norm(normal))
        if norm < 1e-8:
            continue
        normal /= norm
        if kind == "floor" and abs(float(normal[1])) < 0.70:
            continue
        if kind == "wall" and floor_normal is not None and abs(float(normal @ floor_normal)) > 0.35:
            continue
        offset = -float(normal @ sample[0])
        inliers = np.abs(points @ normal + offset) < threshold_m
        count = int(inliers.sum())
        if count > best_count:
            best_count = count
            best_model = (normal, offset)

    if best_model is None or best_count < 250:
        raise RuntimeError(f"Could not find a stable {kind} plane in the repeated depth points.")

    normal, offset = best_model
    inliers = np.abs(points @ normal + offset) < threshold_m
    selected = points[inliers]
    center = selected.mean(axis=0)
    _, _, vectors = np.linalg.svd(selected - center, full_matrices=False)
    normal = vectors[-1]
    if kind == "floor" and normal[1] < 0:
        normal = -normal
    if kind == "wall" and normal[0] < 0:
        normal = -normal
    offset = -float(normal @ center)
    inliers = np.abs(points @ normal + offset) < threshold_m
    return normal, offset, inliers


def svg_cross_section(path: Path, visible_wall_y_m: float, near_wall_y_m: float | None) -> None:
    """Draw the estimated camera and side-wall locations in the lateral axis."""
    width, height = 960, 460
    x0, x1 = -1.0, 3.0
    left, right = 100, 55
    y = 260

    def sx(value: float) -> float:
        return left + (value - x0) / (x1 - x0) * (width - left - right)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="50" y="45" font-family="sans-serif" font-size="22" font-weight="bold">Recording 001: camera-relative corridor cross-section</text>',
        '<text x="50" y="76" font-family="sans-serif" font-size="14" fill="#555">ZED wall fit; opposite wall is inferred from the LiDAR wall gap</text>',
        f'<line x1="{sx(x0):.1f}" y1="{y}" x2="{sx(x1):.1f}" y2="{y}" stroke="#555" stroke-width="2"/>',
    ]
    for value in np.arange(-1.0, 3.01, 0.5):
        xx = sx(float(value))
        parts.append(f'<line x1="{xx:.1f}" y1="{y-7}" x2="{xx:.1f}" y2="{y+7}" stroke="#555"/>')
        parts.append(f'<text x="{xx:.1f}" y="{y+30}" text-anchor="middle" font-family="sans-serif" font-size="13">{value:.1f}</text>')
    parts.append(f'<text x="{sx(0):.1f}" y="{y-105}" text-anchor="middle" font-family="sans-serif" font-size="14">camera projection</text>')
    parts.append(f'<circle cx="{sx(0):.1f}" cy="{y}" r="8" fill="#225ea8"/>')
    parts.append(f'<line x1="{sx(visible_wall_y_m):.1f}" y1="{y-75}" x2="{sx(visible_wall_y_m):.1f}" y2="{y+10}" stroke="#d73027" stroke-width="5"/>')
    parts.append(f'<text x="{sx(visible_wall_y_m):.1f}" y="{y-88}" text-anchor="middle" font-family="sans-serif" font-size="14" fill="#a51f1b">ZED-visible far wall {visible_wall_y_m:.2f} m</text>')
    if near_wall_y_m is not None and x0 < near_wall_y_m < x1:
        parts.append(f'<line x1="{sx(near_wall_y_m):.1f}" y1="{y-75}" x2="{sx(near_wall_y_m):.1f}" y2="{y+10}" stroke="#8c6bb1" stroke-width="4" stroke-dasharray="8 6"/>')
        parts.append(f'<text x="{sx(near_wall_y_m):.1f}" y="{y+65}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#68428d">camera-side wall ≈ {near_wall_y_m:.2f} m</text>')
    parts.append(f'<text x="{(left + width - right)/2:.1f}" y="{height-40}" text-anchor="middle" font-family="sans-serif" font-size="15">Y (m), positive toward the ZED-visible far wall</text>')
    parts.append('</svg>')
    path.write_text('\n'.join(parts) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("depth_dir", type=Path, help="folder containing zed_depth_points.npz and camera.json")
    parser.add_argument("--lidar-candidate", type=Path, help="optional lidar_corridor_candidate.json for width inference")
    parser.add_argument("--output-dir", type=Path, help="defaults to depth_dir")
    args = parser.parse_args()

    depth_dir = args.depth_dir
    output_dir = args.output_dir or depth_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    data = np.load(depth_dir / "zed_depth_points.npz")
    points = data["points_camera_image_m"].astype(np.float64)
    frame_ids = data["point_frame_index"].astype(np.int32)
    centers = repeated_voxel_centers(points, frame_ids)

    floor_normal, floor_offset, floor_mask = fit_plane_ransac(centers, kind="floor", seed=20261103)
    floor_points = centers[~(np.abs(centers @ floor_normal + floor_offset) < 0.12)]
    wall_normal, wall_offset, wall_mask = fit_plane_ransac(
        floor_points,
        kind="wall",
        floor_normal=floor_normal,
        seed=20261104,
    )

    # The LiDAR camera convention is IMAGE (x right, y down, z forward).
    up = -floor_normal
    camera_forward = np.array([0.0, 0.0, 1.0])
    corridor_x = np.cross(up, wall_normal)
    corridor_x /= np.linalg.norm(corridor_x)
    if corridor_x @ camera_forward < 0:
        corridor_x = -corridor_x
    corridor_y = np.cross(up, corridor_x)
    corridor_y /= np.linalg.norm(corridor_y)
    camera_floor_projection = -floor_offset * floor_normal
    # Solve n·(floor_projection + y*corridor_y) + offset = 0.
    # The negative sign is required; the fitted wall lies in +Y for this basis.
    wall_y = float(-(wall_normal @ camera_floor_projection + wall_offset) / (wall_normal @ corridor_y))
    visible_wall_distance = abs(wall_y)
    camera_height = abs(float(floor_offset))

    lidar = None
    lidar_path = args.lidar_candidate
    if lidar_path is None:
        candidate = depth_dir.parent / "lidar_corridor_candidate.json"
        if candidate.is_file():
            lidar_path = candidate
    other_wall_y = None
    if lidar_path is not None and lidar_path.is_file():
        lidar = json.loads(lidar_path.read_text(encoding="utf-8"))
        # Use only the independent LiDAR width; this assumes the ZED plane is one of those boundaries.
        other_wall_y = wall_y - float(lidar["wall_gap_m"])

    metadata = json.loads((depth_dir / "camera.json").read_text(encoding="utf-8"))
    result = {
        "method": "recurrent-depth-voxel plane fitting; camera frame transformed to floor/corridor basis",
        "provisional": True,
        "source_depth_dir": str(depth_dir.resolve()),
        "source_depth_mode": metadata.get("depth_mode"),
        "source_sdk_version": metadata.get("sdk_version"),
        "sampled_depth_frames": int(len(data["frame_indices"])),
        "depth_points": int(len(points)),
        "recurrent_voxels_used": int(len(centers)),
        "floor_plane_camera_image": {
            "normal_down": floor_normal.tolist(),
            "offset_m": float(floor_offset),
            "inlier_recurrent_voxels": int(floor_mask.sum()),
            "median_abs_residual_m": float(np.median(np.abs(centers[floor_mask] @ floor_normal + floor_offset))),
        },
        "visible_wall_plane_camera_image": {
            "normal": wall_normal.tolist(),
            "offset_m": float(wall_offset),
            "inlier_recurrent_voxels": int(wall_mask.sum()),
            "median_abs_residual_m": float(np.median(np.abs(floor_points[wall_mask] @ wall_normal + wall_offset))),
        },
        "corridor_basis_camera_image": {
            "X_into_hallway": corridor_x.tolist(),
            "Y_positive_toward_ZED_visible_far_wall": corridor_y.tolist(),
            "Z_up": up.tolist(),
        },
        "camera_position_in_floor_origin_basis_m": [0.0, 0.0, camera_height],
        "camera_height_above_floor_m": camera_height,
        "visible_wall_Y_m": wall_y,
        "camera_to_visible_wall_m": visible_wall_distance,
        "other_wall_inference": None,
        "notes": [
            "The camera is at X=0; the origin is its optical-center projection onto the floor, and Z=0 is the floor.",
            "Y is positive toward the wall fitted in ZED depth; the camera-side near wall is inferred on the negative-Y side.",
            "Any opposite-wall position inferred from the LiDAR wall gap assumes both sensors observe the same corridor boundaries.",
        ],
    }
    if lidar is not None:
        result["other_wall_inference"] = {
            "method": "ZED-visible far-wall position minus LiDAR-only corridor wall gap",
            "lidar_wall_gap_m": float(lidar["wall_gap_m"]),
            "opposite_wall_Y_m_assuming_same_boundaries": float(other_wall_y),
            "camera_distance_to_opposite_wall_m_assuming_same_boundaries": abs(float(other_wall_y)),
            "provisional": True,
        }

    json_path = output_dir / "zed_corridor_candidate.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    svg_path = output_dir / "zed_corridor_cross_section.svg"
    svg_cross_section(svg_path, wall_y, other_wall_y)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"cross_section: {svg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
