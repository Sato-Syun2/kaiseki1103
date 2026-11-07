"""Prepare a hash-verified recording-006 pilot template; no image or body data is copied."""
import argparse
import csv
import json
from pathlib import Path
import shutil

from depth_person_prototype import digest
from zed_sdk_package.tracking_v2.validate_export import validate_export


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--body', required=True, type=Path)
    p.add_argument('--inventory', required=True, type=Path)
    p.add_argument('--destination', required=True, type=Path)
    a = p.parse_args()
    if a.destination.exists():
        raise FileExistsError('template destination already exists')
    validate_export(a.body)
    manifest = json.loads((a.body/'manifest.json').read_text(encoding='utf-8-sig'))
    camera = json.loads((a.body/'camera.json').read_text(encoding='utf-8-sig'))
    with (a.body/'frames.csv').open(newline='', encoding='utf-8-sig') as f:
        frames = [{k: row[k] for k in ('frame_index', 'svo_frame_index', 'image_timestamp_ns')} for row in csv.DictReader(f)]
    with a.inventory.open(newline='', encoding='utf-8-sig') as f:
        entries = [r for r in csv.DictReader(f) if r['recording'] == 'recording_006']
    if len(entries) != 1 or len(frames) != manifest['saved_frames'] or camera['setup_id'] != entries[0]['setup_id']:
        raise ValueError('recording inventory and validated timeline do not match')
    project = Path(__file__).resolve().parent
    files = ['depth_person_prototype.py', 'corridor_tracking/data.py', 'corridor_tracking/assignment.py',
             'corridor_tracking/depth_alignment.py', 'corridor_tracking/depth_person_comparison.py',
             'corridor_tracking/merge_depth_person_runs.py', 'corridor_tracking/depth_tracking.py',
             'corridor_tracking/depth_corridor_replay.py', 'corridor_tracking/portable_depth_replay.py',
             'corridor_tracking/compact_completed_run.py', 'corridor_tracking/depth_progress.py',
             'corridor_tracking/local_depth_pipeline.py', 'models/yolov8n-seg.pt']
    sdk = project/'zed_sdk_package/tracking_v2'
    files += [str(f.relative_to(project)) for f in sdk.iterdir() if f.is_file() and f.suffix in ('.py', '.ps1', '.md', '.csv')]
    a.destination.mkdir(parents=True, exist_ok=False)
    for name in files:
        target = a.destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project/name, target)
        if digest(target) != digest(project/name):
            raise OSError(f'copy mismatch: {name}')
    shutil.copyfile(project/'corridor_tracking/build_group004_pilot_bundle.py', a.destination/'build_group004_pilot_bundle.py')
    body_hash = digest(a.body/'manifest.json')
    timeline = {'body_manifest_sha256': body_hash, 'camera': camera, 'frames': frames}
    (a.destination/'timelines').mkdir()
    (a.destination/'timelines/g004_recording_006.json').write_text(json.dumps(timeline, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    row = {'group': '4', 'recording': 'recording_006', 'svo_path': entries[0]['svo_path'], 'setup_id': camera['setup_id'],
           'source_svo_sha256': camera['source_svo_sha256'], 'frame_count': str(len(frames)),
           'body_manifest_sha256': body_hash, 'timeline': 'timelines/g004_recording_006.json'}
    (a.destination/'pilot_inventory.json').write_text(json.dumps(row, indent=2)+'\n', encoding='utf-8')
    hashes = {f.relative_to(a.destination).as_posix(): digest(f) for f in a.destination.rglob('*') if f.is_file()}
    (a.destination/'template_manifest.json').write_text(json.dumps({'status': 'prepared_not_windows_validated', 'files_sha256': hashes}, indent=2)+'\n', encoding='utf-8')
    print(f'Pilot template created: {a.destination}')


if __name__ == '__main__':
    main()
