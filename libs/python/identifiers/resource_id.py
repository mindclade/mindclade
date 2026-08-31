from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IdentifierKind(StrEnum):
    TENANT = "tenant"
    PROJECT = "project"
    OPERATION = "operation"
    JOB = "job"
    RUN = "run"
    ATTEMPT = "attempt"


@dataclass(frozen=True)
class Identifier:
    kind: IdentifierKind | str
    value: str

    def __post_init__(self) -> None:
        kind = str(self.kind)
        if not kind or not self.value.startswith(kind + "_"):
            raise ValueError("invalid identifier")

    @classmethod
    def from_proto(cls, kind: IdentifierKind | str, value: str) -> Identifier:
        """Validate an opaque identifier scalar read from a generated message."""
        return cls(kind, value)

    def to_proto(self) -> str:
        """Return the scalar representation used by generated Protobuf messages."""
        return self.value


@dataclass(frozen=True)
class ResourceVersion:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or self.value < 0:
            raise ValueError("resource version must be a non-negative integer")

    @classmethod
    def from_proto(cls, value: int) -> ResourceVersion:
        return cls(value)

    def to_proto(self) -> int:
        return self.value


@dataclass(frozen=True)
class LeaseEpoch:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or self.value < 0:
            raise ValueError("lease epoch must be a non-negative integer")

    @classmethod
    def from_proto(cls, value: int) -> LeaseEpoch:
        return cls(value)

    def to_proto(self) -> int:
        return self.value
