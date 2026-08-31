from __future__ import annotations

from artifact.v1.artifact_reference_pb2 import ArtifactRef as ArtifactRef
from artifact.v1.evidence_reference_pb2 import EvidenceRef as EvidenceRef

from .digest import ArtifactDigest


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
