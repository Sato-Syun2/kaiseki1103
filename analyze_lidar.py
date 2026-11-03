#!/usr/bin/env python3
"""Independently estimate Group 001 corridor geometry from a ROS 2 MCAP bag."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from rosbag2_py import ConverterOptions, SequentialReader, StorageOptions
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
from sensor_msgs_py import point_cloud2


def read_bag(bag: Path) -> tuple[np.ndarray, np.ndarray, int, int]:
    reader = SequentialReader()
    reader.open(
        StorageOptions(uri=str(bag), storage_id="mcap"),
        ConverterOptions(
            input_serialization_format="cdr", output_serialization_format="cdr"
        ),
    )
    type_by_topic = {item.name: item.type for item in reader.get_all_topics_and_types()}
    lidar_type = get_message(type_by_topic["/livox/lidar"])
    imu_type = get_message(type_by_topic["/livox/imu"])
    clouds: list[np.ndarray] = []
    accelerations: list[list[float]] = []
    cloud_count = imu_count = 0
    while reader.has_next():
        topic, serialized, _ = reader.read_next()
        if topic == "/livox/lidar":
            msg = deserialize_message(serialized, lidar_type)
            points = point_cloud2.read_points_numpy(
                msg, field_names=("x", "y", "z"), skip_nans=True
            ).astype(np.float32, copy=False).reshape(-1, 3)
            points = points[np.linalg.norm(points, axis=1) > 0.3]
            if len(points):
                clouds.append(points)
            cloud_count += 1
        elif topic == "/livox/imu":
            msg = deserialize_message(serialized, imu_type)
            a = msg.linear_acceleration
            accelerations.append([a.x, a.y, a.z])
            imu_count += 1
    if not clouds or not accelerations:
        raise RuntimeError("The bag must contain /livox/lidar and /livox/imu data.")
    return np.concatenate(clouds), np.asarray(accelerations, dtype=np.float64), cloud_count, imu_count


def fit_dominant_line(points: np.ndarray, rng: np.random.Generator, iterations: int = 900):
    """RANSAC a line in horizontal coordinates, then refit its inliers by PCA."""
    best_count = 0
    best_mask = None
    tolerance_m = 0.06
    for _ in range(iterations):
        a, b = points[rng.integers(0, len(points), size=2)]
        direction = b - a
        normal = np.array([-direction[1], direction[0]])
        norm = np.linalg.norm(normal)
        if norm < 1e-5:
            continue
        normal /= norm
        distance = np.abs(points @ normal - a @ normal)
        inliers = distance < tolerance_m
        count = int(inliers.sum())
        if count > best_count:
            best_count, best_mask = count, inliers
    if best_mask is None or best_count < max(200, len(points) * 0.015):
        raise RuntimeError("No stable long wall line was found in the LiDAR points.")

    inliers = points[best_mask]
    center = inliers.mean(axis=0)
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(inliers.T))
    direction = eigenvectors[:, -1]
    direction *= 1.0 if direction[0] >= 0 else -1.0
    normal = np.array([-direction[1], direction[0]])
    offset = float(normal @ center)
    along = inliers @ direction
    return {
        "count": int(len(inliers)),
        "direction_2d": direction,
        "normal_2d": normal,
        "offset_m": offset,
        "span_m": [float(along.min()), float(along.max())],
        "inlier_points": inliers,
        "eigenvalues": eigenvalues,
    }


def estimate_geometry(points: np.ndarray, accelerations: np.ndarray) -> dict:
    rng = np.random.default_rng(20261102)
    mean_accel = accelerations.mean(axis=0)
    gravity_magnitude = float(np.linalg.norm(mean_accel))
    up = mean_accel / gravity_magnitude
    height_projection = points @ up
    ranges = np.linalg.norm(points, axis=1)

    # The floor is the dominant near-field plane below the sensor, aligned to IMU gravity.
    near = ranges < 20.0
    bins = np.arange(-4.0, -1.0, 0.01)
    counts, edges = np.histogram(height_projection[near], bins=bins)
    floor_index = int(np.argmax(counts))
    floor_offset = float((edges[floor_index] + edges[floor_index + 1]) / 2)
    floor_height_m = abs(floor_offset)

    # Build an orthonormal horizontal basis from LiDAR X and the IMU up vector.
    horizontal_x = np.array([1.0, 0.0, 0.0])
    horizontal_x -= up * float(horizontal_x @ up)
    horizontal_x /= np.linalg.norm(horizontal_x)
    horizontal_y = np.cross(up, horizontal_x)
    horizontal_y /= np.linalg.norm(horizontal_y)
    horizontal = np.column_stack((points @ horizontal_x, points @ horizontal_y))
    elevation = height_projection - floor_offset

    # Side-wall samples: above the floor, below the ceiling, and in the useful LiDAR range.
    wall_mask = (elevation > 0.35) & (elevation < 1.9) & (ranges < 25.0)
    wall_points = horizontal[wall_mask]
    if len(wall_points) > 120_000:
        wall_points = wall_points[rng.choice(len(wall_points), 120_000, replace=False)]

    first = fit_dominant_line(wall_points, rng)
    residual = wall_points[
        np.abs(wall_points @ first["normal_2d"] - first["offset_m"]) > 0.15
    ]
    second = fit_dominant_line(residual, rng)
    lines = [first, second]

    # Use the most distant wall return to orient positive X into the observed corridor.
    axis_2d = first["direction_2d"].copy()
    along_all = horizontal @ axis_2d
    if abs(float(np.quantile(along_all[wall_mask], 0.99))) < abs(
        float(np.quantile(along_all[wall_mask], 0.01))
    ):
        axis_2d *= -1.0
    lateral_2d = np.array([-axis_2d[1], axis_2d[0]])
    # Each fitted line is parallel to the corridor; project its inliers to one shared lateral axis.
    line_offsets = [
        (float(np.median(line["inlier_points"] @ lateral_2d)), line) for line in lines
    ]
    line_offsets.sort(key=lambda pair: pair[0])
    wall_offsets = [offset for offset, _ in line_offsets]

    # Positive X must point toward the side of the scan with the longer visible reach.
    axis_lidar = horizontal_x * axis_2d[0] + horizontal_y * axis_2d[1]
    lateral_lidar = horizontal_x * lateral_2d[0] + horizontal_y * lateral_2d[1]
    wall_records = []
    for offset, line in line_offsets:
        along = line["inlier_points"] @ axis_2d
        wall_records.append(
            {
                "point_count": line["count"],
                "lateral_offset_from_lidar_m": offset,
                "longitudinal_span_relative_to_lidar_m": [
                    float(along.min()), float(along.max())
                ],
            }
        )
    return {
        "method": "IMU gravity projection plus RANSAC of repeated vertical LiDAR surfaces",
        "source_frame": "livox_frame",
        "provisional": True,
        "imu_mean_acceleration": mean_accel.tolist(),
        "imu_mean_magnitude_g": gravity_magnitude,
        "up_axis_in_lidar_frame": up.tolist(),
        "floor_offset_projection_m": floor_offset,
        "lidar_height_above_floor_m": floor_height_m,
        "corridor_x_axis_in_lidar_frame": axis_lidar.tolist(),
        "corridor_y_axis_in_lidar_frame": lateral_lidar.tolist(),
        "wall_planes": wall_records,
        "wall_gap_m": float(wall_offsets[-1] - wall_offsets[0]),
        "origin": "LiDAR origin for this provisional candidate; camera origin pending ZED depth.",
        "notes": [
            "The wall fits are candidates from one recording and require cross-check against ZED depth.",
            "Camera-to-LiDAR longitudinal offset is not estimated by this LiDAR-only pass.",
        ],
        "_plot_data": {
            "points": horizontal[wall_mask],
            "axis_2d": axis_2d,
            "lateral_2d": lateral_2d,
            "wall_offsets": wall_offsets,
            "wall_spans": [r["longitudinal_span_relative_to_lidar_m"] for r in wall_records],
        },
    }


def save_plot(geometry: dict, output: Path) -> None:
    data = geometry.pop("_plot_data")
    points = data["points"]
    if len(points) > 30_000:
        points = points[:: max(1, len(points) // 30_000)]
    xy = np.column_stack((points @ data["axis_2d"], points @ data["lateral_2d"]))
    x_min = min(span[0] for span in data["wall_spans"]) - 1.0
    x_max = max(span[1] for span in data["wall_spans"]) + 1.0
    y_min = min(data["wall_offsets"]) - 1.0
    y_max = max(data["wall_offsets"]) + 1.0
    width, height = 1200, 760
    left, right, top, bottom = 100, 30, 85, 90
    plot_w, plot_h = width - left - right, height - top - bottom

    def sx(x: float) -> float:
        return left + (x - x_min) / (x_max - x_min) * plot_w

    def sy(y: float) -> float:
        return top + (y_max - y) / (y_max - y_min) * plot_h

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="100" y="42" font-family="sans-serif" font-size="23" font-weight="bold">Recording 001: LiDAR corridor candidates (preliminary)</text>',
    ]
    x_tick = np.floor(x_min / 5) * 5
    while x_tick <= x_max:
        x = sx(float(x_tick))
        elements.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" stroke="#dddddd"/>')
        elements.append(f'<text x="{x:.1f}" y="{top + plot_h + 25}" text-anchor="middle" font-family="sans-serif" font-size="13">{x_tick:.0f}</text>')
        x_tick += 5
    y_tick = np.floor(y_min / 0.5) * 0.5
    while y_tick <= y_max:
        y = sy(float(y_tick))
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#dddddd"/>')
        elements.append(f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" font-size="13">{y_tick:.1f}</text>')
        y_tick += 0.5
    elements.append(f'<defs><clipPath id="plot"><rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}"/></clipPath></defs>')
    elements.append('<g clip-path="url(#plot)" fill="#356b9a" fill-opacity="0.25">')
    for x, y in xy:
        if x_min <= x <= x_max and y_min <= y <= y_max:
            elements.append(f'<circle cx="{sx(float(x)):.1f}" cy="{sy(float(y)):.1f}" r="1.1"/>')
    elements.append('</g>')
    for index, y_value in enumerate(data["wall_offsets"], start=1):
        yy = sy(y_value)
        elements.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left + plot_w}" y2="{yy:.1f}" stroke="#d14a35" stroke-width="2"/>')
        elements.append(f'<text x="{left + plot_w - 5}" y="{yy - 7:.1f}" text-anchor="end" fill="#a93020" font-family="sans-serif" font-size="14">wall {index}: {y_value:.2f} m</text>')
    x0, y0 = sx(0.0), sy(0.0)
    elements.append(f'<path d="M{x0 - 7:.1f},{y0:.1f} L{x0 + 7:.1f},{y0:.1f} M{x0:.1f},{y0 - 7:.1f} L{x0:.1f},{y0 + 7:.1f}" stroke="#111111" stroke-width="2"/>')
    elements.append(f'<text x="{left + plot_w / 2:.1f}" y="{height - 25}" text-anchor="middle" font-family="sans-serif" font-size="16">Corridor X candidate from LiDAR origin (m)</text>')
    elements.append(f'<text x="25" y="{top + plot_h / 2:.1f}" transform="rotate(-90 25 {top + plot_h / 2:.1f})" text-anchor="middle" font-family="sans-serif" font-size="16">Lateral Y candidate (m)</text>')
    elements.append('</svg>')
    output.write_text("\n".join(elements) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path, help="rosbag2 directory containing metadata.yaml and MCAP")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    points, accelerations, cloud_count, imu_count = read_bag(args.bag)
    geometry = estimate_geometry(points, accelerations)
    geometry["source_bag"] = str(args.bag.resolve())
    geometry["point_cloud_frames"] = cloud_count
    geometry["imu_messages"] = imu_count
    geometry["valid_point_returns"] = int(len(points))
    plot_path = args.output_dir / "lidar_corridor_candidate.svg"
    save_plot(geometry, plot_path)
    json_path = args.output_dir / "lidar_corridor_candidate.json"
    json_path.write_text(json.dumps(geometry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in geometry.items() if k != "notes"}, ensure_ascii=False, indent=2))
    print(f"plot: {plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
