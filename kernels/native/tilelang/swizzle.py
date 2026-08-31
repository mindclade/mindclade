"""Consumer-driven shared-memory and CTA swizzle policies for TileLang."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from kernels.native.tilelang.targets import TargetContract, TargetInput, normalize_target


class SwizzlePolicyError(ValueError):
    """Raised when a swizzle is illegal for its target or consumer."""


class SharedLayoutKind(StrEnum):
    NONE = "none"
    AUTO = "auto"
    WGMMA = "wgmma"
    TCGEN05 = "tcgen05"
    FULL = "full"
    HALF = "half"
    QUARTER = "quarter"


class OperandRole(StrEnum):
    GENERIC = "generic"
    GEMM_A = "gemm_a"
    GEMM_B = "gemm_b"
    OUTPUT = "output"


class RasterOrder(StrEnum):
    ROW = "row"
    COL = "col"


_FORBIDDEN_SWIZZLED_CONSUMERS = frozenset({"all_of", "any_of", "cross_width_view"})


@dataclass(frozen=True, slots=True)
class SharedLayoutPolicy:
    kind: SharedLayoutKind = SharedLayoutKind.AUTO
    role: OperandRole = OperandRole.GENERIC
    k_major: bool = True
    continuity: int | None = None
    allow_pad: bool = True
    used_by_tma: bool = False

    def validate(self, target: TargetInput) -> TargetContract:
        contract = normalize_target(target)
        if self.continuity is not None and self.continuity not in {16, 32, 64, 128}:
            raise SwizzlePolicyError("continuity must be one of 16, 32, 64, or 128")
        if self.kind is SharedLayoutKind.WGMMA and not contract.wgmma_layout:
            raise SwizzlePolicyError(f"WGMMA layout is not legal for {contract.name}")
        if self.kind is SharedLayoutKind.TCGEN05 and not contract.tcgen05_layout:
            raise SwizzlePolicyError(f"TCGEN05 layout is not legal for {contract.name}")
        return contract

    def required_alignment(self, target: TargetInput) -> int:
        contract = self.validate(target)
        if self.kind is SharedLayoutKind.NONE or not self.used_by_tma:
            return 128
        return contract.swizzled_tma_alignment


@dataclass(frozen=True, slots=True)
class CtaRasterPolicy:
    panel_size: int = 0
    order: RasterOrder = RasterOrder.ROW

    def __post_init__(self) -> None:
        if self.panel_size < 0 or self.panel_size > 64:
            raise SwizzlePolicyError("CTA raster panel_size must be in [0, 64]")

    @property
    def enabled(self) -> bool:
        return self.panel_size > 0


def gemm_layout_policy(
    target: TargetInput,
    *,
    role: OperandRole,
    k_major: bool,
    continuity: int | None = None,
    used_by_tma: bool = True,
) -> SharedLayoutPolicy:
    contract = normalize_target(target)
    if contract.tcgen05_layout:
        kind = SharedLayoutKind.TCGEN05
    elif contract.wgmma_layout:
        kind = SharedLayoutKind.WGMMA
    else:
        kind = SharedLayoutKind.AUTO
    policy = SharedLayoutPolicy(
        kind=kind,
        role=role,
        k_major=k_major,
        continuity=continuity,
        used_by_tma=used_by_tma,
    )
    policy.validate(contract)
    return policy


def require_safe_swizzled_consumer(name: str) -> None:
    if name in _FORBIDDEN_SWIZZLED_CONSUMERS:
        raise SwizzlePolicyError(f"{name} is prohibited on swizzled shared buffers")


def _layout_module(layout_module: Any | None) -> Any:
    if layout_module is not None:
        return layout_module
    import tilelang.layout as tilelang_layout

    return tilelang_layout


def shared_layout_for(
    buffer: object,
    policy: SharedLayoutPolicy,
    target: TargetInput,
    *,
    layout_module: Any | None = None,
) -> object:
    policy.validate(target)
    layout = _layout_module(layout_module)
    if policy.kind is SharedLayoutKind.NONE:
        return layout.make_linear_layout(buffer)
    if policy.kind is SharedLayoutKind.AUTO:
        return layout.make_swizzled_layout(
            buffer,
            k_major=policy.k_major,
            allow_pad=policy.allow_pad,
        )
    if policy.kind is SharedLayoutKind.WGMMA:
        return layout.make_wgmma_swizzled_layout(
            buffer,
            continuity=policy.continuity,
            k_major=policy.k_major,
        )
    if policy.kind is SharedLayoutKind.TCGEN05:
        return layout.make_tcgen05mma_swizzled_layout(
            buffer,
            continuity=policy.continuity,
            k_major=policy.k_major,
        )
    constructor = {
        SharedLayoutKind.FULL: layout.make_full_bank_swizzled_layout,
        SharedLayoutKind.HALF: layout.make_half_bank_swizzled_layout,
        SharedLayoutKind.QUARTER: layout.make_quarter_bank_swizzled_layout,
    }[policy.kind]
    return constructor(buffer)


def annotate_shared_layouts(
    policies: Mapping[object, SharedLayoutPolicy],
    target: TargetInput,
    *,
    language: Any | None = None,
    layout_module: Any | None = None,
) -> None:
    if language is None:
        import tilelang.language as language
    annotations = {
        buffer: shared_layout_for(buffer, policy, target, layout_module=layout_module)
        for buffer, policy in policies.items()
    }
    if annotations:
        language.annotate_layout(annotations)


def apply_cta_raster(policy: CtaRasterPolicy, *, language: Any | None = None) -> None:
    if not policy.enabled:
        return
    if language is None:
        import tilelang.language as language
    language.use_swizzle(panel_size=policy.panel_size, order=policy.order.value)
