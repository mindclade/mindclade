#!/usr/bin/env python3.12
"""Resolve a fail-closed local qualification decision from exact evidence."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.qualification.verify_evidence import verify_record
from tools.release.build_release_manifest import (
    JsonObject,
    JsonValue,
    atomic_write_json,
    load_object,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    policy = load_object(args.policy)
    required_claims = policy.get("required_claims")
    if not isinstance(required_claims, list) or not all(
        isinstance(claim, str) for claim in required_claims
    ):
        raise SystemExit("qualification policy failed: required_claims must be an array")
    records = [load_object(path) for path in args.evidence]
    for record in records:
        try:
            verify_record(record)
        except (TypeError, ValueError) as error:
            raise SystemExit(f"qualification policy failed: invalid evidence: {error}") from error
    outcomes: dict[str, object] = {}
    for record in records:
        metadata = record.get("metadata")
        spec = record.get("spec")
        if not isinstance(metadata, dict) or not isinstance(spec, dict):
            raise SystemExit("qualification policy failed: evidence envelope is invalid")
        claim_id = metadata.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise SystemExit("qualification policy failed: evidence claim_id is missing")
        if claim_id in outcomes:
            raise SystemExit(
                f"qualification policy failed: duplicate evidence claim_id: {claim_id}"
            )
        outcomes[claim_id] = spec.get("outcome")
    required_values: list[str] = [claim for claim in required_claims if isinstance(claim, str)]
    required: list[str] = sorted(set(required_values))
    missing = [claim for claim in required if claim not in outcomes]
    failed = [claim for claim in required if outcomes.get(claim) == "FAIL"]
    indeterminate = [
        claim for claim in required if outcomes.get(claim) not in {"PASS", "NOT_APPLICABLE"}
    ]
    outcome = "FAIL" if failed else "INDETERMINATE" if missing or indeterminate else "PASS"
    required_json: list[JsonValue] = []
    required_json.extend(required)
    missing_json: list[JsonValue] = []
    missing_json.extend(missing)
    failed_json: list[JsonValue] = []
    failed_json.extend(failed)
    indeterminate_json: list[JsonValue] = []
    indeterminate_json.extend(indeterminate)
    decision: JsonObject = {
        "schema_version": "mindclade.qualification-decision/v1",
        "policy_id": policy.get("policy_id"),
        "outcome": outcome,
        "required_claims": required_json,
        "missing_claims": missing_json,
        "failed_claims": failed_json,
        "indeterminate_claims": indeterminate_json,
    }
    atomic_write_json(args.output, decision)
    return 0 if outcome == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
