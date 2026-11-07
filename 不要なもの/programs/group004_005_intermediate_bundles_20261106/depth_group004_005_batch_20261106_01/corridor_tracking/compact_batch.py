"""Continue group 2/3 using verified existing results and compact retention for new recordings."""
import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from corridor_tracking.portable_depth_replay import create_replay
from depth_person_prototype import digest


ORIGINAL_RUN_IDS = ('20261105_01', '20261105_01_retry01')


def tag_for(row, run_id):
    return f'g{int(row["group"]):03d}_{row["recording"]}_{run_id}'


def existing_run(row, shared, compact_prefix):
    for run_id in ORIGINAL_RUN_IDS:
        if (shared/tag_for(row, run_id)).exists():
            return run_id
    prefix = tag_for(row, compact_prefix)
    matches = sorted((p for p in shared.glob(prefix+'*') if p.is_dir()
                      and re.fullmatch(re.escape(prefix) + r'(?:_retry\d+)?', p.name)), key=lambda p:p.name)
    if len(matches) > 1:
        raise ValueError(f'multiple completed compact runs require review: {row["group"]}/{row["recording"]}')
    return matches[0].name[len(tag_for(row, '')):] if matches else None


def fresh_run(row, root, shared, compact_prefix):
    for number in range(1000):
        run_id = compact_prefix if number == 0 else f'{compact_prefix}_retry{number:02d}'
        tag = tag_for(row, run_id)
        clip_pattern = re.compile(re.escape(tag) + r'_\d{6}_\d{6}$')
        clip_root = root/'depth_clips'
        clip_exists = clip_root.is_dir() and any(clip_pattern.fullmatch(p.name) for p in clip_root.glob(tag+'_*'))
        if not ((root/'analysis'/tag).exists() or (root/'coordinates'/tag).exists()
                or (shared/tag).exists() or clip_exists):
            return run_id
    raise FileExistsError('could not find an unused run ID for this recording')


def validate_existing(row, root, shared, bundle, run_id, compact_prefix):
    tag = tag_for(row, run_id)
    folder = shared/tag
    if {p.name for p in folder.iterdir()} != {'positions.json', 'manifest.json'}:
        raise ValueError(f'invalid existing coordinate share: {folder}')
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8-sig'))
    if (manifest.get('status') != 'complete' or manifest.get('source_svo_sha256') != row['source_svo_sha256']
            or manifest.get('recording') != row['recording'] or str(manifest.get('group')) != row['group']
            or int(manifest.get('frame_count', -1)) != int(row['frame_count'])
            or manifest.get('positions_sha256') != digest(folder/'positions.json')):
        raise ValueError(f'existing coordinates failed validation: {folder}')
    create_replay(root, bundle, int(row['group']), row['recording'], run_id)
    if run_id == compact_prefix or run_id.startswith(compact_prefix+'_retry'):
        receipt = root/'analysis'/tag/'storage_retention.json'
        if not receipt.is_file() or json.loads(receipt.read_text(encoding='utf-8-sig')).get('status') != 'complete':
            raise ValueError(f'compact retention did not finish; preserve files and inspect: {tag}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sdk-python', type=Path, required=True)
    p.add_argument('--local-root', type=Path, required=True)
    p.add_argument('--shared-root', type=Path, required=True)
    p.add_argument('--run-id', default='compact_20261105_01')
    a = p.parse_args()
    if not re.fullmatch(r'compact_[A-Za-z0-9_]+', a.run_id):
        p.error('invalid compact run ID')
    bundle, sdk, root, shared = a.bundle.resolve(), a.sdk_python.resolve(), a.local_root.resolve(), a.shared_root.resolve()
    if not sdk.is_file() or not root.is_dir() or not shared.is_dir():
        p.error('SDK Python, local SSD root, and shared coordinate root must already exist')
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 109 or len({(x['group'], x['recording']) for x in rows}) != len(rows):
        raise ValueError('expected 109 unique recordings')
    if any(x['group'] not in ('2','3') or not re.fullmatch(r'recording_\d{3}', x['recording']) for x in rows):
        raise ValueError('invalid inventory group or recording')
    pending = sum(existing_run(row, shared, a.run_id) is None for row in rows)
    print(f'[Compact batch] {pending} new recordings; existing results are validated and retained.', flush=True)
    done, new_done, new_seconds = 0, 0, 0.
    for row in rows:
        run_id = existing_run(row, shared, a.run_id)
        if run_id is not None:
            print(f'[Compact batch] Checking existing {tag_for(row, run_id)}', flush=True)
            validate_existing(row, root, shared, bundle, run_id, a.run_id)
            done += 1
            continue
        run_id = fresh_run(row, root, shared, a.run_id)
        print(f'[Compact batch] {done}/{len(rows)} checked; starting {tag_for(row, run_id)}', flush=True)
        average = new_seconds/new_done if new_done else 0.
        command = [sys.executable, '-m', 'corridor_tracking.local_depth_pipeline', '--bundle', str(bundle),
                   '--sdk-python', str(sdk), '--local-root', str(root), '--shared-root', str(shared),
                   '--group', row['group'], '--recording', row['recording'], '--run-id', run_id,
                   '--clip-frames', '69', '--point-archive-mode', 'compressed', '--compact-intermediates',
                   '--batch-completed', str(done), '--batch-total', str(len(rows)),
                   '--batch-pending-new', str(pending), '--batch-average-seconds', str(average)]
        started = time.perf_counter()
        code = subprocess.run(command, cwd=bundle, check=False).returncode
        if code:
            raise RuntimeError(f'stopped at {tag_for(row, run_id)}; preserve files and logs')
        new_seconds += time.perf_counter() - started
        new_done += 1; pending -= 1; done += 1
        print(f'[Compact batch] {done}/{len(rows)} checked; {pending} new recordings remain.', flush=True)
    print('[Compact batch] All recordings completed or validated.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
