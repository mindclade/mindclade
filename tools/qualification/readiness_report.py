#!/usr/bin/env python3.12
"""Map every authoritative integration-plan criterion to concrete evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

type JsonScalar = bool | float | int | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

CHECKBOX_RE = re.compile(r"^- \[(?P<checked>[ x])\] (?P<text>.+)$")
QUEUE_RE = re.compile(r"^(?P<number>[0-9]+)\. (?P<text>.+)$")


def canonical_json(value: JsonValue) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_object(path: Path) -> JsonObject:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{path} must contain one JSON object")
    return cast(JsonObject, value)


def plan_criteria(source: str) -> list[tuple[str, bool, str]]:
    criteria: list[tuple[str, bool, str]] = []
    current_id = ""
    current_checked = False
    current_text: list[str] = []
    section = ""

    def finish() -> None:
        nonlocal current_id, current_text
        if current_id:
            criteria.append((current_id, current_checked, " ".join(current_text)))
        current_id, current_text = "", []

    counters: dict[str, int] = {}
    for line in source.splitlines():
        if line.startswith("## "):
            finish()
            section = line.removeprefix("## ").strip().lower().replace(" ", "-")
            continue
        checkbox = CHECKBOX_RE.fullmatch(line)
        queued = QUEUE_RE.fullmatch(line) if section == "completion-work-queue" else None
        if checkbox is not None or queued is not None:
            finish()
            if checkbox is not None:
                counters[section] = counters.get(section, 0) + 1
                current_id = f"{section}-{counters[section]:02d}"
                current_checked = checkbox.group("checked") == "x"
                current_text = [checkbox.group("text")]
            else:
                assert queued is not None
                current_id = f"completion-work-queue-{int(queued.group('number')):02d}"
                current_checked = False
                current_text = [queued.group("text")]
            continue
        if current_id and (line.startswith("  ") or line.strip() == ""):
            if line.strip():
                current_text.append(line.strip())
            continue
        if current_id:
            finish()
    finish()
    return criteria


def evidence_mapping(text: str) -> tuple[list[JsonValue], str, str]:
    lowered = text.lower()
    if any(
        word in lowered
        for word in (
            "postgresql",
            "migration",
            "rls",
            "fenc",
            "lease",
            "reliability",
            "dlq",
            "outbox",
            "inbox",
        )
    ):
        return (
            [
                "//services/control_plane:control_plane_test",
                "//services/control_plane:jobs_server_test",
                "//services/control_plane/internal/platform/eventprojection:event_projection_test",
            ],
            "just integration-ci",
            "build/evidence/training-vertical-rehearsal.v1.json",
        )
    if any(word in lowered for word in ("sdk", "buf", "python", "rust", "typescript", "connect")):
        return (
            [
                "//internal/sdk/go/mindclade:mindclade_test",
                "//internal/sdk/python:tests",
                "//internal/sdk/rust:mindclade_internal_sdk_test",
                "//internal/sdk/typescript:tests",
            ],
            "just check",
            "build/evidence/training-vertical-rehearsal.v1.json",
        )
    if any(
        word in lowered
        for word in ("scientific", "sqp-001", "pa-01", "accelerator", "production qualification")
    ):
        return ([], "protected scientific/production qualification is not active", "none")
    if any(
        word in lowered
        for word in ("deploy", "gitops", "staging", "production promotion", "post-launch")
    ):
        return ([], "protected connected deployment gate is not active", "none")
    if any(word in lowered for word in ("path-policy", "activation", "blueprint")):
        return (
            ["//tools:repository_policies_test"],
            "just governance-ci",
            "build/evidence/repository_drift.v1.json",
        )
    return (
        ["//:all_contract_tests"],
        "just check",
        "build/evidence/training-vertical-rehearsal.v1.json",
    )


def criterion_status(text: str, checked: bool, rehearsal_passed: bool) -> str:
    lowered = text.lower()
    if checked:
        return "source-complete"
    if "ratif" in lowered or "stage 5" in lowered:
        return "blocked-protected-ratification"
    if any(
        word in lowered
        for word in ("deploy", "gitops", "staging", "production promotion", "post-launch")
    ):
        return "pending-connected-qualification"
    if any(word in lowered for word in ("scientific", "sqp-001", "pa-01", "accelerator")):
        return "pending-scientific-qualification"
    if rehearsal_passed and any(
        word in lowered
        for word in (
            "training",
            "postgresql",
            "migration",
            "grpc",
            "sdk",
            "event",
            "reliability",
            "fenc",
            "outbox",
            "inbox",
        )
    ):
        return "local-rehearsal-passed"
    return "candidate-evidence-incomplete"


def build_report(plan_path: Path, rehearsal_path: Path) -> JsonObject:
    plan_source = plan_path.read_text(encoding="utf-8")
    criteria = plan_criteria(plan_source)
    if len(criteria) < 30:
        raise ValueError(f"readiness plan extraction is incomplete: only {len(criteria)} criteria")
    rehearsal = load_object(rehearsal_path)
    rehearsal_passed = (
        rehearsal.get("schema_version") == "mindclade.training-vertical-rehearsal/v1"
        and rehearsal.get("status") == "passed"
        and isinstance(rehearsal.get("ratification"), dict)
        and cast(dict[str, JsonValue], rehearsal["ratification"]).get("authorized") is False
    )
    if not rehearsal_passed:
        raise ValueError("readiness report requires a passed, explicitly non-ratifying rehearsal")

    records: list[JsonValue] = []
    summary: dict[str, int] = {}
    for criterion_id, checked, text in criteria:
        targets, test, receipt = evidence_mapping(text)
        status = criterion_status(text, checked, rehearsal_passed)
        summary[status] = summary.get(status, 0) + 1
        records.append(
            {
                "bazel_targets": targets,
                "criterion": text,
                "criterion_id": criterion_id,
                "receipt": receipt,
                "status": status,
                "test": test,
            }
        )
    summary_json: JsonObject = {}
    for key in sorted(summary):
        summary_json[key] = summary[key]
    report: JsonObject = {
        "criteria": records,
        "plan_digest": digest_bytes(plan_source.encode()),
        "ratification_authorized": False,
        "rehearsal_receipt_digest": digest_bytes(rehearsal_path.read_bytes()),
        "schema_version": "mindclade.authoritative-integration-readiness/v1",
        "summary": summary_json,
    }
    report["report_digest"] = digest_bytes(canonical_json(report))
    return report


def atomic_write(path: Path, value: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(canonical_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--rehearsal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_report(
            cast(Path, args.plan),
            cast(Path, args.rehearsal),
        )
        atomic_write(cast(Path, args.output), report)
    except (OSError, ValueError) as error:
        raise SystemExit(f"readiness report failed: {error}") from error
    print(cast(Path, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
