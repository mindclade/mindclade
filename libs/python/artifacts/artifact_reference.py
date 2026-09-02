from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema.exceptions import ValidationError
from mindclade.artifact.v1.artifact_reference_pb2 import ArtifactRef as ArtifactRef
from mindclade.artifact.v1.evidence_reference_pb2 import EvidenceRef as EvidenceRef
from mindclade.schema.v1.bindings import (
    ArtifactManifest as ArtifactManifest,
    decode_artifact_manifest,
)

from artifacts.digest import ArtifactDigest


def _digest_value(value: ArtifactDigest | str) -> str:
    return ArtifactDigest(value).value if isinstance(value, str) else value.value


def make_artifact_ref(
    *,
    digest: ArtifactDigest | str,
    media_type: str,
    size_bytes: int,
    artifact_kind: str,
    schema_id: str = "",
    integrity_digest: ArtifactDigest | str | None = None,
    uri: str = "",
    schema_version: str = "",
) -> ArtifactRef:
    """Build the authoritative generated artifact reference with local validation."""
    if not media_type:
        raise ValueError("media_type required")
    if isinstance(size_bytes, bool) or size_bytes < 0:
        raise ValueError("size_bytes must be non-negative")
    if not artifact_kind:
        raise ValueError("artifact_kind required")
    return ArtifactRef(
        digest=_digest_value(digest),
        media_type=media_type,
        size_bytes=size_bytes,
        artifact_kind=artifact_kind,
        schema_id=schema_id,
        integrity_digest=("" if integrity_digest is None else _digest_value(integrity_digest)),
        uri=uri,
        schema_version=schema_version,
    )


def make_evidence_ref(
    *,
    digest: ArtifactDigest | str,
    subject_digest: ArtifactDigest | str,
    evidence_kind: str,
    policy_digest: ArtifactDigest | str,
) -> EvidenceRef:
    """Build the authoritative generated evidence reference with digest validation."""
    if not evidence_kind:
        raise ValueError("evidence_kind required")
    return EvidenceRef(
        digest=_digest_value(digest),
        subject_digest=_digest_value(subject_digest),
        evidence_kind=evidence_kind,
        policy_digest=_digest_value(policy_digest),
    )


def validate_artifact_manifest(document: object) -> ArtifactManifest:
    """Validate and narrow an artifact manifest using the generated schema binding.

    The JSON Schema catalog remains the sole authority for the document shape;
    this library only provides the stable artifact-facing entry point.
    """
    return decode_artifact_manifest(document)


def _schema_binding_test() -> None:
    """Exercise the consumer boundary when this module is used as a Bazel test."""
    document: dict[str, Any] = {
        "schema_version": "mindclade.artifact-manifest/v1",
        "kind": "ArtifactManifest",
        "metadata": {
            "uid": "artifact-1",
            "created_at": "2026-08-30T00:00:00Z",
            "owner": "data-platform",
        },
        "spec": {
            "artifact": {
                "digest": "sha256:" + "a" * 64,
                "media_type": "application/json",
                "size_bytes": 1,
                "kind": "fixture",
            }
        },
        "lineage": [],
        "integrity": {
            "payload_digest": "sha256:" + "b" * 64,
            "signatures": [],
        },
    }
    manifest = validate_artifact_manifest(document)
    assert manifest["spec"]["artifact"]["kind"] == "fixture"

    invalid = deepcopy(document)
    del invalid["spec"]["artifact"]["digest"]
    try:
        validate_artifact_manifest(invalid)
    except ValidationError:
        return
    raise AssertionError("artifact manifest without a digest unexpectedly validated")


if __name__ == "__main__":
    _schema_binding_test()
