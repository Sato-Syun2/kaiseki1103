"""Validate, analyze, join and render one completed recording from the depth inventory."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from depth_person_prototype import digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--group', type=int, choices=[2, 3], required=True)
    p.add_argument('--recording', required=True)
    p.add_argument('--exchange-root', type=Path, required=True)
    p.add_argument('--output-root', type=Path, required=True)
    p.add_argument('--depth-python', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--run-id', default='20261105_01')
    p.add_argument('--clip-frames', type=int, default=69)
    a = p.parse_args()
    if not re.fullmatch(r'recording_\d{3}', a.recording) or not re.fullmatch(r'[A-Za-z0-9_]+', a.run_id) or not 1 <= a.clip_frames <= 90:
        p.error('invalid recording, run ID or clip size')
    with a.inventory.open(newline='', encoding='utf-8-sig') as f:
        rows = [r for r in csv.DictReader(f) if r['group'] == str(a.group) and r['recording'] == a.recording]
    if len(rows) != 1:
        raise ValueError('recording missing or duplicated in inventory')
    row = rows[0]
    if row['existing_depth'] == 'yes':
        raise ValueError('use the already completed group 3 recording 018 replay')
    body, cal = Path(row['body_dir']), Path(row['calibration'])
    if digest(body/'manifest.json') != row['body_manifest_sha256'] or digest(cal) != row['calibration_sha256']:
        raise ValueError('BODY or calibration changed since inventory preparation')
    count = int(row['frame_count']); clips = []
    for start in range(0, count, a.clip_frames):
        length = min(a.clip_frames, count-start); last = start+length-1
        tag = f'g{a.group:03d}_{a.recording}_depth_{start:06d}_{last:06d}_{a.run_id}'
        folder = a.exchange_root / tag
        summary = json.loads((folder/'batch_summary.json').read_text(encoding='utf-8-sig'))
        if (summary.get('status') != 'validated' or summary.get('source_svo_sha256') != row['source_svo_sha256']
                or summary.get('setup_id') != row['setup_id'] or summary.get('first_frame') != start
                or summary.get('frame_count') != length):
            raise ValueError(f'clip summary disagrees: {tag}')
        clips.append((start, length, folder/'depth'))
    target = a.output_root / f'g{a.group:03d}_{a.recording}'
    if target.exists():
        raise FileExistsError('output exists; use a new output root for a retry')
    target.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy(); env.setdefault('YOLO_CONFIG_DIR', '/tmp/kaiseki_yolo_config')
    parts = []
    for start, length, depth in clips:
        alignment = target/f'alignment_{start:06d}.json'
        result = target/f'part_{start:06d}'
        subprocess.run([sys.executable, '-m', 'corridor_tracking.depth_alignment', '--depth', str(depth),
                        '--body', str(body), '--first-frame', str(start), '--frame-count', str(length),
                        '--output', str(alignment)], check=True)
        subprocess.run([str(a.depth_python), 'depth_person_prototype.py', '--depth', str(depth), '--method', 'mask',
                        '--model', str(a.model), '--calibration', str(cal), '--output', str(result)], check=True, env=env)
        parts.extend(['--part', str(result), str(alignment)])
    merged, tracking, replay = target/'merged', target/'tracking', target/'replay'
    subprocess.run([sys.executable, '-m', 'corridor_tracking.merge_depth_person_runs', *parts, '--first-frame', '0',
                    '--frame-count', str(count), '--require-full-svo', '--output', str(merged)], check=True)
    subprocess.run([sys.executable, '-m', 'corridor_tracking.depth_tracking', '--input', str(merged), '--output', str(tracking)], check=True)
    subprocess.run([sys.executable, '-m', 'corridor_tracking.depth_corridor_replay', '--tracking', str(tracking),
                    '--person-run', str(merged), '--calibration', str(cal),
                    '--title', f'グループ{a.group} {a.recording}', '--output', str(replay)], check=True)
    print(f'Completed {count} frames: {replay / "index.html"}')


if __name__ == '__main__':
    main()
