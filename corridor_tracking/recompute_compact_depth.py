"""Recompute one compacted recording from its original SVO into a new run."""
import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys

from corridor_tracking.compact_depth_results import TAG
from depth_person_prototype import digest, safe_asset


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compact-root', type=Path, required=True)
    p.add_argument('--tag', required=True, help='recording tag recorded in compact_manifest.json')
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sdk-python', type=Path, required=True)
    p.add_argument('--local-root', type=Path, required=True)
    p.add_argument('--shared-root', type=Path, required=True)
    p.add_argument('--new-run-id', required=True)
    a = p.parse_args()
    match = TAG.fullmatch(a.tag)
    if not match or not re.fullmatch(r'[A-Za-z0-9_]+', a.new_run_id):
        p.error('invalid recording tag or new run ID')
    if a.new_run_id == match.group(3):
        p.error('new run ID must differ from the original run ID')
    root, bundle = a.compact_root.resolve(), a.bundle.resolve()
    report = json.loads((root/'compact_manifest.json').read_text(encoding='utf-8-sig'))
    selected = [x for x in report.get('recordings', []) if x.get('tag') == a.tag]
    if report.get('status') != 'complete' or len(selected) != 1:
        raise ValueError('compact archive is incomplete or recording is missing/duplicated')
    record = selected[0]
    hashes = report.get('files_sha256', {})
    for name in (f'coordinates/{a.tag}/positions.json', f'coordinates/{a.tag}/manifest.json',
                 f'analysis/{a.tag}/merged/manifest.json', f'calibrations/{a.tag}.json', f'timelines/{a.tag}.json'):
        if name not in hashes or digest(safe_asset(root, name)) != hashes[name]:
            raise ValueError(f'compact provenance file missing or changed: {name}')
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = [r for r in csv.DictReader(f) if r['group'] == str(int(match.group(1))) and r['recording'] == match.group(2)]
    if len(rows) != 1:
        raise ValueError('recording missing or duplicated in bundle inventory')
    row = rows[0]
    for key in ('source_svo_sha256', 'calibration_sha256', 'body_manifest_sha256', 'setup_id'):
        if row[key] != record.get(key):
            raise ValueError(f'current bundle and original provenance differ: {key}')
    if Path(row['svo_path']).resolve() != Path(record['source_svo_path']).resolve():
        raise ValueError('source SVO path differs from the recorded path; prepare a verified bundle for the new location')
    if not Path(row['svo_path']).is_file():
        raise FileNotFoundError(f'original SVO not found: {row["svo_path"]}')
    print('Recomputing from the original SVO. The SDK will validate its SHA-256; results may not be bit-identical.', flush=True)
    command = [sys.executable, '-m', 'corridor_tracking.local_depth_pipeline', '--bundle', str(bundle),
               '--sdk-python', str(a.sdk_python.resolve()), '--local-root', str(a.local_root.resolve()),
               '--shared-root', str(a.shared_root.resolve()), '--group', str(int(match.group(1))),
               '--recording', match.group(2), '--run-id', a.new_run_id]
    return subprocess.run(command, cwd=bundle, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
