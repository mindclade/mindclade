#!/usr/bin/env python3.12
"""Build a deterministic, unsigned Wave 1 release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RESOURCE_RE = re.compile(r"^[a-z][a-z0-9_-]{2,127}$")
type JsonScalar = bool | int | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _narrow_json(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        raise ValueError("floating-point JSON is not canonical")
    if isinstance(value, list):
        values = cast(list[object], value)
        return [_narrow_json(item) for item in values]
    if isinstance(value, dict):
        values = cast(dict[object, object], value)
        if not all(isinstance(key, str) for key in values):
            raise ValueError("JSON object contains a non-string key")
        return {cast(str, key): _narrow_json(item) for key, item in values.items()}
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def load_json(path: Path) -> JsonValue:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"input must be a regular file: {path}")
    with path.open("r", encoding="utf-8") as stream:
        return _narrow_json(json.load(stream, object_pairs_hook=_reject_duplicate_pairs))


def load_object(path: Path) -> JsonObject:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError("input JSON must be an object")
    return value


def _validate_canonical_value(value: JsonValue, location: str = "$") -> None:
    if isinstance(value, float):
        raise ValueError(f"floating-point JSON is not canonical at {location}")
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical_value(item, f"{location}[{index}]")
        return
    for key, item in value.items():
        _validate_canonical_value(item, f"{location}.{key}")


def canonical_json(value: JsonValue) -> bytes:
    _validate_canonical_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def validate_digest(value: str, field: str) -> str:
    if not DIGEST_RE.fullmatch(value):
        raise ValueError(f"{field} must be sha256:<64 lowercase hex>")
    return value


def unsigned_payload(manifest: Mapping[str, JsonValue]) -> JsonObject:
    payload = dict(manifest)
    payload.pop("integrity", None)
    return payload


def validate_payload_digest(manifest: Mapping[str, JsonValue]) -> str:
    integrity = manifest.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("manifest integrity must be an object")
    observed = integrity.get("payload_digest")
    if not isinstance(observed, str):
        raise ValueError("manifest payload_digest is missing")
    expected = sha256_digest(canonical_json(unsigned_payload(manifest)))
    if observed != expected:
        raise ValueError("manifest payload_digest does not match canonical unsigned payload")
    return expected


def atomic_write_json(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except BaseException:
        with suppress(FileNotFoundError):
            Path(temporary).unlink()
        raise


def _named_digest(raw: str, field: str) -> dict[str, str]:
    name, separator, digest = raw.partition("=")
    if not separator or not RESOURCE_RE.fullmatch(name):
        raise ValueError(f"{field} must be name=sha256:<64 lowercase hex>")
    return {"name": name, "digest": validate_digest(digest, field)}


def _approval_ref(raw: str) -> dict[str, str]:
    gate, separator, digest = raw.partition("=")
    if not separator or gate not in {"K4", "K5"}:
        raise ValueError("approval must be K4=sha256:<64 lowercase hex> or K5=...")
    return {"gate": gate, "record_digest": validate_digest(digest, "approval")}


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    if not RESOURCE_RE.fullmatch(args.release_id):
        raise ValueError("release-id must be a lowercase opaque resource identifier")
    if not RESOURCE_RE.fullmatch(args.owner):
        raise ValueError("owner must be a lowercase owner identifier")
    if not GIT_SHA_RE.fullmatch(args.source_revision):
        raise ValueError("source-revision must be one full lowercase Git SHA")
    if not UTC_RE.fullmatch(args.created_at):
        raise ValueError("created-at must be a whole-second UTC timestamp")
    if not args.build_target.startswith("//"):
        raise ValueError("build-target must be an absolute Bazel label")
    for field in ("lockfile", "sbom", "provenance", "compatibility", "evidence"):
        if not getattr(args, field):
            raise ValueError(f"at least one {field} reference is required")

    lockfile_digests = [_named_digest(value, "lockfile") for value in args.lockfile]
    lockfile_names = [item["name"] for item in lockfile_digests]
    if len(lockfile_names) != len(set(lockfile_names)):
        raise ValueError("lockfile names must be unique")

    approval_refs = [_approval_ref(value) for value in args.approval]
    approval_gates = [item["gate"] for item in approval_refs]
    if sorted(approval_gates) != ["K4", "K5"]:
        raise ValueError("exactly one K4 and one K5 approval reference are required")

    manifest: dict[str, Any] = {
        "schema_version": "mindclade.release-manifest/v1",
        "kind": "ReleaseManifest",
        "metadata": {
            "uid": args.release_id,
            "created_at": args.created_at,
            "owner": args.owner,
        },
        "spec": {
            "subject": {
                "type": args.subject_type,
                "digest": validate_digest(args.subject_digest, "subject-digest"),
            },
            "source": {
                "repository": "github.com/mindclade/mindclade",
                "revision": args.source_revision,
            },
            "build_target": args.build_target,
            "toolchain_digest": validate_digest(args.toolchain_digest, "toolchain-digest"),
            "lockfile_digests": sorted(lockfile_digests, key=lambda item: item["name"]),
            "sbom_refs": sorted(validate_digest(value, "sbom") for value in args.sbom),
            "provenance_refs": sorted(
                validate_digest(value, "provenance") for value in args.provenance
            ),
            "compatibility_refs": sorted(
                validate_digest(value, "compatibility") for value in args.compatibility
            ),
            "qualification": {
                "policy_digest": validate_digest(args.qualification_policy, "qualification-policy"),
                "evidence_refs": sorted(
                    validate_digest(value, "evidence") for value in args.evidence
                ),
                "approval_refs": sorted(approval_refs, key=lambda item: item["gate"]),
            },
            "environment_constraints": sorted(set(args.environment_constraint)),
        },
    }
    manifest["integrity"] = {
        "payload_digest": sha256_digest(canonical_json(unsigned_payload(manifest))),
        "signatures": [],
    }
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--release-id", required=True)
    result.add_argument("--owner", required=True)
    result.add_argument("--created-at", required=True)
    result.add_argument("--subject-type", required=True)
    result.add_argument("--subject-digest", required=True)
    result.add_argument("--source-revision", required=True)
    result.add_argument("--build-target", required=True)
    result.add_argument("--toolchain-digest", required=True)
    result.add_argument("--lockfile", action="append", default=[])
    result.add_argument("--sbom", action="append", default=[])
    result.add_argument("--provenance", action="append", default=[])
    result.add_argument("--compatibility", action="append", default=[])
    result.add_argument("--qualification-policy", required=True)
    result.add_argument("--evidence", action="append", default=[])
    result.add_argument("--approval", action="append", default=[])
    result.add_argument("--environment-constraint", action="append", default=[])
    result.add_argument("--output", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = build_manifest(args)
        atomic_write_json(args.output, manifest)
    except (OSError, ValueError) as error:
        raise SystemExit(f"release manifest build failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
