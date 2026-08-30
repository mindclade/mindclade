#!/usr/bin/env python3.12
"""Emit the deterministic, non-secret build environment profile."""

from __future__ import annotations

import argparse
import json
import shlex
from collections.abc import Sequence

PROFILE = {
    "LANG": "C",
    "LC_ALL": "C",
    "PYTHONHASHSEED": "0",
    "TZ": "UTC",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "shell"), default="json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.format == "json":
        print(json.dumps(PROFILE, sort_keys=True, separators=(",", ":")))
    else:
        for key, value in sorted(PROFILE.items()):
            print(f"export {key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
