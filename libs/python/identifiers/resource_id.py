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
    kind: str
    value: str

    def __post_init__(self):
        if not self.value.startswith(self.kind + "_"):
            raise ValueError("invalid identifier")


@dataclass(frozen=True)
class ResourceVersion:
    value: int


@dataclass(frozen=True)
class LeaseEpoch:
    value: int
