"""Run the existing group 4/5 batch against an SSD queue and mirror coordinates opportunistically."""
import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

TAG = re.compile(r'^g(004|005)_(recording_\d{3})_(compact_20261106_01(?:_retry\d+)?|pilot_20261106_02)$')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_rows(bundle):
    with (bundle/'inventory.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    out = {(r['group'], r['recording']): r for r in rows}
    if len(out) != len(rows) or not rows:
        raise ValueError('invalid inventory')
    return out


def packet(path, row):
    if not path.is_dir() or {p.name for p in path.iterdir()} != {'manifest.json', 'positions.json'}:
        raise ValueError(f'incomplete coordinate packet: {path}')
    manifest = read_json(path/'manifest.json')
    if (manifest.get('status') != 'complete' or manifest.get('positions_sha256') != sha(path/'positions.json')
            or manifest.get('source_svo_sha256') != row['source_svo_sha256']
            or str(manifest.get('group')) != row['group'] or manifest.get('recording') != row['recording']
            or int(manifest.get('frame_count', -1)) != int(row['frame_count'])):
        raise ValueError(f'coordinate packet failed validation: {path}')
    return manifest


def local_complete(root, tag, row):
    coord = root/'coordinates'/tag
    receipt = root/'analysis'/tag/'storage_retention.json'
    if not receipt.is_file():
        return False
    info = read_json(receipt)
    if info.get('status') != 'complete':
        return False
    manifest = packet(coord, row)
    if info.get('positions_sha256') != manifest['positions_sha256']:
        raise ValueError(f'retention receipt mismatch: {tag}')
    replay = root/'analysis'/tag/'merged'/'portable_replay.html'
    if not replay.is_file() or info.get('replay_sha256') != sha(replay):
        raise ValueError(f'portable replay missing or changed: {tag}')
    return True


def add_to_stage(root, stage, tag, row, copy_batch):
    if not local_complete(root, tag, row):
        return False
    source, target = root/'coordinates'/tag, stage/tag
    if target.exists():
        packet(target, row)
        if sha(source/'positions.json') != sha(target/'positions.json') or sha(source/'manifest.json') != sha(target/'manifest.json'):
            raise ValueError(f'SSD queue conflicts with local coordinates: {tag}')
    else:
        ok, message = copy_batch(source, target)
        if not ok:
            raise OSError(message)
        packet(target, row)
    return True


def bootstrap(root, stage, rows, expected, copy_batch):
    stage.mkdir(parents=True, exist_ok=True)
    for tag, position_sha in expected.items():
        match = TAG.fullmatch(tag)
        if not match or (str(int(match[1])),match[2]) not in rows:
            raise ValueError(f'bad completed-result snapshot: {tag}')
        row = rows[(str(int(match[1])),match[2])]
        if not add_to_stage(root, stage, tag, row, copy_batch) or sha(stage/tag/'positions.json') != position_sha:
            raise ValueError(f'previously shared result missing or changed on SSD: {tag}; do not reprocess')
    coords = root/'coordinates'
    if coords.is_dir():
        for source in sorted(coords.iterdir()):
            match = TAG.fullmatch(source.name)
            if not source.is_dir() or not match:
                continue
            row = rows.get((str(int(match[1])),match[2]))
            if row:
                add_to_stage(root, stage, source.name, row, copy_batch)
    seen = {}
    for path in stage.iterdir():
        match = TAG.fullmatch(path.name)
        if not match or not path.is_dir():
            continue
        key = (str(int(match[1])),match[2])
        if key not in rows or key in seen:
            raise ValueError(f'duplicate or unexpected SSD queued result: {path.name}')
        if not local_complete(root, path.name, rows[key]):
            raise ValueError(f'SSD queue has no validated local result: {path.name}')
        packet(path, rows[key])
        seen[key] = path.name
    print(f'[SSD queue] {len(seen)} completed recordings verified locally.', flush=True)


def sync_once(root, stage, shared, rows, copy_batch):
    pending = []
    completed = 0
    for source in sorted(stage.iterdir()):
        match = TAG.fullmatch(source.name)
        if not match or not source.is_dir():
            continue
        row = rows.get((str(int(match[1])), match[2]))
        if row is None:
            continue
        try:
            if not local_complete(root, source.name, row):
                continue  # pipeline has not finished replay and retention
            manifest = packet(source, row)
            target = shared/source.name
            if not shared.is_dir():
                raise OSError('shared folder unavailable')
            prefix = f'g{int(row["group"]):03d}_{row["recording"]}_'
            for other_path in shared.glob(prefix+'*'):
                if other_path.name != source.name and TAG.fullmatch(other_path.name) and other_path.is_dir():
                    raise ValueError(f'other run already exists on share: {other_path.name}; never overwritten')
            if target.exists():
                other = packet(target, row)
                if (other['positions_sha256'] != manifest['positions_sha256'] or
                        sha(target/'manifest.json') != sha(source/'manifest.json')):
                    raise ValueError('shared destination has different data; never overwritten')
            else:
                ok, msg = copy_batch(source, target)
                if not ok:
                    raise OSError(msg)
                other = packet(target, row)
                if other['positions_sha256'] != manifest['positions_sha256'] or sha(target/'manifest.json') != sha(source/'manifest.json'):
                    raise ValueError('shared file verification failed')
                print(f'[Share] Published and verified: {source.name}', flush=True)
            completed += 1
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            pending.append((source.name, str(exc)))
    return completed, pending


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True); p.add_argument('--sdk-python',type=Path,required=True)
    p.add_argument('--local-root',type=Path,required=True); p.add_argument('--shared-root',type=Path,required=True)
    p.add_argument('--snapshot',type=Path,required=True); p.add_argument('--sync-only',action='store_true')
    a=p.parse_args()
    bundle,root = a.bundle.resolve(),a.local_root.resolve()
    stage = root/'coordinate_queue_group004_005_20261106_01'
    sys.path.insert(0,str(bundle))
    from zed_sdk_package.tracking_v2.exchange_copy import copy_batch
    rows = load_rows(bundle)
    expected = read_json(a.snapshot)['positions_sha256']
    bootstrap(root,stage,rows,expected,copy_batch)
    if a.sync_only:
        count,pending = sync_once(root,stage,a.shared_root,rows,copy_batch)
        print(f'[Share] verified: {count}; pending: {len(pending)}',flush=True)
        for tag,reason in pending:
            print(f'[Share pending] {tag}: {reason}',flush=True)
        return 2 if pending else 0
    done = threading.Event()
    def mirror():
        previous = None
        while not done.is_set():
            try:
                count,pending = sync_once(root,stage,a.shared_root,rows,copy_batch)
                status = (count,len(pending),pending[0][1] if pending else '')
                if status != previous:
                    print(f'[Share] verified: {count}; pending: {len(pending)}'+(f'; {pending[0][1]}' if pending else ''),flush=True)
                    previous = status
            except Exception as exc:
                print(f'[Share] temporarily unavailable; SSD analysis continues: {exc}',flush=True)
            done.wait(120)
    thread = threading.Thread(target=mirror,daemon=True)
    thread.start()
    cmd=[sys.executable,'-m','corridor_tracking.group004_005_batch','--bundle',str(bundle),
         '--sdk-python',str(a.sdk_python),'--local-root',str(root),'--shared-root',str(stage),
         '--run-id','compact_20261106_01']
    try:
        return subprocess.run(cmd,cwd=bundle,check=False).returncode
    finally:
        done.set()
        thread.join(timeout=2)
        print('[Share] The background sync stopped. Run sync-only after reconnecting if anything remains pending.',flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
