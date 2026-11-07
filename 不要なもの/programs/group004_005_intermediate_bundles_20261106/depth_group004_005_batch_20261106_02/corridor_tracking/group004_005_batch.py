"""Run or resume compact group 4/5 depth processing with validated existing results."""
import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from corridor_tracking.compact_batch import fresh_run, tag_for, validate_existing


def existing_run(row, shared, prefix):
    candidates = []
    if row['group'] == '4' and row['recording'] == 'recording_006':
        pilot = 'pilot_20261106_02'
        if (shared/tag_for(row, pilot)).is_dir():
            candidates.append(pilot)
    start = tag_for(row, prefix)
    for folder in shared.glob(start+'*'):
        if folder.is_dir() and re.fullmatch(re.escape(start)+r'(?:_retry\d+)?', folder.name):
            candidates.append(folder.name[len(tag_for(row, '')):])
    if len(candidates) > 1:
        raise ValueError(f'multiple shared results for {row["group"]}/{row["recording"]}; inspect before continuing')
    return candidates[0] if candidates else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True, type=Path)
    p.add_argument('--sdk-python', required=True, type=Path)
    p.add_argument('--local-root', required=True, type=Path)
    p.add_argument('--shared-root', required=True, type=Path)
    p.add_argument('--run-id', default='compact_20261106_01')
    a = p.parse_args()
    if not re.fullmatch(r'compact_[A-Za-z0-9_]+', a.run_id):
        p.error('invalid run ID')
    bundle, sdk, root, shared = a.bundle.resolve(), a.sdk_python.resolve(), a.local_root.resolve(), a.shared_root.resolve()
    if not sdk.is_file() or not root.is_dir() or not shared.is_dir():
        p.error('SDK Python, SSD root and coordinate share must exist')
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if not rows or len({(r['group'], r['recording']) for r in rows}) != len(rows) or any(
            r['group'] not in ('4', '5') or not re.fullmatch(r'recording_\d{3}', r['recording']) for r in rows):
        raise ValueError('invalid or duplicated group 4/5 inventory')
    pilots = [row for row in rows if row['group'] == '4' and row['recording'] == 'recording_006']
    if len(pilots) != 1 or existing_run(pilots[0], shared, a.run_id) != 'pilot_20261106_02':
        raise ValueError('expected the completed group 4 recording 006 pilot; inspect shared and SSD results')
    validate_existing(pilots[0], root, shared, bundle, 'pilot_20261106_02', a.run_id)
    receipt = root/'analysis'/tag_for(pilots[0], 'pilot_20261106_02')/'storage_retention.json'
    if not receipt.is_file() or json.loads(receipt.read_text(encoding='utf-8-sig')).get('status') != 'complete':
        raise ValueError('pilot storage validation not complete; preserve files and inspect')
    pending = sum(existing_run(row, shared, a.run_id) is None for row in rows)
    print(f'[一括解析] {len(rows)} 録画中、未処理 {pending} 録画。', flush=True)
    done = new_done = 0
    new_seconds = 0.
    for row in rows:
        run = existing_run(row, shared, a.run_id)
        if run is not None:
            print(f'[一括解析] 完了済みを照合: {tag_for(row, run)}', flush=True)
            if run != 'pilot_20261106_02':
                validate_existing(row, root, shared, bundle, run, a.run_id)
            done += 1
            continue
        run = fresh_run(row, root, shared, a.run_id)
        cmd = [sys.executable, '-m', 'corridor_tracking.local_depth_pipeline', '--bundle', str(bundle),
               '--sdk-python', str(sdk), '--local-root', str(root), '--shared-root', str(shared),
               '--group', row['group'], '--recording', row['recording'], '--run-id', run,
               '--clip-frames', '69', '--point-archive-mode', 'compressed', '--compact-intermediates',
               '--batch-completed', str(done), '--batch-total', str(len(rows)), '--batch-pending-new', str(pending),
               '--batch-average-seconds', str(new_seconds/new_done if new_done else 0.)]
        start = time.perf_counter()
        code = subprocess.run(cmd, cwd=bundle, check=False).returncode
        if code:
            raise RuntimeError(f'stopped at {tag_for(row, run)}; preserve files and logs')
        new_seconds += time.perf_counter()-start
        new_done += 1; pending -= 1; done += 1
        print(f'[一括解析] {done}/{len(rows)} 録画完了・照合済み、残り {pending} 録画。', flush=True)
    print('[一括解析] すべての録画が完了または照合済みです。', flush=True)


if __name__ == '__main__':
    main()
