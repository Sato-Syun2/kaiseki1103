#!/usr/bin/env python3
"""Copy a completed local export to a shared folder without risking the local copy."""

from __future__ import annotations

from pathlib import Path
import shutil
import uuid


def _file_sizes(root: Path) -> dict[str, int]:
    return {
        path.relative_to(root).as_posix(): path.stat().st_size
        for path in root.rglob("*")
        if path.is_file()
    }


def copy_batch(source: Path, target: Path) -> tuple[bool, str]:
    """Publish a complete tree at target; leave source untouched on every failure."""
    source = source.expanduser()
    target = target.expanduser()
    staging = target.with_name(f".{target.name}.partial-{uuid.uuid4().hex[:12]}")
    try:
        if not source.is_dir():
            raise FileNotFoundError(f"local export folder does not exist: {source}")
        if target.exists():
            raise FileExistsError(f"shared destination already exists; refusing to overwrite: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, staging)
        if _file_sizes(source) != _file_sizes(staging):
            raise OSError("shared copy verification failed: file list or sizes differ")
        staging.rename(target)
        return True, f"shared copy complete: {target}"
    except Exception as exc:
        try:
            if staging.exists():
                shutil.rmtree(staging)
        except OSError:
            pass
        return False, f"shared copy unavailable or failed: {exc}; local data is preserved at {source}"


def stage_worker_scripts(package_dir: Path, local_root: Path, names: list[str]) -> Path:
    """Snapshot child tools locally so an SMB disconnect cannot break an active export."""
    cache = local_root / ".sdk_tools" / package_dir.name
    cache.mkdir(parents=True, exist_ok=True)
    for name in names:
        source = package_dir / name
        destination = cache / name
        temporary = cache / f".{name}.copy-{uuid.uuid4().hex[:12]}"
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    return cache
