"""Normalized device capabilities and exact compile/runtime identities."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import KernelContractError
from .output import ContractModel, _nonempty, _unique


@dataclass(frozen=True, slots=True)
class DeviceCapabilities(ContractModel):
    architecture: str
    sm_count: int
    warp_size: int
    shared_memory_per_block: int
    shared_memory_per_sm: int
    registers_per_sm: int
    max_threads_per_block: int
    supports_tensor_cores: bool
    supports_async_copy: bool
    supports_tma: bool
    supports_wgmma: bool
    supports_cluster_launch: bool
    supports_fp8: bool
    supports_mxfp8: bool
    supported_dtypes: tuple[str, ...]
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.architecture, "device architecture")
        if self.version != 1:
            raise KernelContractError(f"unsupported DeviceCapabilities version: {self.version}")
        for label in (
            "sm_count",
            "warp_size",
            "shared_memory_per_block",
            "shared_memory_per_sm",
            "registers_per_sm",
            "max_threads_per_block",
        ):
            if getattr(self, label) <= 0:
                raise KernelContractError(f"{label} must be positive")
        if not self.supported_dtypes:
            raise KernelContractError("supported_dtypes must not be empty")
        _unique(self.supported_dtypes, "supported_dtypes")
        if self.supports_wgmma and not self.supports_tensor_cores:
            raise KernelContractError("WGMMA capability requires tensor cores")
        if self.supports_mxfp8 and not self.supports_fp8:
            raise KernelContractError("MXFP8 capability requires FP8 capability")


@dataclass(frozen=True, slots=True)
class CompileEnvironment(ContractModel):
    target_architecture: str
    cuda_toolkit_digest: str
    tilelang_digest: str
    compiler_digest: str
    nix_closure_digest: str
    bazel_toolchain_digest: str
    compiler_flags: tuple[str, ...]
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.target_architecture, "compile target architecture")
        if self.version != 1:
            raise KernelContractError(f"unsupported CompileEnvironment version: {self.version}")
        for label in (
            "cuda_toolkit_digest",
            "tilelang_digest",
            "compiler_digest",
            "nix_closure_digest",
            "bazel_toolchain_digest",
        ):
            _validate_digest(getattr(self, label), label)
        _unique(self.compiler_flags, "compiler flags")


@dataclass(frozen=True, slots=True)
class RuntimeCompatibility(ContractModel):
    architecture: str
    required_features: tuple[str, ...]
    allowed_gpu_skus: tuple[str, ...]
    minimum_driver: str
    minimum_runtime: str
    shared_memory_required: int
    cluster_launch_required: bool
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.architecture, "runtime architecture")
        _nonempty(self.minimum_driver, "minimum driver")
        _nonempty(self.minimum_runtime, "minimum runtime")
        if self.version != 1:
            raise KernelContractError(f"unsupported RuntimeCompatibility version: {self.version}")
        if self.shared_memory_required < 0:
            raise KernelContractError("shared_memory_required must be non-negative")
        _unique(self.required_features, "required runtime features")
        _unique(self.allowed_gpu_skus, "allowed GPU SKUs")


def _validate_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise KernelContractError(f"{label} must be sha256:<64 lowercase hex>")
    suffix = value[7:]
    if any(character not in "0123456789abcdef" for character in suffix):
        raise KernelContractError(f"{label} must be sha256:<64 lowercase hex>")
