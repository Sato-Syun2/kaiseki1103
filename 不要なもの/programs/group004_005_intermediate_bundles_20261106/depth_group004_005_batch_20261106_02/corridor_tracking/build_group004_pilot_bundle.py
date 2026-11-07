"""Create a new single-recording pilot bundle using a locally generated calibration."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def same_image_coordinates(*values):
    """Accept the two IMAGE names emitted by our BODY and depth exporters."""
    allowed = {'IMAGE', 'IMAGE (x right, y down, z forward)'}
    return all(value in allowed for value in values)


def validate_calibration(cal, summary, calibration_camera, camera, calibration_export):
    if summary.get('status') != 'validated' or summary.get('setup_id') != cal.get('setup_id'):
        raise ValueError('calibration depth export is not validated or has a different setup')
    if summary.get('source_svo_sha256') != calibration_camera.get('source_svo_sha256'):
        raise ValueError('calibration export source differs')
    if Path(cal['source_depth_dir']).resolve() != (calibration_export/'depth').resolve():
        raise ValueError('calibration candidate does not reference this depth export')
    if cal.get('provisional') is not True or not cal.get('applies_to'):
        raise ValueError('expected a scoped provisional calibration')
    if not same_image_coordinates(cal['applies_to'].get('coordinate_system'),
                                  camera.get('coordinate_system'), calibration_camera.get('coordinate_system')):
        raise ValueError('calibration camera mismatch: coordinate_system')
    for key, expected in cal['applies_to'].items():
        if key == 'coordinate_system':
            continue
        if expected is not None and (camera.get(key) != expected or calibration_camera.get(key) != expected):
            raise ValueError(f'calibration camera mismatch: {key}')
    if cal['setup_id'] != camera.get('setup_id'):
        raise ValueError('recording setup differs')
    for key in ('camera_height_above_floor_m', 'visible_wall_Y_m'):
        if not math.isfinite(float(cal[key])):
            raise ValueError(f'invalid calibration: {key}')
    vectors = list(cal['corridor_basis_camera_image'].values())
    if len(vectors) != 3 or any(len(v) != 3 for v in vectors):
        raise ValueError('invalid calibration basis')
    for i, v in enumerate(vectors):
        for j, w in enumerate(vectors):
            if abs(sum(float(x)*float(y) for x,y in zip(v,w)) - (1 if i == j else 0)) > 0.001:
                raise ValueError('calibration basis is not orthonormal')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template', required=True, type=Path)
    p.add_argument('--calibration', required=True, type=Path)
    p.add_argument('--calibration-export', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    template, output = a.template.resolve(), a.output.resolve()
    if output.exists():
        raise FileExistsError('pilot bundle already exists')
    manifest = json.loads((template/'template_manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files_sha256'].items():
        path = (template/name).resolve()
        if not path.is_relative_to(template) or not path.is_file() or digest(path) != expected:
            raise ValueError(f'pilot template verification failed: {name}')
    cal = json.loads(a.calibration.read_text(encoding='utf-8-sig'))
    summary = json.loads((a.calibration_export/'batch_summary.json').read_text(encoding='utf-8-sig'))
    calibration_camera = json.loads((a.calibration_export/'depth/camera.json').read_text(encoding='utf-8-sig'))
    timeline = json.loads((template/'timelines/g004_recording_006.json').read_text(encoding='utf-8'))
    camera = timeline['camera']
    validate_calibration(cal, summary, calibration_camera, camera, a.calibration_export)
    row = json.loads((template/'pilot_inventory.json').read_text(encoding='utf-8'))
    row['calibration'] = 'calibrations/g004_candidate.json'
    row['calibration_sha256'] = digest(a.calibration)
    output.mkdir(parents=True, exist_ok=False)
    for name in manifest['files_sha256']:
        if name == 'pilot_inventory.json' or name == 'build_group004_pilot_bundle.py':
            continue
        dest = output/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template/name, dest)
        if digest(dest) != manifest['files_sha256'][name]:
            raise OSError(f'copied pilot file differs: {name}')
    (output/'calibrations').mkdir()
    shutil.copyfile(a.calibration, output/row['calibration'])
    if digest(output/row['calibration']) != row['calibration_sha256']:
        raise OSError('copied calibration differs')
    with (output/'inventory.csv').open('x', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
    hashes = {f.relative_to(output).as_posix(): digest(f) for f in output.rglob('*') if f.is_file()}
    out = {'status': 'prepared_not_windows_validated', 'recording_count': 1,
           'files_sha256': hashes, 'calibration_depth_source_svo_sha256': summary['source_svo_sha256'],
           'output_policy': 'local depth and images; share only positions.json and manifest.json'}
    (output/'bundle_manifest.json').write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Created pilot bundle: {output}', flush=True)


if __name__ == '__main__':
    main()
