#!/usr/bin/env python3.12
"""Attach a detached ECDSA P-256 signature to a release manifest."""

from __future__ import annotations

import argparse
import base64
import os
import re
from collections.abc import Sequence
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

try:
    from .build_release_manifest import (
        atomic_write_json,
        canonical_json,
        load_object,
        unsigned_payload,
        validate_payload_digest,
    )
except ImportError:
    from build_release_manifest import (
        atomic_write_json,
        canonical_json,
        load_object,
        unsigned_payload,
        validate_payload_digest,
    )

KEY_ID_RE = re.compile(r"^[a-z][a-z0-9._:/-]{2,255}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def load_private_key(path: Path) -> ec.EllipticCurvePrivateKey:
    if path.is_symlink() or not path.is_file():
        raise ValueError("private key must be a regular file")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("private key permissions must not grant group or other access")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("signing key must be ECDSA P-256")
    return key


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--private-key", type=Path, required=True)
    result.add_argument("--key-id", required=True)
    result.add_argument("--signed-at", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not KEY_ID_RE.fullmatch(args.key_id):
            raise ValueError("key-id is invalid")
        if not UTC_RE.fullmatch(args.signed_at):
            raise ValueError("signed-at must be a whole-second UTC timestamp")
        manifest = load_object(args.input)
        validate_payload_digest(manifest)
        integrity = manifest.get("integrity")
        if not isinstance(integrity, dict):
            raise ValueError("manifest integrity must be an object")
        if integrity.get("signatures"):
            raise ValueError("manifest is already signed")
        payload = canonical_json(unsigned_payload(manifest))
        signature = load_private_key(args.private_key).sign(payload, ec.ECDSA(hashes.SHA256()))
        integrity["signatures"] = [
            {
                "algorithm": "ecdsa-p256-sha256",
                "key_id": args.key_id,
                "signed_at": args.signed_at,
                "signature": base64.b64encode(signature).decode("ascii"),
            }
        ]
        atomic_write_json(args.output, manifest)
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"release signing failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
