#!/usr/bin/env python3
"""Retry copying a previously completed local export to shared exchange."""

from __future__ import annotations

import argparse
from pathlib import Path

from exchange_copy import copy_batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True, help="completed local export folder")
    parser.add_argument("--shared-dir", type=Path, required=True, help="new shared destination folder")
    args = parser.parse_args()
    copied, message = copy_batch(args.local_dir, args.shared_dir)
    print(message)
    return 0 if copied else 1


if __name__ == "__main__":
    raise SystemExit(main())
