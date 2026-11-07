"""Prepare a verified recording inventory for the group 2/3 depth batch."""
import argparse
import csv
import json
from pathlib import Path

from depth_person_prototype import calibration_for_camera, digest
from zed_sdk_package.tracking_v2.validate_export import validate_export


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exchange-root', type=Path, required=True)
    p.add_argument('--project-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('inventory already exists')
    sources = {2: ['group002_20261104_candidate_01', 'group002_20261104_candidate_02'],
               3: ['group003_20261104_candidate_01']}
    rows, seen = [], set()
    for group, names in sources.items():
        for name in names:
            source = a.exchange_root / name
            with (source/'input_inventory.csv').open(newline='', encoding='utf-8-sig') as f:
                lookup = {r['recording']: r for r in csv.DictReader(f)}
            for body in sorted(source.glob('recording_*/body')):
                rec = body.parent.name
                if (group, rec) in seen or rec not in lookup:
                    raise ValueError(f'duplicate or unmapped recording: {group} {rec}')
                validate_export(body)
                camera = json.loads((body/'camera.json').read_text(encoding='utf-8-sig'))
                manifest = json.loads((body/'manifest.json').read_text(encoding='utf-8-sig'))
                entry = lookup[rec]
                if entry['setup_id'] != camera['setup_id']:
                    raise ValueError(f'inventory setup mismatch: {group} {rec}')
                cal = a.project_root/f'results/tracking_v2/group{group:03d}_20261104_analysis_01/scoped_calibrations/{rec}.json'
                calibration_for_camera(cal, camera)
                rows.append({'group': group, 'recording': rec, 'svo_path': entry['svo_path'],
                    'setup_id': camera['setup_id'], 'source_svo_sha256': camera['source_svo_sha256'],
                    'frame_count': manifest['saved_frames'], 'body_dir': str(body.resolve()),
                    'body_manifest_sha256': digest(body/'manifest.json'), 'calibration': str(cal.resolve()),
                    'calibration_sha256': digest(cal), 'existing_depth': 'yes' if group == 3 and rec == 'recording_018' else 'no'})
                seen.add((group, rec))
                print(f'group {group} {rec} validated', flush=True)
    if not rows:
        raise ValueError('no validated BODY exports')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f'{len(rows)} recordings: {a.output}')


if __name__ == '__main__':
    main()
