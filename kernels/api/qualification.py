"""Immutable qualification and promotion identities."""

from __future__ import annotations

from dataclasses import dataclass

from .environment import _validate_digest
from .errors import KernelContractError
from .output import ContractModel, _nonempty


@dataclass(frozen=True, slots=True)
class QualifiedCapability(ContractModel):
    operation: str
    operation_version: int
    implementation: str
    implementation_version: int
    workload_digest: str
    schedule_digest: str
    numerical_envelope_digest: str
    compile_environment_digest: str
    runtime_compatibility_digest: str
    forward_artifact_digest: str
    backward_artifact_digest: str | None
    qualification_release_digest: str
    status: str
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.operation, "qualified operation")
        _nonempty(self.implementation, "qualified implementation")
        if self.version != 1:
            raise KernelContractError(f"unsupported QualifiedCapability version: {self.version}")
        if self.operation_version < 1 or self.implementation_version < 1:
            raise KernelContractError("qualified operation and implementation versions must be positive")
        for label in (
            "workload_digest",
            "schedule_digest",
            "numerical_envelope_digest",
            "compile_environment_digest",
            "runtime_compatibility_digest",
            "forward_artifact_digest",
            "qualification_release_digest",
        ):
            _validate_digest(getattr(self, label), label)
        if self.backward_artifact_digest is not None:
            _validate_digest(self.backward_artifact_digest, "backward_artifact_digest")
        if self.status not in {
            "candidate",
            "compiled",
            "benchmarked",
            "qualified",
            "promoted",
            "superseded",
            "revoked",
        }:
            raise KernelContractError(f"unsupported qualification status: {self.status}")

    def validate_training_atomicity(self, *, autograd_required: bool) -> None:
        if autograd_required and self.backward_artifact_digest is None:
            raise KernelContractError(
                "AutogradPolicy.REQUIRED capability requires an atomically qualified backward artifact"
            )
