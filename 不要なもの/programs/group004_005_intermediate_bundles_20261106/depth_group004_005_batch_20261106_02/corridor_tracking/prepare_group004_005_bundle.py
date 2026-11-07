"""Build a local, compact group 4/5 bundle with verified recording timelines."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import time

from corridor_tracking.depth_progress import duration

from corridor_tracking.build_group004_pilot_bundle import digest, validate_calibration


def validate_timeline(data, svo, setup_id, *, verify_source=True):
    camera, frames = data['camera'], data['frames']
    if data.get('status') != 'complete' or data.get('kind') != 'svo_sdk_timeline_no_body':
        raise ValueError('timeline is incomplete or has wrong kind')
    if camera['setup_id'] != setup_id or not svo.is_file():
        raise ValueError('timeline setup or source path differs')
    if verify_source and camera['source_svo_sha256'] != digest(svo):
        raise ValueError('timeline SVO hash differs')
    indices = [int(f['frame_index']) for f in frames]
    stamps = [int(f['image_timestamp_ns']) for f in frames]
    if not frames or indices != list(range(len(frames))) or any(int(f['svo_frame_index']) != i for f, i in zip(frames, indices)) or any(t <= 0 for t in stamps) or any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise ValueError('invalid timeline frames')
    return camera, frames


def verify_template(template):
    m = json.loads((template/'template_manifest.json').read_text(encoding='utf-8'))
    for name, expected in m['files_sha256'].items():
        path = (template/name).resolve()
        if not path.is_relative_to(template) or not path.is_file() or digest(path) != expected:
            raise ValueError(f'template verification failed: {name}')
    return m


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('template', 'output', 'calibration', 'calibration-export', 'group5-root', 'timeline-cache', 'sdk-python'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    template, output = a.template.resolve(), a.output.resolve()
    manifest = verify_template(template)
    if output.exists():
        raise FileExistsError('batch bundle exists; use the existing validated bundle or choose a new path')
    cal = json.loads(a.calibration.read_text(encoding='utf-8-sig'))
    summary = json.loads((a.calibration_export/'batch_summary.json').read_text(encoding='utf-8-sig'))
    cal_camera = json.loads((a.calibration_export/'depth/camera.json').read_text(encoding='utf-8-sig'))
    group4 = json.loads((template/'group4_inventory.json').read_text(encoding='utf-8'))
    expected5 = json.loads((template/'group5_recordings.json').read_text(encoding='utf-8'))
    if not group4 or not expected5 or len(expected5) != len(set(expected5)):
        raise ValueError('empty or duplicate recording inventory')
    for row in group4:
        t = json.loads((template/row['timeline']).read_text(encoding='utf-8'))
        validate_calibration(cal, summary, cal_camera, t['camera'], a.calibration_export)
        if not Path(row['svo_path']).is_file():
            raise FileNotFoundError(f'group 4 SVO missing: {row["svo_path"]}')
    discovered = {}
    for rec in expected5:
        folder = a.group5_root/rec
        matches = sorted(p for p in folder.glob('*') if p.is_file() and p.suffix.lower() in ('.svo', '.svo2'))
        if len(matches) != 1:
            raise ValueError(f'expected one SVO in {folder}, found {len(matches)}')
        discovered[rec] = matches[0]
    a.timeline_cache.mkdir(parents=True, exist_ok=True)
    group5 = []
    started = time.monotonic()
    for i, rec in enumerate(expected5, 1):
        svo, path = discovered[rec], a.timeline_cache/(rec+'.json')
        eta = duration((time.monotonic()-started)/(i-1)*(len(expected5)-i+1)) if i > 1 else '算定中'
        print(f'[時刻準備] グループ5 完了 {i-1}/{len(expected5)}; {rec}; 残り約 {eta}（目安）', flush=True)
        if not path.exists():
            subprocess.run([str(a.sdk_python), str(template/'zed_sdk_package/tracking_v2/export_svo_timeline.py'),
                            '--svo', str(svo), '--setup-id', cal['setup_id'], '--output', str(path)], check=True)
        timeline = json.loads(path.read_text(encoding='utf-8-sig'))
        camera, frames = validate_timeline(timeline, svo, cal['setup_id'])
        validate_calibration(cal, summary, cal_camera, camera, a.calibration_export)
        group5.append({'group': '5', 'recording': rec, 'svo_path': str(svo.resolve()), 'setup_id': cal['setup_id'],
                       'source_svo_sha256': camera['source_svo_sha256'], 'frame_count': str(len(frames)),
                       'body_manifest_sha256': '', 'timeline_sha256': digest(path), 'timeline': 'timelines/g005_'+rec+'.json'})
    output.mkdir(parents=True, exist_ok=False)
    for name, expected in manifest['files_sha256'].items():
        if name in ('group4_inventory.json', 'group5_recordings.json'):
            continue
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template/name, target)
        if digest(target) != expected:
            raise OSError(f'copy mismatch: {name}')
    for row in group5:
        target = output/row['timeline']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a.timeline_cache/(row['recording']+'.json'), target)
        if digest(target) != row['timeline_sha256']:
            raise OSError('copied timeline differs')
    (output/'calibrations').mkdir()
    shutil.copyfile(a.calibration, output/'calibrations/group004_candidate.json')
    cal_hash = digest(a.calibration)
    if digest(output/'calibrations/group004_candidate.json') != cal_hash:
        raise OSError('copied calibration differs')
    rows = group4 + group5
    for row in rows:
        row.setdefault('timeline_sha256', '')
        row.update(calibration='calibrations/group004_candidate.json', calibration_sha256=cal_hash)
    fields = ['group','recording','svo_path','setup_id','source_svo_sha256','frame_count','body_manifest_sha256','timeline_sha256','timeline','calibration','calibration_sha256']
    with (output/'inventory.csv').open('x', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    hashes = {f.relative_to(output).as_posix(): digest(f) for f in output.rglob('*') if f.is_file()}
    record = {'status': 'prepared_not_windows_validated', 'recording_count': len(rows), 'files_sha256': hashes,
              'calibration_depth_source_svo_sha256': summary['source_svo_sha256'],
              'output_policy': 'local images and depth; share only positions.json and manifest.json'}
    (output/'bundle_manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'[準備完了] グループ4: {len(group4)} 録画、グループ5: {len(group5)} 録画: {output}', flush=True)


if __name__ == '__main__':
    main()
