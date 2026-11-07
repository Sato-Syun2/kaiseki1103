#!/usr/bin/env python3
"""Experimental per-frame RGB/depth person surface estimates; no skeleton input."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import importlib.metadata
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np

from corridor_tracking.data import transform


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_asset(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'missing or unsafe input asset: {relative}')
    return path


def load_depth_export(root):
    root = Path(root).resolve()
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest.get('status') != 'complete':
        raise ValueError('depth export is not complete')
    hashes = manifest.get('files_sha256')
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('depth export has no file hashes')
    for name in ('camera.json', 'frames.csv', 'zed_depth_points.npz'):
        if name not in hashes:
            raise ValueError(f'depth manifest omits {name}')
    for name, expected in hashes.items():
        if digest(safe_asset(root, name)) != expected:
            raise ValueError(f'depth asset hash mismatch: {name}')
    camera = json.loads((root / 'camera.json').read_text(encoding='utf-8-sig'))
    source_hash = camera.get('source_svo_sha256')
    if not isinstance(source_hash, str) or len(source_hash) != 64 or any(c not in '0123456789abcdef' for c in source_hash.lower()):
        raise ValueError('depth camera has no valid source SVO hash')
    if not camera.get('setup_id') or source_hash != manifest.get('source_svo_sha256') or camera.get('setup_id') != manifest.get('setup_id'):
        raise ValueError('camera and manifest source/setup do not match')
    if not str(camera.get('coordinate_system', '')).startswith('IMAGE') or camera.get('coordinate_units') != 'meter':
        raise ValueError('expected IMAGE coordinates in metres')
    intr = camera['intrinsics_left']
    if not all(math.isfinite(float(intr[k])) for k in ('fx', 'fy', 'cx', 'cy')) or intr['fx'] <= 0 or intr['fy'] <= 0:
        raise ValueError('invalid camera intrinsics')
    with (root / 'frames.csv').open(newline='', encoding='utf-8-sig') as f:
        frames = list(csv.DictReader(f))
    if len(frames) != manifest.get('sample_count') or not frames:
        raise ValueError('depth frame count mismatch')
    sample_ids = [int(f['sample_index']) for f in frames]
    indices = [int(f['frame_index']) for f in frames]
    timestamps = [int(f['image_timestamp_ns']) for f in frames]
    if sample_ids != list(range(len(frames))) or any(int(f['svo_frame_index']) != int(f['frame_index']) for f in frames) or any(b <= a for a, b in zip(indices, indices[1:])) or any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        raise ValueError('depth frames are duplicated or not ordered')
    for frame in frames:
        name = frame['image_file']
        if name not in hashes or frame['image_sha256'] != hashes[name]:
            raise ValueError('frame image hash not covered by manifest')
        safe_asset(root, name)
        if int(frame['image_width']) != int(camera['width']) or int(frame['image_height']) != int(camera['height']):
            raise ValueError('frame image dimensions differ from camera')
    with np.load(root / 'zed_depth_points.npz', allow_pickle=False) as z:
        points = z['points_camera_image_m']
        ids = z['point_frame_index']
        if not np.array_equal(z['frame_indices'], sample_ids) or not np.array_equal(z['frame_timestamps_ns'], timestamps):
            raise ValueError('depth point archive and frame timeline differ')
    if points.ndim != 2 or points.shape[1] != 3 or ids.ndim != 1 or len(ids) != len(points) or not np.issubdtype(ids.dtype, np.integer):
        raise ValueError('invalid depth point arrays')
    if len(ids) and (ids.min() < 0 or ids.max() >= len(frames)):
        raise ValueError('point sample index outside timeline')
    if any(int((ids == i).sum()) != int(f['valid_depth_points']) for i, f in enumerate(frames)):
        raise ValueError('point count differs from frame inventory')
    return root, camera, frames, points, ids, digest(manifest_path)


def calibration_for_camera(path, camera):
    if path is None:
        return None
    cal = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not cal.get('applies_to') or cal.get('setup_id') != camera.get('setup_id'):
        raise ValueError('calibration setup/scope does not match depth camera')
    for key, expected in cal['applies_to'].items():
        if expected is None:
            continue
        actual = camera.get(key)
        if key == 'coordinate_system' and str(expected).startswith('IMAGE') and str(actual).startswith('IMAGE'):
            continue
        if actual != expected:
            raise ValueError(f'calibration mismatch: {key}')
    transform([0., 0., 1.], cal)
    return cal


def mask_from_region(region, width, height):
    mask = np.zeros((height, width), np.uint8)
    if 'bbox_xyxy' in region and 'polygon_xy' not in region:
        box = region['bbox_xyxy']
        if len(box) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in box):
            raise ValueError('invalid box')
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError('box outside image')
        mask[math.floor(y0):math.ceil(y1), math.floor(x0):math.ceil(x1)] = 1
    elif 'polygon_xy' in region and 'bbox_xyxy' not in region:
        poly = np.asarray(region['polygon_xy'], dtype=float)
        if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3 or not np.isfinite(poly).all():
            raise ValueError('invalid polygon')
        if np.any(poly[:, 0] < 0) or np.any(poly[:, 0] >= width) or np.any(poly[:, 1] < 0) or np.any(poly[:, 1] >= height):
            raise ValueError('polygon outside image')
        cv2.fillPoly(mask, [np.rint(poly).astype(np.int32)], 1)
    else:
        raise ValueError('region must have exactly one of bbox_xyxy or polygon_xy')
    return mask


def estimate_surface(xyz, *, min_points=20, window_m=0.8, ambiguity_ratio=0.5):
    """Find the densest depth band; abstain if a disjoint band also has support."""
    xyz = np.asarray(xyz)
    valid = np.isfinite(xyz).all(axis=1) & (xyz[:, 2] > 0)
    valid_indices = np.flatnonzero(valid)
    selected = np.zeros(len(xyz), dtype=bool)
    if len(valid_indices) < min_points:
        return selected, {'status': 'insufficient_depth', 'valid_points': int(len(valid_indices)), 'depth_modes': []}
    order = valid_indices[np.argsort(xyz[valid_indices, 2])]
    def densest(indices):
        if not len(indices):
            return indices
        depths = xyz[indices, 2]
        ends = np.searchsorted(depths, depths + window_m, side='right')
        start = int(np.argmax(ends - np.arange(len(indices))))
        return indices[start:ends[start]]
    main = densest(order)
    if len(main) < min_points:
        return selected, {'status': 'insufficient_cluster', 'valid_points': int(len(valid_indices)), 'depth_modes': []}
    other = densest(order[~np.isin(order, main)])
    bands = [main] + ([other] if len(other) else [])
    desc = [{'count': int(len(c)), 'z_min_m': float(xyz[c, 2].min()), 'z_max_m': float(xyz[c, 2].max())} for c in bands]
    if len(other) >= min_points and len(other) >= ambiguity_ratio * len(main):
        return selected, {'status': 'ambiguous_depth_modes', 'valid_points': int(len(valid_indices)), 'depth_modes': desc}
    selected[main] = True
    chosen = xyz[main]
    return selected, {'status': 'surface_candidate', 'valid_points': int(len(valid_indices)), 'depth_modes': desc,
                      'selected_points': int(len(main)), 'surface_camera_image_m': np.median(chosen, axis=0).astype(float).tolist(),
                      'depth_p10_p50_p90_m': np.percentile(chosen[:, 2], [10, 50, 90]).astype(float).tolist()}


def project(points, camera):
    good = np.isfinite(points).all(axis=1) & (points[:, 2] > 0)
    p = points[good]
    intr = camera['intrinsics_left']
    u = np.rint(intr['fx'] * p[:, 0] / p[:, 2] + intr['cx']).astype(np.int64)
    v = np.rint(intr['fy'] * p[:, 1] / p[:, 2] + intr['cy']).astype(np.int64)
    inside = (u >= 0) & (u < camera['width']) & (v >= 0) & (v < camera['height'])
    return p[inside], u[inside], v[inside]


def manual_regions(path, camera, frames):
    annotation = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if annotation.get('source_svo_sha256') != camera.get('source_svo_sha256'):
        raise ValueError('manual regions do not match source SVO hash')
    by_frame = {}
    valid = {int(f['frame_index']): f for f in frames}
    for item in annotation['frames']:
        idx = int(item['frame_index'])
        if idx not in valid or idx in by_frame or item.get('image_sha256') != valid[idx]['image_sha256']:
            raise ValueError('manual region frame is absent, duplicated, or image hash differs')
        people = []
        labels = set()
        for region in item['regions']:
            label = str(region['label'])
            if not label or label in labels:
                raise ValueError('manual labels must be unique per frame')
            labels.add(label)
            mask = mask_from_region(region, camera['width'], camera['height'])
            people.append({'label': label, 'mask': mask, 'confidence': None})
        by_frame[idx] = people
    if set(by_frame) != set(valid):
        raise ValueError('manual regions must cover every exported frame, with empty regions if none')
    return by_frame, annotation.get('description', '')


def model_regions(model, image, mode, confidence, imgsz):
    result = model.predict(image, device='cpu', imgsz=imgsz, conf=confidence, classes=[0], verbose=False, retina_masks=True)[0]
    people = []
    if mode == 'mask' and len(result.boxes) and (result.masks is None or len(result.masks.data) != len(result.boxes)):
        raise ValueError('segmentation model did not return one mask per detection')
    for i, box in enumerate(result.boxes):
        if mode == 'box':
            xy = box.xyxy[0].cpu().numpy().astype(float).tolist()
            xy = [max(0., xy[0]), max(0., xy[1]), min(float(image.shape[1]), xy[2]), min(float(image.shape[0]), xy[3])]
            mask = mask_from_region({'bbox_xyxy': xy}, image.shape[1], image.shape[0])
        else:
            mask = result.masks.data[i].cpu().numpy().astype(np.uint8)
            if mask.shape != image.shape[:2]:
                raise ValueError('segmentation mask is not in original image coordinates')
        people.append({'label': f'detection_{i+1}', 'mask': mask, 'confidence': float(box.conf[0])})
    return people


def run(args):
    script_hash = digest(Path(__file__))
    transform_hash = digest(Path(__file__).resolve().parent / 'corridor_tracking' / 'data.py')
    if args.min_points < 1 or not math.isfinite(args.window_m) or args.window_m <= 0 or not math.isfinite(args.ambiguity_ratio) or not 0 < args.ambiguity_ratio <= 1 or args.erode_px < 0:
        raise ValueError('invalid depth selection thresholds')
    if not math.isfinite(args.confidence) or not 0 < args.confidence <= 1 or args.imgsz <= 0:
        raise ValueError('invalid detector settings')
    if args.output.exists():
        raise FileExistsError(f'output already exists: {args.output}')
    if args.method == 'manual' and args.regions is None:
        raise ValueError('--regions required for manual method')
    if args.method != 'manual' and args.model is None:
        raise ValueError('--model required for detector methods; supply a local model file')
    root, camera, frames, points, ids, manifest_hash = load_depth_export(args.depth)
    cal = calibration_for_camera(args.calibration, camera)
    by_frame, annotation_description, model = None, None, None
    meta = {'method': args.method, 'depth_manifest_sha256': manifest_hash, 'source_svo_sha256': camera['source_svo_sha256'],
            'setup_id': camera['setup_id'], 'calibration_sha256': digest(args.calibration) if args.calibration else None,
            'selection': {'min_points': args.min_points, 'depth_window_m': args.window_m, 'ambiguity_ratio': args.ambiguity_ratio, 'erode_px': args.erode_px},
            'limits': ['surface estimate is not pelvis, floor contact, or measured person centre',
                       'cluster and mask thresholds are unvalidated; a dominant cluster can still be background',
                       'per-frame candidates are not person tracks; no skeleton input or matching used']}
    if args.method == 'manual':
        by_frame, annotation_description = manual_regions(args.regions, camera, frames)
        meta.update(regions_sha256=digest(args.regions), regions_description=annotation_description)
    else:
        if not args.model.is_file():
            raise ValueError('model must be an existing local file; automatic downloads are disabled')
        from ultralytics import YOLO
        model = YOLO(str(args.model))
        if args.method == 'mask' and model.task != 'segment':
            raise ValueError('mask method requires an instance-segmentation model')
        meta.update(model_sha256=digest(args.model), model_path=str(args.model.resolve()), model_task=model.task,
                    ultralytics_version=importlib.metadata.version('ultralytics'), confidence=args.confidence, imgsz=args.imgsz, device='cpu')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'images').mkdir()
    (args.output / 'masks').mkdir()
    results = []
    started = time.monotonic()
    for frame in frames:
        index = int(frame['frame_index'])
        image = cv2.imread(str(root / frame['image_file']))
        if image is None or image.shape[:2] != (camera['height'], camera['width']):
            raise ValueError(f'cannot read expected image at frame {index}')
        people = by_frame[index] if by_frame is not None else model_regions(model, image, args.method, args.confidence, args.imgsz)
        p, u, v = project(points[ids == int(frame['sample_index'])], camera)
        if args.erode_px:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*args.erode_px+1, 2*args.erode_px+1))
            for person in people:
                person['mask'] = cv2.erode(person['mask'], kernel)
        membership = np.zeros(len(p), dtype=np.uint16)
        for person in people:
            membership += person['mask'][v, u].astype(np.uint16)
        overlay = image.copy()
        rows = []
        colours = [(0, 220, 255), (255, 180, 0), (100, 255, 100), (255, 90, 255)]
        for i, person in enumerate(people):
            mask = person['mask']; colour = colours[i % len(colours)]
            mask_name = f'masks/frame_{index:08d}_region_{i+1:03d}.png'
            if not cv2.imwrite(str(args.output / mask_name), mask * 255):
                raise OSError('could not write region mask')
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(overlay, contours, -1, colour, 2)
            inside = mask[v, u] != 0
            overlap = inside & (membership > 1)
            eligible = inside & (membership == 1)
            coords = np.flatnonzero(eligible)
            chosen, info = estimate_surface(p[eligible], min_points=args.min_points, window_m=args.window_m, ambiguity_ratio=args.ambiguity_ratio)
            chosen_idx = coords[chosen]
            rejected_idx = np.flatnonzero(inside & (~eligible)) if info['status'] == 'surface_candidate' else np.flatnonzero(inside)
            if info['status'] == 'surface_candidate':
                rejected_idx = np.concatenate((coords[~chosen], rejected_idx))
            # Review pixels are deliberately sparse; counts are computed from all points.
            for j in rejected_idx[::max(1, len(rejected_idx)//1200)]:
                cv2.circle(overlay, (int(u[j]), int(v[j])), 1, (0, 0, 255), -1)
            for j in chosen_idx[::max(1, len(chosen_idx)//1200)]:
                cv2.circle(overlay, (int(u[j]), int(v[j])), 1, colour, -1)
            xyz = info.get('surface_camera_image_m')
            if xyz:
                cu = round(camera['intrinsics_left']['fx']*xyz[0]/xyz[2]+camera['intrinsics_left']['cx'])
                cv = round(camera['intrinsics_left']['fy']*xyz[1]/xyz[2]+camera['intrinsics_left']['cy'])
                cv2.drawMarker(overlay, (cu, cv), colour, cv2.MARKER_CROSS, 18, 2)
                if cal is not None:
                    info['surface_corridor_m'] = transform(xyz, cal)
            nonzero = cv2.findNonZero(mask)
            if nonzero is not None:
                x, y, w, h = cv2.boundingRect(nonzero)
                cv2.putText(overlay, f'{person["label"]}: {info["status"]}', (x, max(15, y-5)), cv2.FONT_HERSHEY_SIMPLEX, .45, colour, 1, cv2.LINE_AA)
                bounds = [x, y, x+w, y+h]
            else:
                bounds = None
            rows.append({'label': person['label'], 'detector_confidence': person['confidence'], 'region_bbox_xyxy': bounds,
                         'region_mask': mask_name, 'region_mask_sha256': digest(args.output / mask_name),
                         'region_pixels_after_erosion': int(mask.sum()), 'points_in_region': int(inside.sum()),
                         'overlap_points_excluded': int(overlap.sum()), **info})
        name = f'frame_{index:08d}.jpg'
        if not cv2.imwrite(str(args.output / 'images' / name), overlay):
            raise OSError('could not write review image')
        results.append({'frame_index': index, 'timestamp_ns': frame['image_timestamp_ns'], 'elapsed_s': float(frame['elapsed_s']),
                        'image_sha256': frame['image_sha256'], 'review_image': 'images/'+name, 'people': rows})
        print(f'frame {index}: {len(rows)} regions, {sum(r["status"] == "surface_candidate" for r in rows)} candidates', flush=True)
    meta['processing_seconds'] = round(time.monotonic()-started, 3)
    payload = {'metadata': meta, 'frames': results}
    (args.output/'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    sections = []
    for frame in results:
        lines = html.escape(json.dumps(frame['people'], ensure_ascii=False, indent=2))
        sections.append(f'<section><h2>Frame {frame["frame_index"]} / {frame["elapsed_s"]:.3f} s</h2><img src="{frame["review_image"]}"><pre>{lines}</pre></section>')
    page = '<!doctype html><meta charset="utf-8"><title>人物深度の試作</title><style>body{font:16px sans-serif;margin:24px}img{width:100%;max-width:1920px}pre{white-space:pre-wrap}section{border-top:1px solid #aaa}</style><h1>画像領域と深度から求めた可視表面候補</h1><p>色の枠・点は領域と採用された深度点、赤点は除外点、十字は代表点。表示点は間引き。これは位置や人物IDの正解ではなく、背景の混入を確認する試作です。各フレーム独立、骨格は使用していません。</p><p><a href="results.json">数値・入力条件</a></p>' + ''.join(sections)
    (args.output/'index.html').write_text(page, encoding='utf-8')
    if digest(Path(__file__)) != script_hash or digest(Path(__file__).resolve().parent / 'corridor_tracking' / 'data.py') != transform_hash:
        raise ValueError('analysis code changed during run; output is incomplete')
    output_files = sorted(p for p in args.output.rglob('*') if p.is_file())
    manifest = {'status': 'complete', 'script_sha256': script_hash, 'transform_code_sha256': transform_hash,
                'files_sha256': {str(p.relative_to(args.output)): digest(p) for p in output_files}}
    (args.output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Saved {args.output} ({len(results)} frames)')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--depth', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--method', choices=('manual','mask','box'), required=True)
    p.add_argument('--regions', type=Path, help='manual frame regions JSON')
    p.add_argument('--model', type=Path, help='local Ultralytics model file')
    p.add_argument('--calibration', type=Path)
    p.add_argument('--confidence', type=float, default=.15)
    p.add_argument('--imgsz', type=int, default=1280)
    p.add_argument('--min-points', type=int, default=20)
    p.add_argument('--window-m', type=float, default=.8, help='experimental depth-band width in metres')
    p.add_argument('--ambiguity-ratio', type=float, default=.5, help='reject when a disjoint depth band has this fraction of primary support')
    p.add_argument('--erode-px', type=int, default=1)
    args = p.parse_args()
    run(args)


if __name__ == '__main__':
    main()
