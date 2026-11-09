"""Use an SSD coordinate queue; mirror completed group 6–9 packets when connected."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import threading

import corridor_tracking.offline_group004_005 as queue


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'sdk-python', 'local-root', 'shared-root'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--sync-only', action='store_true')
    a = p.parse_args()
    bundle, root = a.bundle.resolve(), a.local_root.resolve()
    stage = root/'coordinate_queue_group006_009_20261107_01'
    from zed_sdk_package.tracking_v2.exchange_copy import copy_batch
    queue.TAG = re.compile(r'^g(006|007|008|009)_(recording_\d{3})_(compact_20261107_01(?:_retry\d+)?)$')
    rows = queue.load_rows(bundle)
    queue.bootstrap(root, stage, rows, {}, copy_batch)
    if a.sync_only:
        count, pending = queue.sync_once(root, stage, a.shared_root, rows, copy_batch)
        print(f'[Share] verified: {count}; pending: {len(pending)}', flush=True)
        for tag, reason in pending: print(f'[Share pending] {tag}: {reason}', flush=True)
        return 2 if pending else 0
    done = threading.Event()
    def mirror():
        previous = None
        while not done.is_set():
            try:
                count, pending = queue.sync_once(root, stage, a.shared_root, rows, copy_batch)
                status = (count, len(pending), pending[0][1] if pending else '')
                if status != previous:
                    print(f'[Share] verified: {count}; pending: {len(pending)}'+(f'; {pending[0][1]}' if pending else ''), flush=True)
                    previous = status
            except Exception as exc:
                print(f'[Share] unavailable; SSD analysis continues: {exc}', flush=True)
            done.wait(120)
    thread = threading.Thread(target=mirror, daemon=True); thread.start()
    command = [sys.executable, '-m', 'corridor_tracking.group006_009_batch', '--bundle', str(bundle),
               '--sdk-python', str(a.sdk_python), '--local-root', str(root), '--queue-root', str(stage)]
    try:
        return subprocess.run(command, cwd=bundle, check=False).returncode
    finally:
        done.set(); thread.join(timeout=2)
        print('[Share] Run sync-only after reconnecting if anything remains pending.', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
