"""Package group 4 timelines and source tools without images or BODY detections."""
import argparse
import csv
import json
from pathlib import Path
import re
import shutil

from depth_person_prototype import digest
from zed_sdk_package.tracking_v2.validate_export import validate_export


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--group4-exchange', type=Path, required=True)
    p.add_argument('--group5-progress', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    a = p.parse_args()
    if a.destination.exists():
        raise FileExistsError('new template destination required')
    project = Path(__file__).resolve().parent
    with (a.group4_exchange/'input_inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        entries = {r['recording']: r for r in csv.DictReader(f)}
    bodies = sorted(a.group4_exchange.glob('recording_*/body'))
    if not bodies or len(bodies) != len(entries):
        raise ValueError('group 4 exports and inventory do not match')
    progress = json.loads(a.group5_progress.read_text(encoding='utf-8-sig'))
    ids = sorted({r['recording_id'] for attempts in progress['attempts'].values() for r in attempts
                  if r.get('status') == 'complete' and re.fullmatch(r'recording_\d{3}', r.get('recording_id', ''))})
    if not ids:
        raise ValueError('no completed group 5 recordings in progress')
    files = ['depth_person_prototype.py', 'corridor_tracking/data.py', 'corridor_tracking/assignment.py',
             'corridor_tracking/depth_alignment.py', 'corridor_tracking/depth_person_comparison.py',
             'corridor_tracking/merge_depth_person_runs.py', 'corridor_tracking/depth_tracking.py',
             'corridor_tracking/depth_corridor_replay.py', 'corridor_tracking/portable_depth_replay.py',
             'corridor_tracking/compact_completed_run.py', 'corridor_tracking/compact_batch.py',
             'corridor_tracking/depth_progress.py', 'corridor_tracking/local_depth_pipeline.py',
             'corridor_tracking/build_group004_pilot_bundle.py', 'corridor_tracking/prepare_group004_005_bundle.py',
             'corridor_tracking/group004_005_batch.py', 'corridor_tracking/verify_portable_bundle.py',
             'run_group004_005.ps1',
             'models/yolov8n-seg.pt']
    sdk = project/'zed_sdk_package/tracking_v2'
    files += [str(f.relative_to(project)) for f in sdk.iterdir() if f.is_file() and f.suffix in ('.py', '.ps1', '.md', '.csv')]
    a.destination.mkdir(parents=True, exist_ok=False)
    for name in files:
        target = a.destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        source = project/'corridor_tracking/run_group004_005.ps1' if name == 'run_group004_005.ps1' else project/name
        shutil.copyfile(source, target)
        if digest(target) != digest(source):
            raise OSError(f'copy mismatch: {name}')
    rows = []
    for index, body in enumerate(bodies, 1):
        rec = body.parent.name
        if rec not in entries:
            raise ValueError(f'missing inventory row: {rec}')
        validate_export(body)
        source = json.loads((body/'manifest.json').read_text(encoding='utf-8-sig'))
        camera = json.loads((body/'camera.json').read_text(encoding='utf-8-sig'))
        with (body/'frames.csv').open(newline='', encoding='utf-8-sig') as f:
            frames = [{k: row[k] for k in ('frame_index', 'svo_frame_index', 'image_timestamp_ns')} for row in csv.DictReader(f)]
        if len(frames) != source['saved_frames'] or camera['setup_id'] != entries[rec]['setup_id']:
            raise ValueError(f'group 4 timeline mismatch: {rec}')
        body_hash = digest(body/'manifest.json')
        name = f'timelines/g004_{rec}.json'
        target = a.destination/name
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps({'body_manifest_sha256': body_hash, 'camera': camera, 'frames': frames},
                                     ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
        rows.append({'group': '4', 'recording': rec, 'svo_path': entries[rec]['svo_path'], 'setup_id': camera['setup_id'],
                     'source_svo_sha256': camera['source_svo_sha256'], 'frame_count': str(len(frames)),
                     'body_manifest_sha256': body_hash, 'timeline': name})
        print(f'validated group4 timeline {index}/{len(bodies)}: {rec}', flush=True)
    (a.destination/'group4_inventory.json').write_text(json.dumps(rows, indent=2)+'\n', encoding='utf-8')
    (a.destination/'group5_recordings.json').write_text(json.dumps(ids, indent=2)+'\n', encoding='utf-8')
    hashes = {f.relative_to(a.destination).as_posix(): digest(f) for f in a.destination.rglob('*') if f.is_file()}
    (a.destination/'template_manifest.json').write_text(json.dumps({'status': 'prepared_not_windows_validated', 'files_sha256': hashes}, indent=2)+'\n', encoding='utf-8')
    print(f'template prepared: group4={len(rows)}, group5={len(ids)}; {a.destination}', flush=True)


if __name__ == '__main__':
    main()
