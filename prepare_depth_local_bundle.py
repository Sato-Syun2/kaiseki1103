"""Package a local-only SDK and coordinate-analysis workflow for Windows."""
import argparse
import csv
import json
from pathlib import Path
import shutil

from depth_person_prototype import digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    a = p.parse_args()
    if a.destination.exists():
        raise FileExistsError('bundle already exists')
    project = Path(__file__).resolve().parent
    files = ['depth_person_prototype.py', 'corridor_tracking/data.py', 'corridor_tracking/assignment.py',
             'corridor_tracking/depth_alignment.py', 'corridor_tracking/depth_person_comparison.py',
             'corridor_tracking/merge_depth_person_runs.py', 'corridor_tracking/depth_tracking.py',
             'corridor_tracking/depth_corridor_replay.py', 'corridor_tracking/portable_depth_replay.py',
             'corridor_tracking/migrate_depth_results.py', 'corridor_tracking/compact_depth_results.py', 'corridor_tracking/compact_completed_run.py', 'corridor_tracking/recompute_compact_depth.py', 'corridor_tracking/verify_portable_bundle.py', 'corridor_tracking/depth_progress.py',
             'corridor_tracking/local_depth_pipeline.py', 'corridor_tracking/compact_batch.py', 'corridor_tracking/benchmark_depth_pipeline.py', 'corridor_tracking/benchmark_storage_pipeline.py', 'corridor_tracking/run_depth_local.ps1',
             'corridor_tracking/bootstrap_local_depth.ps1', 'corridor_tracking/bootstrap_compact_batch.ps1', 'models/yolov8n-seg.pt']
    sdk = project/'zed_sdk_package/tracking_v2'
    files += [str(f.relative_to(project)) for f in sdk.iterdir() if f.is_file() and f.suffix in ('.py', '.ps1', '.md', '.csv')]
    with a.inventory.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 109 or len({(r['group'], r['recording']) for r in rows}) != len(rows):
        raise ValueError('expected 109 unique group 2/3 recordings')
    a.destination.mkdir(parents=True, exist_ok=False)
    for name in files:
        dest = a.destination/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project/name, dest)
        if digest(project/name) != digest(dest):
            raise OSError(f'copy mismatch: {name}')
    portable = []
    for row in rows:
        body, cal = Path(row['body_dir']), Path(row['calibration'])
        if digest(body/'manifest.json') != row['body_manifest_sha256'] or digest(cal) != row['calibration_sha256']:
            raise ValueError(f'BODY or calibration changed: {row["recording"]}')
        body_manifest = json.loads((body/'manifest.json').read_text(encoding='utf-8-sig'))
        for name in ('camera.json', 'frames.csv'):
            if digest(body/name) != body_manifest['file_hashes'][name]:
                raise ValueError(f'BODY file changed: {row["recording"]}/{name}')
        camera = json.loads((body/'camera.json').read_text(encoding='utf-8-sig'))
        with (body/'frames.csv').open(newline='', encoding='utf-8-sig') as f:
            frames = [{k: x[k] for k in ('frame_index', 'svo_frame_index', 'image_timestamp_ns')} for x in csv.DictReader(f)]
        if len(frames) != int(row['frame_count']) or camera['source_svo_sha256'] != row['source_svo_sha256']:
            raise ValueError('BODY timeline mismatch')
        key = f'g{int(row["group"]):03d}_{row["recording"]}'
        cal_name, time_name = f'calibrations/{key}.json', f'timelines/{key}.json'
        (a.destination/'calibrations').mkdir(exist_ok=True)
        (a.destination/'timelines').mkdir(exist_ok=True)
        shutil.copyfile(cal, a.destination/cal_name)
        timeline = {'body_manifest_sha256': row['body_manifest_sha256'], 'camera': camera, 'frames': frames}
        (a.destination/time_name).write_text(json.dumps(timeline, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
        portable.append({k: row[k] for k in ('group', 'recording', 'svo_path', 'setup_id', 'source_svo_sha256',
                         'frame_count', 'body_manifest_sha256', 'calibration_sha256', 'existing_depth')}
                        | {'calibration': cal_name, 'timeline': time_name})
    with (a.destination/'inventory.csv').open('x', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(portable[0])); w.writeheader(); w.writerows(portable)
    hashes = {f.relative_to(a.destination).as_posix(): digest(f) for f in a.destination.rglob('*') if f.is_file()}
    manifest = {'status': 'prepared_not_windows_validated', 'recording_count': len(portable),
                'source_inventory_sha256': digest(a.inventory), 'files_sha256': hashes,
                'output_policy': 'local depth and images; share only positions.json and manifest.json'}
    (a.destination/'bundle_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'{len(portable)} recordings packaged at {a.destination}')


if __name__ == '__main__':
    main()
