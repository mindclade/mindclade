from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from kernels.native.tilelang.swizzle import (
    CtaRasterPolicy,
    OperandRole,
    RasterOrder,
    SharedLayoutKind,
    SharedLayoutPolicy,
    SwizzlePolicyError,
    annotate_shared_layouts,
    apply_cta_raster,
    gemm_layout_policy,
    require_safe_swizzled_consumer,
)
from kernels.native.tilelang.targets import PORTABLE_CUDA, SM90A, SM100A


@dataclass
class FakeLayout:
    calls: list[tuple[str, object, dict[str, object]]] = field(default_factory=list)

    def __getattr__(self, name: str):
        def invoke(buffer: object, **kwargs: object) -> tuple[str, object]:
            self.calls.append((name, buffer, kwargs))
            return name, buffer
        return invoke


@dataclass
class FakeLanguage:
    annotations: list[dict[object, object]] = field(default_factory=list)
    raster: list[tuple[int, str]] = field(default_factory=list)

    def annotate_layout(self, value: dict[object, object]) -> None:
        self.annotations.append(value)

    def use_swizzle(self, *, panel_size: int, order: str) -> None:
        self.raster.append((panel_size, order))


def test_gemm_layout_is_consumer_and_architecture_driven() -> None:
    assert gemm_layout_policy(PORTABLE_CUDA, role=OperandRole.GEMM_A, k_major=True).kind is SharedLayoutKind.AUTO
    assert gemm_layout_policy(SM90A, role=OperandRole.GEMM_A, k_major=True).kind is SharedLayoutKind.WGMMA
    assert gemm_layout_policy(SM100A, role=OperandRole.GEMM_B, k_major=False).kind is SharedLayoutKind.TCGEN05


def test_annotation_and_cta_raster_emit_only_declared_policy() -> None:
    language = FakeLanguage()
    layout = FakeLayout()
    buffer = object()
    policy = SharedLayoutPolicy(kind=SharedLayoutKind.WGMMA, used_by_tma=True)
    annotate_shared_layouts({buffer: policy}, SM90A, language=language, layout_module=layout)
    apply_cta_raster(CtaRasterPolicy(8, RasterOrder.COL), language=language)
    assert layout.calls[0][0] == "make_wgmma_swizzled_layout"
    assert language.raster == [(8, "col")]
    assert policy.required_alignment(SM90A) == 1024


def test_illegal_layouts_and_consumers_fail_closed() -> None:
    with pytest.raises(SwizzlePolicyError, match="WGMMA layout is not legal"):
        SharedLayoutPolicy(kind=SharedLayoutKind.WGMMA).validate(PORTABLE_CUDA)
    for consumer in ("all_of", "any_of", "cross_width_view"):
        with pytest.raises(SwizzlePolicyError, match="prohibited"):
            require_safe_swizzled_consumer(consumer)
