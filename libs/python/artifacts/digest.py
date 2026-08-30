import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactDigest:
    value: str

    def __post_init__(self):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.value) is None:
            raise ValueError("invalid digest")

    @classmethod
    def from_bytes(cls, value: bytes):
        return cls("sha256:" + hashlib.sha256(value).hexdigest())
