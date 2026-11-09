"""Run or resume depth processing using an SSD queue for groups 6–9."""
import argparse
import csv
from pathlib import Path
import re
import subprocess
import sys
import time

from corridor_tracking.compact_batch import fresh_run, tag_for, validate_existing


def existing(row, queue, prefix):
    start = tag_for(row, prefix)
    matches = [p for p in queue.glob(start+'*') if p.is_dir() and
               re.fullmatch(re.escape(start)+r'(?:_retry\d+)?', p.name)]
    if len(matches) > 1:
        raise ValueError(f'multiple completed results for {row["group"]}/{row["recording"]}; inspect')
    return matches[0].name[len(tag_for(row, '')):] if matches else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'sdk-python', 'local-root', 'queue-root'):
        p.add_argument('--'+name, required=True, type=Path)
    p.add_argument('--run-id', default='compact_20261107_01')
    a = p.parse_args()
    if not re.fullmatch(r'compact_[A-Za-z0-9_]+', a.run_id):
        p.error('invalid run ID')
    bundle, sdk, root, queue = (x.resolve() for x in (a.bundle, a.sdk_python, a.local_root, a.queue_root))
    if not sdk.is_file() or not root.is_dir() or not queue.is_dir():
        p.error('SDK Python, SSD root and SSD queue must exist')
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if (not rows or len({(r['group'], r['recording']) for r in rows}) != len(rows) or
            any(r['group'] not in ('6','7','8','9') or not re.fullmatch(r'recording_\d{3}', r['recording']) for r in rows)):
        raise ValueError('invalid or duplicated group 6–9 inventory')
    pending = sum(existing(row, queue, a.run_id) is None for row in rows)
    print(f'[一括解析] {len(rows)} 録画中、未処理 {pending} 録画。', flush=True)
    done = new_done = 0; new_seconds = 0.
    for row in rows:
        run = existing(row, queue, a.run_id)
        if run is not None:
            validate_existing(row, root, queue, bundle, run, a.run_id)
            done += 1
            print(f'[一括解析] 完了済み照合: {tag_for(row, run)}', flush=True)
            continue
        run = fresh_run(row, root, queue, a.run_id)
        command = [sys.executable, '-m', 'corridor_tracking.local_depth_pipeline', '--bundle', str(bundle),
                   '--sdk-python', str(sdk), '--local-root', str(root), '--shared-root', str(queue),
                   '--group', row['group'], '--recording', row['recording'], '--run-id', run,
                   '--clip-frames', '69', '--point-archive-mode', 'compressed', '--compact-intermediates',
                   '--batch-completed', str(done), '--batch-total', str(len(rows)), '--batch-pending-new', str(pending),
                   '--batch-average-seconds', str(new_seconds/new_done if new_done else 0.)]
        started = time.perf_counter()
        if subprocess.run(command, cwd=bundle, check=False).returncode:
            raise RuntimeError(f'stopped at {tag_for(row, run)}; preserve files and logs')
        new_seconds += time.perf_counter()-started; new_done += 1; pending -= 1; done += 1
        print(f'[一括解析] {done}/{len(rows)} 完了・照合済み、残り {pending} 録画。', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
