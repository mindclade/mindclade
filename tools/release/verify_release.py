#!/usr/bin/env python3.12
"""Verify release approvals, external signature, transparency, and revocation state."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

try:
    from .build_release_manifest import JsonObject, load_object, validate_payload_digest
    from .sign_release import (
        load_public_key,
        load_transparency_log,
        signature_digest,
        validate_approvals,
        validate_external_signature,
        verify_transparency,
    )
except ImportError:
    from build_release_manifest import JsonObject, load_object, validate_payload_digest
    from sign_release import (
        load_public_key,
        load_transparency_log,
        signature_digest,
        validate_approvals,
        validate_external_signature,
        verify_transparency,
    )


def verify(
    manifest: JsonObject,
    key: ec.EllipticCurvePublicKey,
    key_id: str,
    approvals: Mapping[str, JsonObject],
    transparency_entries: Sequence[JsonObject],
) -> None:
    release_digest = validate_payload_digest(manifest)
    integrity = manifest.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("manifest integrity must be an object")
    signatures = integrity.get("signatures")
    if not isinstance(signatures, list) or len(signatures) != 1:
        raise ValueError("manifest must contain exactly one trusted signature")
    envelope = signatures[0]
    if not isinstance(envelope, dict):
        raise ValueError("external signature entry must be an object")
    validate_external_signature(manifest, envelope, key, key_id, approvals)
    verify_transparency(
        transparency_entries,
        release_payload_digest=release_digest,
        signature_record_digest=signature_digest(envelope),
    )


def verify_paths(
    manifest: JsonObject,
    public_key_path: Path,
    key_id: str,
    k4_approval_path: Path,
    k5_approval_path: Path,
    transparency_log_path: Path,
) -> None:
    approvals = validate_approvals(manifest, k4_approval_path, k5_approval_path)
    verify(
        manifest,
        load_public_key(public_key_path),
        key_id,
        approvals,
        load_transparency_log(transparency_log_path),
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--public-key", type=Path, required=True)
    result.add_argument("--key-id", required=True)
    result.add_argument("--k4-approval", type=Path, required=True)
    result.add_argument("--k5-approval", type=Path, required=True)
    result.add_argument("--transparency-log", type=Path, required=True)
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
        verify_paths(
            manifest,
            args.public_key,
            args.key_id,
            args.k4_approval,
            args.k5_approval,
            args.transparency_log,
        )
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"release verification failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
