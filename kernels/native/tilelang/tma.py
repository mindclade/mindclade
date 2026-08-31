"""Validated TileLang TMA, cluster-copy, and portable-copy emission helpers.

The helpers are build-time only. They do not inspect a runtime device and do
not accept arbitrary descriptor metadata from model requests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

from kernels.native.tilelang.targets import TargetContract, TargetInput, normalize_target

Fallback: TypeAlias = Callable[[], object]


class TmaPolicyError(ValueError):
    """Raised when a transfer cannot preserve its declared semantics."""


class CopyInstruction(StrEnum):
    AUTO = "auto"
    TMA = "tma"
    CP_ASYNC = "cp_async"
    SYNC = "sync"


class TransferDirection(StrEnum):
    LOAD = "global_to_shared"
    STORE = "shared_to_global"
    SHARED = "shared_to_shared"


class EvictionPolicy(StrEnum):
    NORMAL = "evict_normal"
    FIRST = "evict_first"
    LAST = "evict_last"


@dataclass(frozen=True, slots=True)
class TransferPolicy:
    instruction: CopyInstruction = CopyInstruction.AUTO
    direction: TransferDirection = TransferDirection.LOAD
    coalesced_width: int | None = None
    eviction: EvictionPolicy | None = None
    allow_fallback: bool = True

    def __post_init__(self) -> None:
        if self.coalesced_width is not None:
            width = self.coalesced_width
            if width <= 0 or width & (width - 1):
                raise TmaPolicyError("coalesced_width must be a positive power of two")
        if self.instruction is CopyInstruction.CP_ASYNC and self.direction is not TransferDirection.LOAD:
            raise TmaPolicyError("cp_async is legal only for global-to-shared loads")


@dataclass(frozen=True, slots=True)
class BarrierPlan:
    arrive_count: int = 1
    stages: int = 1
    initial_parity: int = 0
    leader_scope_threads: int = 32

    def __post_init__(self) -> None:
        if self.arrive_count <= 0:
            raise TmaPolicyError("barrier arrive_count must be positive")
        if self.stages <= 0 or self.stages > 8:
            raise TmaPolicyError("barrier stages must be in [1, 8]")
        if self.initial_parity not in {0, 1}:
            raise TmaPolicyError("barrier parity must be 0 or 1")
        if self.leader_scope_threads <= 0 or self.leader_scope_threads % 32:
            raise TmaPolicyError("leader scope must be a positive multiple of 32 threads")


@dataclass(frozen=True, slots=True)
class ClusterPlan:
    cluster_size: int
    cluster_mask: int
    dst_block: int | None = None
    leader_scope_threads: int = 32

    def __post_init__(self) -> None:
        if self.cluster_size <= 0 or self.cluster_size > 16:
            raise TmaPolicyError("cluster_size must be in [1, 16]")
        legal_mask = (1 << self.cluster_size) - 1
        if self.cluster_mask <= 0 or self.cluster_mask & ~legal_mask:
            raise TmaPolicyError("cluster_mask addresses a CTA outside the cluster")
        if self.dst_block is not None and not 0 <= self.dst_block < self.cluster_size:
            raise TmaPolicyError("dst_block must address a CTA inside the cluster")
        if self.leader_scope_threads <= 0 or self.leader_scope_threads % 32:
            raise TmaPolicyError("leader scope must be a positive multiple of 32 threads")


def _language(language: Any | None) -> Any:
    if language is not None:
        return language
    import tilelang.language as tilelang_language

    return tilelang_language


def _copy_kwargs(policy: TransferPolicy) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if policy.coalesced_width is not None:
        kwargs["coalesced_width"] = policy.coalesced_width
    if policy.eviction is not None:
        kwargs["eviction_policy"] = policy.eviction.value
    return kwargs


def managed_copy(
    src: object,
    dst: object,
    *,
    target: TargetInput,
    policy: TransferPolicy = TransferPolicy(),
    language: Any | None = None,
) -> object:
    """Emit a completed copy, forcing TMA only when the target contract permits it."""

    contract = normalize_target(target)
    instruction = policy.instruction
    if instruction is CopyInstruction.AUTO:
        instruction = CopyInstruction.TMA if contract.managed_tma else (
            CopyInstruction.CP_ASYNC
            if policy.direction is TransferDirection.LOAD
            else CopyInstruction.SYNC
        )
    if instruction is CopyInstruction.TMA and not contract.managed_tma:
        if not policy.allow_fallback:
            raise TmaPolicyError(f"managed TMA is not legal for {contract.name}")
        instruction = (
            CopyInstruction.CP_ASYNC
            if policy.direction is TransferDirection.LOAD
            else CopyInstruction.SYNC
        )
    if instruction is CopyInstruction.CP_ASYNC and policy.direction is not TransferDirection.LOAD:
        raise TmaPolicyError("cp_async fallback cannot implement this transfer direction")

    kwargs = _copy_kwargs(policy)
    kwargs["disable_tma"] = instruction is not CopyInstruction.TMA
    kwargs["prefer_instruction"] = instruction.value
    return _language(language).copy(src, dst, **kwargs)


def allocate_barriers(
    plan: BarrierPlan,
    *,
    cluster: bool = False,
    language: Any | None = None,
) -> object:
    lang = _language(language)
    arrive_count: int | list[int] = (
        plan.arrive_count if plan.stages == 1 else [plan.arrive_count] * plan.stages
    )
    allocator = lang.alloc_cluster_barrier if cluster else lang.alloc_barrier
    return allocator(arrive_count)


def issue_tma_load(
    src: object,
    dst: object,
    barrier: object,
    *,
    target: TargetInput,
    leader_scope_threads: int = 32,
    cluster_mask: int | None = None,
    eviction: EvictionPolicy | None = None,
    language: Any | None = None,
) -> object:
    contract = normalize_target(target)
    if not contract.manual_tma:
        raise TmaPolicyError(f"manual TMA is not legal for {contract.name}")
    if cluster_mask is not None and not contract.cluster_tma:
        raise TmaPolicyError(f"cluster TMA is not legal for {contract.name}")
    return _language(language).tma_copy(
        src,
        dst,
        barrier=barrier,
        cluster_mask=cluster_mask,
        leader_scope_threads=leader_scope_threads,
        eviction_policy=None if eviction is None else eviction.value,
    )


def wait_tma_load(barrier: object, parity: object, *, language: Any | None = None) -> None:
    lang = _language(language)
    lang.barrier_arrive(barrier)
    lang.mbarrier_wait_parity(barrier, parity)


def tma_load_and_wait(
    src: object,
    dst: object,
    barrier: object,
    *,
    target: TargetInput,
    parity: object,
    fallback: Fallback | None = None,
    language: Any | None = None,
) -> object | None:
    contract = normalize_target(target)
    if not contract.manual_tma:
        if fallback is not None:
            return fallback()
        return managed_copy(src, dst, target=contract, language=language)
    result = issue_tma_load(src, dst, barrier, target=contract, language=language)
    wait_tma_load(barrier, parity, language=language)
    return result


def issue_tma_store(
    src: object,
    dst: object,
    *,
    target: TargetInput,
    language: Any | None = None,
) -> object:
    contract = normalize_target(target)
    if not contract.manual_tma:
        raise TmaPolicyError(f"manual TMA store is not legal for {contract.name}")
    return _language(language).tma_copy(src, dst)


def wait_tma_stores(
    count: int = 0,
    *,
    include_destination_writes: bool = True,
    language: Any | None = None,
) -> object:
    if count < 0:
        raise TmaPolicyError("TMA store wait count cannot be negative")
    return _language(language).tma_store_wait(count, read=not include_destination_writes)


def cluster_multicast_copy(
    src: object,
    dst: object,
    *,
    target: TargetInput,
    cluster: ClusterPlan,
    fallback: Fallback | None = None,
    language: Any | None = None,
) -> object:
    contract = normalize_target(target)
    if not contract.cluster_tma:
        if fallback is not None:
            return fallback()
        return managed_copy(src, dst, target=contract, language=language)
    return _language(language).copy_cluster(
        src,
        dst,
        cluster_mask=cluster.cluster_mask,
    )


def cluster_remote_copy(
    src: object,
    dst: object,
    remote_barrier: object,
    *,
    target: TargetInput,
    cluster: ClusterPlan,
    fallback: Fallback | None = None,
    language: Any | None = None,
) -> object:
    contract = normalize_target(target)
    if cluster.dst_block is None:
        raise TmaPolicyError("remote cluster copy requires dst_block")
    if not contract.cluster_tma:
        if fallback is None:
            raise TmaPolicyError("remote shared-memory semantics require an explicit fallback")
        return fallback()
    return _language(language).copy_cluster(
        src,
        dst,
        dst_block=cluster.dst_block,
        remote_barrier=remote_barrier,
    )


def gather4_load(
    src: object,
    dst: object,
    col: object,
    rows: object,
    barrier: object,
    *,
    k_box: int,
    dtype: str,
    target: TargetInput,
    parity: object,
    fallback: Fallback | None = None,
    language: Any | None = None,
) -> object | None:
    contract = normalize_target(target)
    if k_box <= 0:
        raise TmaPolicyError("gather4 k_box must be positive")
    if not contract.gather_scatter4:
        if fallback is None:
            raise TmaPolicyError("gather4 requires SM100a or an explicit fallback")
        return fallback()
    lang = _language(language)
    with lang.shuffle_elect(32):
        lang.mbarrier_expect_tx(barrier, lang.tma_gather4_bytes(k_box, dtype))
        result = lang.tma_gather4(src, dst, col, rows, barrier=barrier)
    lang.barrier_arrive(barrier)
    lang.mbarrier_wait_parity(barrier, parity)
    return result


def scatter4_store(
    src: object,
    dst: object,
    col: object,
    rows: object,
    *,
    target: TargetInput,
    fallback: Fallback | None = None,
    language: Any | None = None,
) -> object | None:
    contract = normalize_target(target)
    if not contract.gather_scatter4:
        if fallback is None:
            raise TmaPolicyError("scatter4 requires SM100a or an explicit fallback")
        return fallback()
    lang = _language(language)
    with lang.shuffle_elect(32):
        result = lang.tma_scatter4(src, dst, col, rows)
    lang.tma_store_arrive()
    lang.tma_store_wait(0, read=False)
    return result
