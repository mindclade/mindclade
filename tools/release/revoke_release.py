#!/usr/bin/env python3.12
"""Exercise source-only release revocation and immutable rollback selection."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

try:
    from .build_release_manifest import (
        JsonObject,
        atomic_write_json,
        load_object,
        validate_payload_digest,
    )
    from .sign_release import IDENTITY_RE, append_transparency_event
    from .verify_release import verify_paths
except ImportError:
    from build_release_manifest import (
        JsonObject,
        atomic_write_json,
        load_object,
        validate_payload_digest,
    )
    from sign_release import IDENTITY_RE, append_transparency_event
    from verify_release import verify_paths

UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REASON_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")


def _subject_digest(manifest: JsonObject) -> str:
    spec = manifest.get("spec")
    subject = spec.get("subject") if isinstance(spec, dict) else None
    digest = subject.get("digest") if isinstance(subject, dict) else None
    if not isinstance(digest, str):
        raise ValueError("release subject digest is missing")
    return digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--k4-approval", type=Path, required=True)
    parser.add_argument("--k5-approval", type=Path, required=True)
    parser.add_argument("--rollback-manifest", type=Path, required=True)
    parser.add_argument("--rollback-public-key", type=Path, required=True)
    parser.add_argument("--rollback-key-id", required=True)
    parser.add_argument("--rollback-k4-approval", type=Path, required=True)
    parser.add_argument("--rollback-k5-approval", type=Path, required=True)
    parser.add_argument("--transparency-log", type=Path, required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--revoker-identity", required=True)
    parser.add_argument("--rollback-approver-identity", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not UTC_RE.fullmatch(args.created_at) or not REASON_RE.fullmatch(args.reason_code):
            raise ValueError("created-at or reason-code is invalid")
        if not IDENTITY_RE.fullmatch(args.revoker_identity) or not IDENTITY_RE.fullmatch(
            args.rollback_approver_identity
        ):
            raise ValueError("revoker or rollback approver identity is invalid")
        if args.revoker_identity == args.rollback_approver_identity:
            raise ValueError("revocation and rollback selection require independent identities")

        manifest = load_object(args.manifest)
        rollback_manifest = load_object(args.rollback_manifest)
        verify_paths(
            manifest,
            args.public_key,
            args.key_id,
            args.k4_approval,
            args.k5_approval,
            args.transparency_log,
        )
        verify_paths(
            rollback_manifest,
            args.rollback_public_key,
            args.rollback_key_id,
            args.rollback_k4_approval,
            args.rollback_k5_approval,
            args.transparency_log,
        )
        release_digest = validate_payload_digest(manifest)
        rollback_digest = validate_payload_digest(rollback_manifest)
        if release_digest == rollback_digest:
            raise ValueError("rollback must select a different previously signed release")

        append_transparency_event(
            args.transparency_log,
            event="release-revoked",
            release_payload_digest=release_digest,
            subject_digest=_subject_digest(manifest),
            actor_identity=args.revoker_identity,
            recorded_at=args.created_at,
            reason_code=args.reason_code,
        )
        append_transparency_event(
            args.transparency_log,
            event="rollback-selected",
            release_payload_digest=rollback_digest,
            subject_digest=_subject_digest(rollback_manifest),
            related_release_payload_digest=release_digest,
            actor_identity=args.rollback_approver_identity,
            recorded_at=args.created_at,
            reason_code=args.reason_code,
        )
        drill = {
            "schema_version": "mindclade.release-transition/v1",
            "kind": "RevocationRollbackDrill",
            "source_only": True,
            "connected_execution": False,
            "revoked_release_payload_digest": release_digest,
            "rollback_release_payload_digest": rollback_digest,
            "reason_code": args.reason_code,
            "revoker_identity": args.revoker_identity,
            "rollback_approver_identity": args.rollback_approver_identity,
            "created_at": args.created_at,
        }
        atomic_write_json(args.output, drill)
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"revocation/rollback drill failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
