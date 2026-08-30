#!/usr/bin/env python3.12
"""Verify the canonical digest and exact subject of qualification evidence."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.release.build_release_manifest import (
    JsonObject,
    canonical_json,
    load_object,
    sha256_digest,
)


def verify_record(record: JsonObject) -> None:
    integrity = record.get("integrity")
    metadata = record.get("metadata")
    spec = record.get("spec")
    if (
        not isinstance(integrity, dict)
        or not isinstance(metadata, dict)
        or not isinstance(spec, dict)
    ):
        raise ValueError("evidence must contain object integrity, metadata, and spec")
    unsigned = dict(record)
    unsigned.pop("integrity", None)
    if integrity.get("payload_digest") != sha256_digest(canonical_json(unsigned)):
        raise ValueError("payload digest mismatch")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-claim", required=True)
    parser.add_argument("--expected-target", required=True)
    args = parser.parse_args(argv)
    record = load_object(args.input)
    try:
        verify_record(record)
    except (TypeError, ValueError) as error:
        raise SystemExit(f"evidence verification failed: {error}") from error
    metadata = record.get("metadata")
    spec = record.get("spec")
    if not isinstance(metadata, dict) or not isinstance(spec, dict):
        raise SystemExit("evidence verification failed: evidence envelope is invalid")
    if metadata.get("claim_id") != args.expected_claim:
        raise SystemExit("evidence verification failed: claim mismatch")
    if spec.get("target") != args.expected_target:
        raise SystemExit("evidence verification failed: target mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
