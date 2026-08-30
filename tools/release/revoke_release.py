#!/usr/bin/env python3.12
"""Emit a source-only revocation intent without mutating a registry."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

try:
    from .build_release_manifest import atomic_write_json, load_object, validate_payload_digest
    from .verify_release import load_public_key, verify
except ImportError:
    from build_release_manifest import atomic_write_json, load_object, validate_payload_digest
    from verify_release import load_public_key, verify

UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REASON_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not UTC_RE.fullmatch(args.created_at) or not REASON_RE.fullmatch(args.reason_code):
            raise ValueError("created-at or reason-code is invalid")
        manifest = load_object(args.manifest)
        verify(manifest, load_public_key(args.public_key), args.key_id)
        intent = {
            "schema_version": "mindclade.release-transition/v1",
            "kind": "RevocationIntent",
            "source_only": True,
            "connected_execution": False,
            "release_payload_digest": validate_payload_digest(manifest),
            "reason_code": args.reason_code,
            "actor": args.actor,
            "created_at": args.created_at,
        }
        atomic_write_json(args.output, intent)
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"revocation intent failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
