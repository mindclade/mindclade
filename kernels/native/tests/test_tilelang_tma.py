from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field

import pytest

from kernels.native.tilelang.targets import PORTABLE_CUDA, SM90A, SM100A
from kernels.native.tilelang.tma import (
    BarrierPlan,
    ClusterPlan,
    CopyInstruction,
    TmaPolicyError,
    TransferPolicy,
    allocate_barriers,
    cluster_multicast_copy,
    cluster_remote_copy,
    gather4_load,
    managed_copy,
    scatter4_store,
    tma_load_and_wait,
)


@dataclass
class FakeLanguage:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(default_factory=list)

    def __getattr__(self, name: str):
        def invoke(*args: object, **kwargs: object):
            self.calls.append((name, args, kwargs))
            if name == "shuffle_elect":
                return nullcontext()
            if name == "tma_gather4_bytes":
                return 256
            return name
        return invoke


def test_managed_copy_forces_tma_or_portable_lane() -> None:
    language = FakeLanguage()
    managed_copy("src", "dst", target=SM90A, language=language)
    managed_copy("src", "dst", target=PORTABLE_CUDA, language=language)
    assert language.calls[0][2]["prefer_instruction"] == "tma"
    assert language.calls[0][2]["disable_tma"] is False
    assert language.calls[1][2]["prefer_instruction"] == "cp_async"
    assert language.calls[1][2]["disable_tma"] is True
    with pytest.raises(TmaPolicyError, match="not legal"):
        managed_copy(
            "src",
            "dst",
            target=PORTABLE_CUDA,
            policy=TransferPolicy(CopyInstruction.TMA, allow_fallback=False),
            language=language,
        )


def test_manual_load_has_complete_barrier_lifecycle() -> None:
    language = FakeLanguage()
    barrier = allocate_barriers(BarrierPlan(stages=2), language=language)
    tma_load_and_wait("src", "dst", barrier, target=SM90A, parity=0, language=language)
    names = [call[0] for call in language.calls]
    assert names == ["alloc_barrier", "tma_copy", "barrier_arrive", "mbarrier_wait_parity"]


def test_cluster_and_blackwell_specializations_are_gated() -> None:
    language = FakeLanguage()
    cluster = ClusterPlan(cluster_size=2, cluster_mask=0b11, dst_block=1)
    cluster_multicast_copy("src", "dst", target=SM90A, cluster=cluster, language=language)
    cluster_remote_copy("src", "dst", "bar", target=SM90A, cluster=cluster, language=language)
    gather4_load("src", "dst", 0, "rows", "bar", k_box=64, dtype="float16", target=SM100A, parity=0, language=language)
    scatter4_store("src", "dst", 0, "rows", target=SM100A, language=language)
    names = [call[0] for call in language.calls]
    assert names.count("copy_cluster") == 2
    assert "tma_gather4" in names
    assert "tma_scatter4" in names
    with pytest.raises(TmaPolicyError, match="gather4 requires SM100a"):
        gather4_load("src", "dst", 0, "rows", "bar", k_box=64, dtype="float16", target=SM90A, parity=0, language=language)


def test_cluster_masks_and_remote_fallbacks_fail_closed() -> None:
    with pytest.raises(TmaPolicyError, match="outside the cluster"):
        ClusterPlan(cluster_size=2, cluster_mask=0b100)
    with pytest.raises(TmaPolicyError, match="explicit fallback"):
        cluster_remote_copy(
            "src",
            "dst",
            "bar",
            target=PORTABLE_CUDA,
            cluster=ClusterPlan(cluster_size=2, cluster_mask=0b11, dst_block=1),
            language=FakeLanguage(),
        )
