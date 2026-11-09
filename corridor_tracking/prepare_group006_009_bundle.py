"""Prepare an SSD-only group 6–9 bundle with a per-group calibration and SVO timeline.

Recording IDs 900–902 are analysis-only aliases. The physical source name and
reported trial interpretation are recorded separately; no conditions are assigned.
"""
import argparse
import csv
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from corridor_tracking.build_group004_pilot_bundle import digest, validate_calibration
from corridor_tracking.depth_progress import duration
from corridor_tracking.prepare_group004_005_bundle import scope_calibration, validate_timeline, verify_template


def unique_svo(folder):
    if not folder.is_dir():
        raise FileNotFoundError(f'SVO folder missing: {folder}')
    files = sorted(p.resolve() for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.svo', '.svo2'))
    if len(files) != 1:
        raise ValueError(f'expected exactly one SVO beneath {folder}; found {len(files)}')
    return files[0]


def recording_inventory(roots, test_root):
    rows = []
    for group in range(6, 10):
        root = roots[group]
        if not root.is_dir():
            raise FileNotFoundError(f'group {group} directory missing: {root}')
        folders = sorted((p for p in root.iterdir() if p.is_dir() and re.fullmatch(r'recording_\d{3}', p.name)),
                         key=lambda p: p.name)
        if not folders:
            raise ValueError(f'no recording folders found: {root}')
        for folder in folders:
            if int(folder.name[-3:]) >= 900:
                raise ValueError(f'reserved alias conflicts with physical recording: {folder}')
            candidates = [p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.svo', '.svo2')]
            if not candidates:
                print(f'[録画なし] {folder}: SVOがないため条件を割り当てず記録のみ。', flush=True)
                continue
            source = unique_svo(folder)
            reported = ''
            if group == 6 and folder.name in ('recording_001', 'recording_002'):
                reported = 'operator_reported_basic_trial_' + str(int(folder.name[-3:]) + 1)
            rows.append({'group': str(group), 'recording': folder.name, 'svo_path': str(source),
                         'source_label': folder.name, 'reported_trial': reported})
        if group == 6:
            source = unique_svo(root/'calibration_001')
            rows.append({'group': '6', 'recording': 'recording_900', 'svo_path': str(source),
                         'source_label': 'calibration_001', 'reported_trial': 'operator_reported_basic_trial_1'})
        if group == 7:
            for number, label in ((1, 'recording_901'), (2, 'recording_902')):
                folder = test_root/f'test_{number:03d}'
                source = unique_svo(folder)
                rows.append({'group': '7', 'recording': label, 'svo_path': str(source),
                             'source_label': folder.name, 'reported_trial': f'operator_reported_additional_trial_{number+3}_unverified'})
    keys = [(r['group'], r['recording']) for r in rows]
    sources = [str(Path(r['svo_path']).resolve()).casefold() for r in rows]
    if len(keys) != len(set(keys)) or len(sources) != len(set(sources)):
        raise ValueError('duplicate recording identity or source path; inspect before continuing')
    return rows


def prepare(template, output, roots, test_root, local_root, sdk_python, cache):
    template, output = template.resolve(), output.resolve()
    manifest = verify_template(template)
    if output.exists():
        raise FileExistsError(f'bundle already exists: {output}')
    rows = recording_inventory(roots, test_root)
    calibrations = {}
    for group in range(6, 10):
        tag = f'g{group:03d}_calibration_depth_20261107_01'
        export = local_root/'calibration_preparation'/tag
        cal_path = local_root/'calibration_preparation'/(tag+'_floor_wall_candidate')/'zed_corridor_candidate.json'
        cal = json.loads(cal_path.read_text(encoding='utf-8-sig'))
        summary = json.loads((export/'batch_summary.json').read_text(encoding='utf-8-sig'))
        cal_camera = json.loads((export/'depth/camera.json').read_text(encoding='utf-8-sig'))
        expected = roots[group]/('calibration_002' if group == 6 else 'calibration_001')
        if Path(cal_camera['source_svo']).resolve() != unique_svo(expected):
            raise ValueError(f'group {group} calibration source does not match group directory')
        if digest(Path(cal_camera['source_svo'])) != summary.get('source_svo_sha256'):
            raise ValueError(f'group {group} calibration SVO has changed')
        calibrations[group] = (cal, summary, cal_camera, export, cal_path)
    cache.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    for index, row in enumerate(rows, 1):
        group, rec = int(row['group']), row['recording']
        cal, summary, cal_camera, export, cal_path = calibrations[group]
        svo = Path(row['svo_path'])
        timeline_path = cache/f'g{group:03d}_{rec}.json'
        remaining = duration((time.monotonic()-start)/(index-1)*(len(rows)-index+1)) if index > 1 else '算定中'
        print(f'[時刻準備] 完了 {index-1}/{len(rows)}; G{group:03d} {rec}; 残り約 {remaining}', flush=True)
        if not timeline_path.exists():
            subprocess.run([str(sdk_python), str(template/'zed_sdk_package/tracking_v2/export_svo_timeline.py'),
                            '--svo', str(svo), '--setup-id', cal['setup_id'], '--output', str(timeline_path)], check=True)
        timeline = json.loads(timeline_path.read_text(encoding='utf-8-sig'))
        camera, frames = validate_timeline(timeline, svo, cal['setup_id'])
        validate_calibration(cal, summary, cal_camera, camera, export, max_intrinsics_delta_px=1.0)
        row.update(setup_id=cal['setup_id'], source_svo_sha256=camera['source_svo_sha256'], frame_count=str(len(frames)),
                   body_manifest_sha256='', timeline_sha256=digest(timeline_path),
                   timeline=f'timelines/g{group:03d}_{rec}.json', calibration=f'calibrations/g{group:03d}_{rec}.json',
                   base_calibration_sha256=digest(cal_path),
                   camera_intrinsics_left=json.dumps(camera['intrinsics_left'], sort_keys=True, separators=(',', ':')))
    output.mkdir(parents=True, exist_ok=False)
    for name, expected in manifest['files_sha256'].items():
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template/name, target)
        if digest(target) != expected:
            raise OSError(f'template copy mismatch: {name}')
    for row in rows:
        group, rec = int(row['group']), row['recording']
        timeline_path = cache/f'g{group:03d}_{rec}.json'
        timeline = json.loads(timeline_path.read_text(encoding='utf-8-sig'))
        target = output/row['timeline']; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(timeline_path, target)
        if digest(target) != row['timeline_sha256']:
            raise OSError('timeline copy mismatch')
        cal, _, _, _, cal_path = calibrations[group]
        target = output/row['calibration']; target.parent.mkdir(parents=True, exist_ok=True)
        scoped = scope_calibration(cal, timeline['camera'], digest(cal_path))
        if scoped is None:
            shutil.copyfile(cal_path, target)
        else:
            target.write_text(json.dumps(scoped, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        row['calibration_sha256'] = digest(target)
    fields = ['group', 'recording', 'svo_path', 'source_label', 'reported_trial', 'setup_id', 'source_svo_sha256',
              'frame_count', 'body_manifest_sha256', 'timeline_sha256', 'timeline', 'calibration', 'calibration_sha256',
              'base_calibration_sha256', 'camera_intrinsics_left']
    with (output/'inventory.csv').open('x', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    hashes = {f.relative_to(output).as_posix(): digest(f) for f in output.rglob('*') if f.is_file()}
    info = {'status': 'prepared_not_windows_validated', 'recording_count': len(rows), 'files_sha256': hashes,
            'calibration_source_svo_sha256': {str(g): c[1]['source_svo_sha256'] for g,c in calibrations.items()},
            'alias_policy': '900 group6 calibration take1; 901/902 group7 test1/test2; reported trial mappings unverified',
            'output_policy': 'local depth and images; share only coordinates and provenance'}
    (output/'bundle_manifest.json').write_text(json.dumps(info, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'[準備完了] {len(rows)} 録画: {output}', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('template', 'output', 'g6-root', 'g7-root', 'g8-root', 'g9-root', 'test-root', 'local-root', 'sdk-python', 'timeline-cache'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    return prepare(a.template, a.output, {6:a.g6_root,7:a.g7_root,8:a.g8_root,9:a.g9_root}, a.test_root,
                   a.local_root, a.sdk_python, a.timeline_cache)


if __name__ == '__main__':
    main()
