"""Copy existing local depth results to an SSD without overwriting or deleting data."""
import argparse
import hashlib
from pathlib import Path
import tempfile

from depth_person_prototype import digest


def copy_tree_checked(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('source and destination must be separate directory trees')
    if not source.is_dir():
        return 0, 0
    copied = existing = 0
    for src in sorted(source.rglob('*')):
        if src.is_symlink():
            raise ValueError(f'symbolic link is not supported: {src}')
        if not src.is_file():
            continue
        dst = target/src.relative_to(source)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if not dst.is_file() or src.stat().st_size != dst.stat().st_size or digest(src) != digest(dst):
                raise FileExistsError(f'existing destination differs: {dst}')
            existing += 1
            continue
        before = src.stat()
        tmp = None
        try:
            with src.open('rb') as inp, tempfile.NamedTemporaryFile('wb', dir=dst.parent, delete=False, suffix='.partial') as out:
                tmp = Path(out.name)
                h = hashlib.sha256()
                while block := inp.read(1024*1024):
                    out.write(block); h.update(block)
            after = src.stat()
            if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns or
                    tmp.stat().st_size != after.st_size or digest(tmp) != h.hexdigest()):
                raise OSError(f'source changed or copy verification failed: {src}')
            if dst.exists():
                raise FileExistsError(f'destination appeared during copy: {dst}')
            tmp.replace(dst)
            copied += 1
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
    return copied, existing


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--destination-root', type=Path, required=True)
    a = p.parse_args()
    for name in ('depth_clips', 'analysis', 'coordinates'):
        copied, existing = copy_tree_checked(a.source_root/name, a.destination_root/name)
        print(f'{name}: copied {copied}, verified existing {existing}; originals retained', flush=True)


if __name__ == '__main__':
    main()
