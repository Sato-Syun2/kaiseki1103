"""Export and analyze depth locally; publish only person coordinates and provenance."""
import argparse
import csv
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys

from corridor_tracking.depth_alignment import verify_metadata
from corridor_tracking.depth_person_comparison import load_run
from corridor_tracking.depth_tracking import associate_frames
from depth_person_prototype import digest, load_depth_export
from zed_sdk_package.tracking_v2.exchange_copy import copy_batch


def coordinates(frames):
    """Strip image coordinates, masks and all image/depth data from tracking results."""
    output = []
    for frame in frames:
        observations = []
        for o in frame['observations']:
            observations.append({k: o[k] for k in ('track_id', 'association_reason', 'depth_status', 'surface_corridor_m')})
        output.append({k: frame[k] for k in ('frame_index', 'timestamp_ns', 'elapsed_s')} | {'observations': observations})
    return output


def publish_coordinates(frames, metadata, local, shared):
    if local.exists() or shared.exists():
        raise FileExistsError('coordinate output already exists')
    local.mkdir(parents=True, exist_ok=False)
    data = {'metadata': metadata, 'frames': coordinates(frames)}
    (local/'positions.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    manifest = {'status': 'complete', 'positions_sha256': digest(local/'positions.json'),
                'allowed_files': ['positions.json', 'manifest.json'], 'source_svo_sha256': metadata['source_svo_sha256'],
                'recording': metadata['recording'], 'group': metadata['group'], 'frame_count': len(frames)}
    (local/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if {x.name for x in local.iterdir()} != set(manifest['allowed_files']):
        raise ValueError('coordinate-only output contains unexpected files')
    copied, message = copy_batch(local, shared)
    print(message, flush=True)
    if not copied:
        raise OSError('coordinate copy failed; local output is preserved')
    if digest(shared/'positions.json') != manifest['positions_sha256']:
        raise OSError('shared coordinate hash mismatch; local output is preserved')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sdk-python', type=Path, required=True)
    p.add_argument('--local-root', type=Path, required=True)
    p.add_argument('--shared-root', type=Path, required=True)
    p.add_argument('--group', type=int, choices=[2, 3], required=True)
    p.add_argument('--recording', required=True)
    p.add_argument('--run-id', default='20261105_01')
    p.add_argument('--clip-frames', type=int, default=69)
    a = p.parse_args()
    if not re.fullmatch(r'recording_\d{3}', a.recording) or not re.fullmatch(r'[A-Za-z0-9_]+', a.run_id) or not 1 <= a.clip_frames <= 90:
        p.error('invalid recording, run ID or clip size')
    bundle = a.bundle.resolve()
    manifest = json.loads((bundle/'bundle_manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files_sha256'].items():
        path = (bundle/name).resolve()
        if not path.is_relative_to(bundle) or not path.is_file() or digest(path) != expected:
            raise ValueError(f'bundle file is missing or changed: {name}')
    if importlib.metadata.version('ultralytics') != '8.4.89':
        raise ValueError('analysis environment requires ultralytics 8.4.89')
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = [r for r in csv.DictReader(f) if r['group'] == str(a.group) and r['recording'] == a.recording]
    if len(rows) != 1:
        raise ValueError('recording missing or duplicated in inventory')
    row = rows[0]
    if row['existing_depth'] == 'yes':
        raise ValueError('group 3 recording 018 was already processed')
    svo = Path(row['svo_path'])
    if not svo.is_file() or digest(svo) != row['source_svo_sha256']:
        raise ValueError('source SVO missing or hash mismatch')
    timeline = json.loads((bundle/row['timeline']).read_text(encoding='utf-8'))
    body_camera, body_frames = timeline['camera'], timeline['frames']
    cal, model = bundle/row['calibration'], bundle/'models/yolov8n-seg.pt'
    if digest(cal) != row['calibration_sha256'] or timeline['body_manifest_sha256'] != row['body_manifest_sha256']:
        raise ValueError('calibration or BODY timeline provenance mismatch')
    count = int(row['frame_count'])
    if len(body_frames) != count:
        raise ValueError('BODY timeline length mismatch')
    tag = f'g{a.group:03d}_{a.recording}_{a.run_id}'
    work = a.local_root/'analysis'/tag
    published = a.local_root/'coordinates'/tag
    shared = a.shared_root/tag
    clip_root = a.local_root/'depth_clips'
    if work.exists() or published.exists() or shared.exists():
        raise FileExistsError('recording output already exists; do not overwrite')
    clips = []
    for start in range(0, count, a.clip_frames):
        length = min(a.clip_frames, count-start)
        clip_tag = f'{tag}_{start:06d}_{start+length-1:06d}'
        if (clip_root/clip_tag).exists():
            raise FileExistsError(f'local clip exists: {clip_tag}')
        clips.append((start, length, clip_tag))
    work.mkdir(parents=True, exist_ok=False)
    parts = []
    for start, length, clip_tag in clips:
        subprocess.run([str(a.sdk_python), str(bundle/'zed_sdk_package/tracking_v2/export_depth_clip.py'),
                        '--svo', str(svo), '--setup-id', row['setup_id'], '--tag', clip_tag,
                        '--local-root', str(clip_root), '--local-only', '--first-frame', str(start),
                        '--frame-count', str(length), '--pixel-stride', '2', '--expected-svo-sha256', row['source_svo_sha256']], check=True, cwd=bundle)
        depth = clip_root/clip_tag/'depth'
        _, dc, depth_frames, _, _, dh = load_depth_export(depth)
        report = verify_metadata(dc, body_camera, depth_frames, body_frames, first=start, count=length)
        if dc.get('total_svo_frames_read') != count:
            raise ValueError('depth pass did not read the entire BODY timeline')
        report.update(depth_manifest_sha256=dh, body_manifest_sha256=row['body_manifest_sha256'])
        alignment = work/f'alignment_{start:06d}.json'
        alignment.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        result = work/f'part_{start:06d}'
        subprocess.run([sys.executable, str(bundle/'depth_person_prototype.py'), '--depth', str(depth),
                        '--method', 'mask', '--model', str(model), '--calibration', str(cal), '--output', str(result)], check=True, cwd=bundle)
        parts.extend(['--part', str(result), str(alignment)])
    merged = work/'merged'
    subprocess.run([sys.executable, '-m', 'corridor_tracking.merge_depth_person_runs', *parts,
                    '--first-frame', '0', '--frame-count', str(count), '--require-full-svo', '--output', str(merged)], check=True, cwd=bundle)
    data = load_run(merged)
    frames = associate_frames(data['frames'])
    metadata = {'group': a.group, 'recording': a.recording, 'source_svo_sha256': row['source_svo_sha256'],
                'setup_id': row['setup_id'], 'calibration_sha256': digest(cal), 'body_manifest_sha256': row['body_manifest_sha256'],
                'bundle_manifest_sha256': digest(bundle/'bundle_manifest.json'), 'model_sha256': digest(model),
                'person_run_manifest_sha256': digest(merged/'manifest.json'),
                'tracking_code_sha256': digest(bundle/'corridor_tracking/depth_tracking.py'),
                'ultralytics_version': importlib.metadata.version('ultralytics'),
                'position_semantics': 'visible depth surface candidate in provisional corridor XYZ metres; not body centre',
                'limits': ['IDs are provisional', 'missing positions not interpolated', 'separate depth SDK passes']}
    publish_coordinates(frames, metadata, published, shared)
    print(f'Completed {count} frames; raw depth remains local: {clip_root}; coordinates: {shared}', flush=True)


if __name__ == '__main__':
    main()
