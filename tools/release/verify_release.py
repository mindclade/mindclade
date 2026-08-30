#!/usr/bin/env python3.12
"""Verify a release manifest payload and its trusted P-256 signature."""

from __future__ import annotations

import argparse
import base64
import binascii
from collections.abc import Sequence
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

try:
    from .build_release_manifest import (
        JsonObject,
        canonical_json,
        load_object,
        unsigned_payload,
        validate_payload_digest,
    )
except ImportError:
    from build_release_manifest import (
        JsonObject,
        canonical_json,
        load_object,
        unsigned_payload,
        validate_payload_digest,
    )


def load_public_key(path: Path) -> ec.EllipticCurvePublicKey:
    if path.is_symlink() or not path.is_file():
        raise ValueError("public key must be a regular file")
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("verification key must be ECDSA P-256")
    return key


def verify(manifest: JsonObject, key: ec.EllipticCurvePublicKey, key_id: str) -> None:
    validate_payload_digest(manifest)
    integrity = manifest["integrity"]
    if not isinstance(integrity, dict):
        raise ValueError("manifest integrity must be an object")
    signatures = integrity.get("signatures")
    if not isinstance(signatures, list) or len(signatures) != 1:
        raise ValueError("manifest must contain exactly one trusted signature")
    signature = signatures[0]
    if not isinstance(signature, dict):
        raise ValueError("signature entry must be an object")
    if signature.get("algorithm") != "ecdsa-p256-sha256" or signature.get("key_id") != key_id:
        raise ValueError("signature algorithm or trusted key identity mismatch")
    encoded = signature.get("signature")
    if not isinstance(encoded, str):
        raise ValueError("signature bytes are missing")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except binascii.Error as error:
        raise ValueError("signature is not canonical base64") from error
    try:
        key.verify(decoded, canonical_json(unsigned_payload(manifest)), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise ValueError("release signature is invalid") from error


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--public-key", type=Path, required=True)
    result.add_argument("--key-id", required=True)
    result.add_argument("--expected-subject-digest")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = load_object(args.input)
        if args.expected_subject_digest:
            spec = manifest.get("spec")
            subject = spec.get("subject") if isinstance(spec, dict) else None
            observed = subject.get("digest") if isinstance(subject, dict) else None
            if observed != args.expected_subject_digest:
                raise ValueError("release subject digest mismatch")
        verify(manifest, load_public_key(args.public_key), args.key_id)
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"release verification failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
