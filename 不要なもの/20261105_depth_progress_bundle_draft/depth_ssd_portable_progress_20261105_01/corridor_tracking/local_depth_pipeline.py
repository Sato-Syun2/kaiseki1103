"""Export and analyze depth locally; publish only person coordinates and provenance."""
import argparse
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from corridor_tracking.depth_alignment import verify_metadata
from corridor_tracking.depth_person_comparison import load_run
from corridor_tracking.depth_progress import DepthProgress
from corridor_tracking.depth_tracking import associate_frames
from corridor_tracking.portable_depth_replay import create_replay
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
    p.add_argument('--batch-completed', type=int, default=0)
    p.add_argument('--batch-total', type=int)
    p.add_argument('--batch-pending-new', type=int)
    p.add_argument('--batch-average-seconds', type=float, default=0.)
    a = p.parse_args()
    if not re.fullmatch(r'recording_\d{3}', a.recording) or not re.fullmatch(r'[A-Za-z0-9_]+', a.run_id) or not 1 <= a.clip_frames <= 90:
        p.error('invalid recording, run ID or clip size')
    if (a.batch_completed < 0 or (a.batch_total is not None and not 0 <= a.batch_completed <= a.batch_total)
            or (a.batch_pending_new is not None and a.batch_pending_new < 1)
            or not 0 <= a.batch_average_seconds < 1e9):
        p.error('invalid batch progress parameters')
    progress = DepthProgress(a.group, a.recording, completed=a.batch_completed, total=a.batch_total,
                             pending_new=a.batch_pending_new, previous_average=a.batch_average_seconds)
    progress.start()
    try:
        return run_pipeline(a, progress)
    finally:
        progress.stop()


def run_pipeline(a, progress):
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
    if os.name == 'nt' and str(a.local_root.resolve()).startswith('\\\\'):
        raise ValueError('raw depth local root must not be a UNC shared path')
    a.local_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(a.local_root).free < count * 8 * 1024**2 + 5 * 1024**3:
        raise OSError('insufficient local disk space for this recording and a 5 GiB reserve')
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
    progress.update(clips_total=len(clips), stage='SVOと設定を確認済み')
    work.mkdir(parents=True, exist_ok=False)
    parts = []
    for clip_index, (start, length, clip_tag) in enumerate(clips, 1):
        progress.update(stage=f'SDK深度書き出し {clip_index}/{len(clips)}（フレーム {start}〜{start+length-1}）')
        subprocess.run([str(a.sdk_python), str(bundle/'zed_sdk_package/tracking_v2/export_depth_clip.py'),
                        '--svo', str(svo), '--setup-id', row['setup_id'], '--tag', clip_tag,
                        '--local-root', str(clip_root), '--local-only', '--first-frame', str(start),
                        '--frame-count', str(length), '--pixel-stride', '2', '--expected-svo-sha256', row['source_svo_sha256']], check=True, cwd=bundle)
        depth = clip_root/clip_tag/'depth'
        progress.update(stage=f'深度と録画時刻を照合 {clip_index}/{len(clips)}')
        _, dc, depth_frames, _, _, dh = load_depth_export(depth)
        report = verify_metadata(dc, body_camera, depth_frames, body_frames, first=start, count=length)
        if dc.get('total_svo_frames_read') != count:
            raise ValueError('depth pass did not read the entire BODY timeline')
        report.update(depth_manifest_sha256=dh, body_manifest_sha256=row['body_manifest_sha256'])
        alignment = work/f'alignment_{start:06d}.json'
        alignment.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        result = work/f'part_{start:06d}'
        progress.update(stage=f'人物検出と深度解析 {clip_index}/{len(clips)}')
        subprocess.run([sys.executable, str(bundle/'depth_person_prototype.py'), '--depth', str(depth),
                        '--method', 'mask', '--model', str(model), '--calibration', str(cal), '--output', str(result)], check=True, cwd=bundle)
        parts.extend(['--part', str(result), str(alignment)])
        progress.update(clips_done=clip_index, stage=f'区間 {clip_index}/{len(clips)} 完了')
    merged = work/'merged'
    progress.update(stage='全区間を結合中')
    subprocess.run([sys.executable, '-m', 'corridor_tracking.merge_depth_person_runs', *parts,
                    '--first-frame', '0', '--frame-count', str(count), '--require-full-svo', '--output', str(merged)], check=True, cwd=bundle)
    data = load_run(merged)
    progress.update(stage='人物IDを追跡中')
    frames = associate_frames(data['frames'])
    metadata = {'group': a.group, 'recording': a.recording, 'source_svo_sha256': row['source_svo_sha256'],
                'setup_id': row['setup_id'], 'calibration_sha256': digest(cal), 'body_manifest_sha256': row['body_manifest_sha256'],
                'bundle_manifest_sha256': digest(bundle/'bundle_manifest.json'), 'model_sha256': digest(model),
                'person_run_manifest_sha256': digest(merged/'manifest.json'),
                'tracking_code_sha256': digest(bundle/'corridor_tracking/depth_tracking.py'),
                'ultralytics_version': importlib.metadata.version('ultralytics'),
                'position_semantics': 'visible depth surface candidate in provisional corridor XYZ metres; not body centre',
                'limits': ['IDs are provisional', 'missing positions not interpolated', 'separate depth SDK passes']}
    progress.update(stage='座標を共有中')
    publish_coordinates(frames, metadata, published, shared)
    progress.update(stage='再生ページを作成中')
    create_replay(a.local_root, bundle, a.group, a.recording, a.run_id)
    print(f'[進捗] G{a.group:03d} {a.recording} の処理が完了しました。', flush=True)
    print(f'Completed {count} frames; raw depth remains local: {clip_root}; coordinates: {shared}', flush=True)


if __name__ == '__main__':
    main()
