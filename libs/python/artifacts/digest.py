from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactDigest:
    value: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.value) is None:
            raise ValueError("invalid digest")

    @classmethod
    def from_bytes(cls, value: bytes) -> ArtifactDigest:
        return cls("sha256:" + hashlib.sha256(value).hexdigest())

    @classmethod
    def from_proto(cls, value: str) -> ArtifactDigest:
        """Validate a digest scalar read from an authoritative generated message."""
        return cls(value)

    def to_proto(self) -> str:
        """Return the scalar representation used by generated Protobuf messages."""
        return self.value

    def __str__(self) -> str:
        return self.value
