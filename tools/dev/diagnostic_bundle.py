#!/usr/bin/env python3.12
"""Create a redacted local diagnostic bundle containing no environment values."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any


def command(root: Path, arguments: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            arguments,
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return {"command": arguments[0], "status": "unavailable", "output": str(error)}
    return {
        "command": arguments[0],
        "status": "pass" if completed.returncode == 0 else "fail",
        "output": completed.stdout.strip()[:4000],
    }


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        with suppress(FileNotFoundError):
            Path(temporary_name).unlink()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    bundle = {
        "schema_version": "diagnostic-bundle.v1",
        "repository": "github.com/mindclade/mindclade",
        "connected_qualification": "not_attempted",
        "checks": [
            command(root, ["git", "status", "--short", "--untracked-files=all"]),
            command(root, [sys.executable, "tools/dev/bootstrap.py", "--json"]),
            command(root, [sys.executable, "tools/dev/doctor.py", "--quick", "--json"]),
        ],
    }
    rendered = (json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if args.output:
        atomic_write(args.output, rendered)
    else:
        sys.stdout.buffer.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
