#!/usr/bin/env python3.12
"""Create a sanitized, caller-declared qualification hardware envelope."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.release.build_release_manifest import JsonObject, atomic_write_json, validate_digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--operating-system", required=True)
    parser.add_argument("--cpu-class", required=True)
    parser.add_argument("--toolchain-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    for field in (args.architecture, args.operating_system, args.cpu_class):
        if not field or field.strip() != field:
            raise SystemExit(
                "hardware envelope failed: hardware fields must be non-empty trimmed strings"
            )
    envelope: JsonObject = {
        "schema_version": "mindclade.hardware-envelope/v1",
        "architecture": args.architecture,
        "operating_system": args.operating_system,
        "cpu_class": args.cpu_class,
        "accelerators": [],
        "toolchain_digest": validate_digest(args.toolchain_digest, "toolchain-digest"),
        "source": "caller-declared-and-ci-attested",
    }
    atomic_write_json(args.output, envelope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
