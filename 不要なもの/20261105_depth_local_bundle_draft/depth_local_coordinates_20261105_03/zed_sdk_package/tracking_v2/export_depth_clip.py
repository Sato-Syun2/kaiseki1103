#!/usr/bin/env python3
"""Export a contiguous SVO depth clip locally, validate it, and mirror the completed result."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from exchange_copy import copy_batch, stage_worker_scripts


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--svo', type=Path, required=True, help='SVO/SVO2 on a local or attached disk')
    p.add_argument('--setup-id', required=True)
    p.add_argument('--tag', required=True, help='new local run folder name')
    destination = p.add_mutually_exclusive_group(required=True)
    destination.add_argument('--shared-dir', type=Path, help='new shared destination folder')
    destination.add_argument('--local-only', action='store_true', help='do not copy depth or images to a shared folder')
    p.add_argument('--local-root', type=Path, default=Path.home()/'kaiseki1103_exchange')
    p.add_argument('--first-frame', type=int, default=0, help='zero-based SVO frame index')
    p.add_argument('--frame-count', type=int, required=True, help='number of consecutive frames to save')
    p.add_argument('--pixel-stride', type=int, default=2)
    p.add_argument('--expected-svo-sha256', help='optional expected source hash to check before processing')
    a = p.parse_args()
    if not a.svo.is_file() or a.svo.suffix.lower() not in ('.svo', '.svo2'):
        p.error('--svo must be an existing local .svo or .svo2 file')
    if not a.setup_id.strip() or not re.fullmatch(r'[A-Za-z0-9_.-]+', a.tag) or a.tag in ('.','..'):
        p.error('provide a non-empty setup ID and a safe tag containing only letters, digits, dots, underscores or hyphens')
    if a.first_frame < 0 or a.frame_count < 1 or a.pixel_stride < 1:
        p.error('frame index must be nonnegative; frame count and pixel stride must be positive')
    if a.expected_svo_sha256 and not re.fullmatch(r'[0-9a-fA-F]{64}', a.expected_svo_sha256):
        p.error('--expected-svo-sha256 must contain 64 hexadecimal characters')
    local = a.local_root / a.tag
    if local.exists() or (a.shared_dir is not None and a.shared_dir.exists()):
        p.error('local or shared destination already exists; choose a new tag/destination')
    print(f'Hashing source SVO: {a.svo}', flush=True)
    source_hash = sha256_file(a.svo)
    if a.expected_svo_sha256 and source_hash.lower() != a.expected_svo_sha256.lower():
        raise ValueError('SVO SHA-256 differs from the expected recording; no export started')
    package = Path(__file__).resolve().parent
    a.local_root.mkdir(parents=True, exist_ok=True)
    workers = ['export_zed_depth.py','export_depth_batch.py','exchange_copy.py','sync_exchange.py']
    staged = stage_worker_scripts(package, a.local_root, workers)
    local.mkdir(parents=True, exist_ok=False)
    output = local/'depth'
    command = [sys.executable, str(staged/'export_zed_depth.py'), str(a.svo.resolve()),
               '--output', str(output), '--setup-id', a.setup_id, '--depth-mode', 'NEURAL',
               '--match-body-depth-settings', '--pixel-stride', str(a.pixel_stride), '--frame-indices']
    command.extend(str(i) for i in range(a.first_frame, a.first_frame+a.frame_count))
    status = {'status':'export_failed','source_svo_sha256':source_hash,'setup_id':a.setup_id,
              'first_frame':a.first_frame,'frame_count':a.frame_count,'pixel_stride':a.pixel_stride,
              'depth_mode':'NEURAL','started_at':datetime.now().astimezone().isoformat(timespec='seconds'),
              'runner_sha256':sha256_file(Path(__file__)),
              'staged_worker_sha256':{name:sha256_file(staged/name) for name in workers}}
    with (local/'export.log').open('x', encoding='utf-8') as log:
        log.write('command: '+subprocess.list2cmdline(command)+'\n\n'); log.flush()
        try:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            status['export_exit_code'] = result.returncode
        except OSError as exc:
            log.write(f'Could not start exporter: {exc}\n'); status['export_exit_code'] = 1
    if status['export_exit_code'] == 0:
        # Import the locally staged validator in a separate process, without relying on shared storage.
        code = ('import json,sys; from pathlib import Path; '
                'sys.path.insert(0,sys.argv[1]); from export_depth_batch import validate_depth_export; '
                'print(json.dumps(validate_depth_export(Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4])))')
        validation = [sys.executable,'-c',code,str(staged),str(output),str(a.svo.resolve()),a.setup_id]
        with (local/'validation.log').open('x', encoding='utf-8') as log:
            try:
                result = subprocess.run(validation, stdout=log, stderr=subprocess.STDOUT, check=False)
                status['validation_exit_code'] = result.returncode
            except OSError as exc:
                log.write(f'Could not start validator: {exc}\n'); status['validation_exit_code'] = 1
        status['status'] = 'validated' if status['validation_exit_code'] == 0 else 'validation_failed'
        if status['status'] == 'validated':
            camera = json.loads((output/'camera.json').read_text(encoding='utf-8-sig'))
            if camera.get('source_svo_sha256') != source_hash or camera.get('requested_frame_indices') != list(range(a.first_frame,a.first_frame+a.frame_count)):
                status['status'] = 'validation_failed'
                status['validation_error'] = 'source hash or requested frame list disagrees'
    (local/'batch_summary.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Export status: {status["status"]}; local output: {local}', flush=True)
    if status['status'] != 'validated':
        print('Local files and logs are preserved. Choose a new tag after diagnosing the failure.', flush=True)
        return 1
    if a.local_only:
        print('Local-only export: no depth or images were copied to a shared folder.', flush=True)
        return 0
    mirrored, message = copy_batch(local, a.shared_dir)
    print(message, flush=True)
    if not mirrored:
        print(f'Retry later with: {sys.executable} {staged/"sync_exchange.py"} --local-dir {local} --shared-dir <new-shared-dir>', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
