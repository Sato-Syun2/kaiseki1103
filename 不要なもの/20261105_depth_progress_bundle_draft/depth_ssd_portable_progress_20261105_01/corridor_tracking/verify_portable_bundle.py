"""Verify the copied portable bundle before running code or migrating data."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    a = p.parse_args()
    root = a.bundle.resolve()
    manifest = json.loads((root/'bundle_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'prepared_not_windows_validated' or not manifest.get('files_sha256'):
        raise ValueError('invalid bundle manifest')
    for name, expected in manifest['files_sha256'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f'bundle file missing or unsafe: {name}')
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(1024*1024), b''):
                h.update(block)
        if h.hexdigest() != expected:
            raise ValueError(f'bundle file hash mismatch: {name}')
    print(f'Verified {len(manifest["files_sha256"])} portable bundle files.', flush=True)


if __name__ == '__main__':
    main()
