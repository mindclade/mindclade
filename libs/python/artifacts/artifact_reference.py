from dataclasses import dataclass

from .digest import ArtifactDigest


@dataclass(frozen=True)
class ArtifactRef:
    digest: ArtifactDigest
    media_type: str
    size_bytes: int
    kind: str


@dataclass(frozen=True)
class EvidenceRef:
    artifact: ArtifactRef
    evidence_type: str
    subject_digest: ArtifactDigest
