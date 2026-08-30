#!/usr/bin/env python3.12
"""Collect one immutable, canonical local qualification evidence record."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.release.build_release_manifest import (
    JsonObject,
    JsonValue,
    atomic_write_json,
    canonical_json,
    load_json,
    sha256_digest,
    validate_digest,
)

OUTCOMES = {"PASS", "FAIL", "INDETERMINATE", "NOT_APPLICABLE", "WAIVED"}
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--requirement-id", action="append", default=[])
    parser.add_argument("--target", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--outcome", choices=sorted(OUTCOMES), required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--fixture-digest", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not UTC_RE.fullmatch(args.created_at):
        raise SystemExit("evidence collection failed: created-at must be whole-second UTC")
    environment = load_json(args.environment)
    result = load_json(args.result)
    requirement_ids = cast(list[str], args.requirement_id)
    fixture_digests = cast(list[str], args.fixture_digest)
    requirement_id_values: list[JsonValue] = []
    requirement_id_values.extend(sorted(set(requirement_ids)))
    fixture_digest_values: list[JsonValue] = []
    fixture_digest_values.extend(
        validate_digest(value, "fixture-digest") for value in fixture_digests
    )
    metadata: JsonObject = {
        "claim_id": cast(str, args.claim_id),
        "created_at": cast(str, args.created_at),
        "owner": cast(str, args.owner),
    }
    spec: JsonObject = {
        "requirement_ids": requirement_id_values,
        "target": cast(str, args.target),
        "source_revision": cast(str, args.source_revision),
        "environment": environment,
        "fixture_digests": fixture_digest_values,
        "procedure_result_digest": sha256_digest(canonical_json(result)),
        "outcome": cast(str, args.outcome),
    }
    record: JsonObject = {
        "schema_version": "mindclade.evidence-manifest/v1",
        "kind": "QualificationEvidence",
        "metadata": metadata,
        "spec": spec,
    }
    record["integrity"] = {"payload_digest": sha256_digest(canonical_json(record))}
    atomic_write_json(args.output, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
