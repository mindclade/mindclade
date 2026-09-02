"""First-party TileLang programs for Pairformer triangle attention.

The public tensors are logically ``[..., N, N, H, D]``.  The native launcher
flattens the leading pair-stack dimensions into ``batch`` before invoking these
static programs.  Forward uses row-wise online normalization and never stores
an ``N x N`` probability matrix.  Backward deterministically recomputes the
probabilities from the saved FP32 LSE and is split into private programs so no
gradient requires atomics.

Builders are build-plane only.  Importing this module does not compile or
register a kernel.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TILELANG_VERSION = "0.1.13"
SUPPORTED_ARCHITECTURES = ("sm90a", "sm100a")
SUPPORTED_DTYPES = ("float16", "bfloat16")

TRIANGLE_ATTENTION_PROFILES: tuple[Mapping[str, object], ...] = (
    {
        "name": "b1_n32_h4_d32_fp16",
        "batch": 1,
        "n": 32,
        "heads": 4,
        "head_dim": 32,
        "dtype": "float16",
        "threads": 64,
    },
    {
        "name": "b1_n64_h8_d32_fp16",
        "batch": 1,
        "n": 64,
        "heads": 8,
        "head_dim": 32,
        "dtype": "float16",
        "threads": 128,
    },
    {
        "name": "b1_n128_h8_d64_bf16",
        "batch": 1,
        "n": 128,
        "heads": 8,
        "head_dim": 64,
        "dtype": "bfloat16",
        "threads": 128,
    },
)


def _tilelang() -> tuple[Any, Any]:
    try:
        import tilelang
        from tilelang import language as T
    except ImportError as exc:  # pragma: no cover - exercised in build lane
        raise RuntimeError(
            "TileLang 0.1.13 is required in the hermetic native build lane"
        ) from exc
    if getattr(tilelang, "__version__", None) != TILELANG_VERSION:
        raise RuntimeError(
            f"expected TileLang {TILELANG_VERSION}, got "
            f"{getattr(tilelang, '__version__', 'unknown')}"
        )
    return tilelang, T


def _validate(
    *,
    target: str,
    architecture: str,
    dtype: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    threads: int,
) -> tuple[Any, str, int]:
    if target != "cuda":
        raise ValueError("triangle attention supports only the explicit cuda target")
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise ValueError(
            f"unsupported architecture {architecture!r}; expected sm90a or sm100a"
        )
    if dtype not in SUPPORTED_DTYPES:
        raise ValueError("production triangle attention supports float16 and bfloat16")
    if min(batch, n, heads, head_dim, threads) <= 0:
        raise ValueError("all static launch dimensions must be positive")
    if head_dim not in (32, 64):
        raise ValueError("head_dim must be 32 or 64")
    if n > 128:
        raise ValueError("the v1 capability envelope supports n <= 128")
    if threads not in (64, 128, 256):
        raise ValueError("threads must be 64, 128, or 256")
    _, T = _tilelang()
    target_arch = {"sm90a": "sm_90a", "sm100a": "sm_100a"}[architecture]
    padded_n = ((n + 31) // 32) * 32
    return T, target_arch, padded_n


def _logical_group(
    *,
    phase: str,
    logical_symbol: str,
    execution_order: tuple[str, ...],
    workspaces: tuple[str, ...],
) -> dict[str, object]:
    return {
        "phase": phase,
        "logical_symbol": logical_symbol,
        "execution_order": execution_order,
        "workspaces": workspaces,
        "version": 1,
    }


def build_forward_program_group(**_: object) -> dict[str, object]:
    """Return deterministic logical FWD orchestration metadata."""

    return _logical_group(
        phase="forward",
        logical_symbol="mindclade_tilelang_triangle_attention_fwd_launch",
        execution_order=("forward",),
        workspaces=(),
    )


def build_backward_program_group(**_: object) -> dict[str, object]:
    """Return deterministic logical BWD orchestration metadata."""

    return _logical_group(
        phase="backward",
        logical_symbol="mindclade_tilelang_triangle_attention_bwd_launch",
        execution_order=("delta", "dbias", "dk", "dq", "dv"),
        workspaces=("delta",),
    )


def build_forward_program(
    *,
    target: str,
    architecture: str,
    dtype: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    threads: int = 128,
    **_: object,
) -> Any:
    """Build online-softmax FWD returning output and padded FP32 LSE."""

    T, target_arch, padded_n = _validate(
        target=target,
        architecture=architecture,
        dtype=dtype,
        batch=batch,
        n=n,
        heads=heads,
        head_dim=head_dim,
        threads=threads,
    )
    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[6, 7], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_attention_forward_raw(
        q: T.Tensor((batch, n, heads, head_dim), dtype),
        k: T.Tensor((batch, n, heads, head_dim), dtype),
        v: T.Tensor((batch, n, heads, head_dim), dtype),
        bias: T.Tensor((batch, heads, n, n), dtype),
        mask: T.Tensor((batch, n, n), "bool"),
        scale: T.float32,
        output: T.Tensor((batch, n, heads, head_dim), dtype),
        lse: T.Tensor((batch, heads, padded_n), "float32"),
    ):
        with T.Kernel(batch * heads * padded_n, threads=threads) as block:
            query_index = block % padded_n
            head = (block // padded_n) % heads
            batch_index = block // (padded_n * heads)

            if query_index < n:
                for out_d in T.Parallel(head_dim):
                    row_max = T.alloc_local((1,), "float32")
                    row_sum = T.alloc_local((1,), "float32")
                    numerator = T.alloc_local((1,), "float32")
                    has_source = T.alloc_local((1,), "int32")
                    row_max[0] = -T.infinity("float32")
                    row_sum[0] = 0.0
                    numerator[0] = 0.0
                    has_source[0] = 0

                    # One-pass online softmax.  Rescale both normalization and
                    # value state whenever the running maximum changes.  This
                    # retains fixed reduction order without materializing
                    # logits/probabilities or making a second key pass.
                    for key_index in T.serial(n):
                        score = T.alloc_local((1,), "float32")
                        score[0] = 0.0
                        for reduce_d in T.serial(head_dim):
                            score[0] += T.Cast("float32", q[batch_index, query_index, head, reduce_d]) * T.Cast(
                                "float32", k[batch_index, key_index, head, reduce_d]
                            )
                        score[0] = score[0] * scale
                        score[0] += T.Cast(
                            "float32", bias[batch_index, head, query_index, key_index]
                        )
                        if mask[batch_index, query_index, key_index]:
                            if has_source[0] == 0:
                                row_max[0] = score[0]
                                row_sum[0] = 1.0
                                numerator[0] = T.Cast(
                                    "float32", v[batch_index, key_index, head, out_d]
                                )
                                has_source[0] = 1
                            else:
                                next_max = T.max(row_max[0], score[0])
                                old_scale = T.exp(row_max[0] - next_max)
                                new_scale = T.exp(score[0] - next_max)
                                row_sum[0] = row_sum[0] * old_scale + new_scale
                                numerator[0] = (
                                    numerator[0] * old_scale
                                    + new_scale
                                    * T.Cast(
                                        "float32",
                                        v[batch_index, key_index, head, out_d],
                                    )
                                )
                                row_max[0] = next_max

                    if has_source[0] != 0:
                        output[batch_index, query_index, head, out_d] = T.Cast(
                            dtype, numerator[0] / row_sum[0]
                        )
                    else:
                        output[batch_index, query_index, head, out_d] = T.Cast(dtype, 0.0)
                    if out_d == 0:
                        if has_source[0] != 0:
                            lse[batch_index, head, query_index] = row_max[0] + T.log(row_sum[0])
                        else:
                            lse[batch_index, head, query_index] = -T.infinity("float32")
            else:
                lse[batch_index, head, query_index] = -T.infinity("float32")

    return mindclade_tilelang_triangle_attention_forward_raw.with_attr(
        {
            "target": target_arch,
            "global_symbol": "mindclade_tilelang_triangle_attention_forward_raw",
        }
    )


def build_delta(
    *,
    target: str,
    architecture: str,
    dtype: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    threads: int = 128,
    **_: object,
) -> Any:
    """Build the deterministic ``sum(dO * O)`` workspace producer."""

    T, target_arch, padded_n = _validate(
        target=target,
        architecture=architecture,
        dtype=dtype,
        batch=batch,
        n=n,
        heads=heads,
        head_dim=head_dim,
        threads=threads,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[2], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_attention_delta_raw(
        grad_output: T.Tensor((batch, n, heads, head_dim), dtype),
        output: T.Tensor((batch, n, heads, head_dim), dtype),
        delta: T.Tensor((batch, heads, padded_n), "float32"),
    ):
        with T.Kernel(batch * heads * padded_n, threads=threads) as block:
            query_index = block % padded_n
            head = (block // padded_n) % heads
            batch_index = block // (padded_n * heads)
            value = T.alloc_local((1,), "float32")
            value[0] = 0.0
            if query_index < n:
                for d in T.serial(head_dim):
                    value[0] += T.Cast(
                        "float32", grad_output[batch_index, query_index, head, d]
                    ) * T.Cast("float32", output[batch_index, query_index, head, d])
            delta[batch_index, head, query_index] = value[0]

    return mindclade_tilelang_triangle_attention_delta_raw.with_attr(
        {
            "target": target_arch,
            "global_symbol": "mindclade_tilelang_triangle_attention_delta_raw",
        }
    )


def build_dq(
    *,
    target: str,
    architecture: str,
    dtype: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    threads: int = 128,
    **_: object,
) -> Any:
    """Build dQ with probability recomputation from saved LSE."""

    T, target_arch, padded_n = _validate(
        target=target,
        architecture=architecture,
        dtype=dtype,
        batch=batch,
        n=n,
        heads=heads,
        head_dim=head_dim,
        threads=threads,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[9], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_attention_dq_raw(
        grad_output: T.Tensor((batch, n, heads, head_dim), dtype),
        q: T.Tensor((batch, n, heads, head_dim), dtype),
        k: T.Tensor((batch, n, heads, head_dim), dtype),
        v: T.Tensor((batch, n, heads, head_dim), dtype),
        bias: T.Tensor((batch, heads, n, n), dtype),
        mask: T.Tensor((batch, n, n), "bool"),
        scale: T.float32,
        lse: T.Tensor((batch, heads, padded_n), "float32"),
        delta: T.Tensor((batch, heads, padded_n), "float32"),
        grad_q: T.Tensor((batch, n, heads, head_dim), dtype),
    ):
        with T.Kernel(batch * n * heads * head_dim, threads=threads) as block:
            d = block % head_dim
            head = (block // head_dim) % heads
            query_index = (block // (head_dim * heads)) % n
            batch_index = block // (head_dim * heads * n)
            result = T.alloc_local((1,), "float32")
            result[0] = 0.0
            for key_index in T.serial(n):
                if mask[batch_index, query_index, key_index]:
                    score = T.alloc_local((1,), "float32")
                    grad_probability = T.alloc_local((1,), "float32")
                    score[0] = 0.0
                    grad_probability[0] = 0.0
                    for reduce_d in T.serial(head_dim):
                        score[0] += T.Cast("float32", q[batch_index, query_index, head, reduce_d]) * T.Cast(
                            "float32", k[batch_index, key_index, head, reduce_d]
                        )
                        grad_probability[0] += T.Cast(
                            "float32", grad_output[batch_index, query_index, head, reduce_d]
                        ) * T.Cast("float32", v[batch_index, key_index, head, reduce_d])
                    score[0] = score[0] * scale
                    score[0] += T.Cast(
                        "float32", bias[batch_index, head, query_index, key_index]
                    )
                    probability = T.exp(score[0] - lse[batch_index, head, query_index])
                    grad_score = probability * (
                        grad_probability[0] - delta[batch_index, head, query_index]
                    )
                    result[0] += grad_score * T.Cast(
                        "float32", k[batch_index, key_index, head, d]
                    ) * scale
            grad_q[batch_index, query_index, head, d] = T.Cast(dtype, result[0])

    return mindclade_tilelang_triangle_attention_dq_raw.with_attr(
        {
            "target": target_arch,
            "global_symbol": "mindclade_tilelang_triangle_attention_dq_raw",
        }
    )


def build_dk(
    *,
    target: str,
    architecture: str,
    dtype: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    threads: int = 128,
    **_: object,
) -> Any:
    """Build atomics-free dK using source-key ownership."""

    T, target_arch, padded_n = _validate(
        target=target,
        architecture=architecture,
        dtype=dtype,
        batch=batch,
        n=n,
        heads=heads,
        head_dim=head_dim,
        threads=threads,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[9], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_attention_dk_raw(
        grad_output: T.Tensor((batch, n, heads, head_dim), dtype),
        q: T.Tensor((batch, n, heads, head_dim), dtype),
        k: T.Tensor((batch, n, heads, head_dim), dtype),
        v: T.Tensor((batch, n, heads, head_dim), dtype),
        bias: T.Tensor((batch, heads, n, n), dtype),
        mask: T.Tensor((batch, n, n), "bool"),
        scale: T.float32,
        lse: T.Tensor((batch, heads, padded_n), "float32"),
        delta: T.Tensor((batch, heads, padded_n), "float32"),
        grad_k: T.Tensor((batch, n, heads, head_dim), dtype),
    ):
        with T.Kernel(batch * n * heads * head_dim, threads=threads) as block:
            d = block % head_dim
            head = (block // head_dim) % heads
            key_index = (block // (head_dim * heads)) % n
            batch_index = block // (head_dim * heads * n)
            result_k = T.alloc_local((1,), "float32")
            result_k[0] = 0.0
            for query_index in T.serial(n):
                if mask[batch_index, query_index, key_index]:
                    score = T.alloc_local((1,), "float32")
                    grad_probability = T.alloc_local((1,), "float32")
                    score[0] = 0.0
                    grad_probability[0] = 0.0
                    for reduce_d in T.serial(head_dim):
                        score[0] += T.Cast("float32", q[batch_index, query_index, head, reduce_d]) * T.Cast(
                            "float32", k[batch_index, key_index, head, reduce_d]
                        )
                        grad_probability[0] += T.Cast(
                            "float32", grad_output[batch_index, query_index, head, reduce_d]
                        ) * T.Cast("float32", v[batch_index, key_index, head, reduce_d])
                    score[0] = score[0] * scale
                    score[0] += T.Cast(
                        "float32", bias[batch_index, head, query_index, key_index]
                    )
                    probability = T.exp(score[0] - lse[batch_index, head, query_index])
                    grad_score = probability * (
                        grad_probability[0] - delta[batch_index, head, query_index]
                    )
                    result_k[0] += grad_score * T.Cast(
                        "float32", q[batch_index, query_index, head, d]
                    ) * scale
            grad_k[batch_index, key_index, head, d] = T.Cast(dtype, result_k[0])

    return mindclade_tilelang_triangle_attention_dk_raw.with_attr(
        {
            "target": target_arch,
            "global_symbol": "mindclade_tilelang_triangle_attention_dk_raw",
        }
    )


def build_dv(
    *, target: str, architecture: str, dtype: str, batch: int, n: int,
    heads: int, head_dim: int, threads: int = 128, **_: object,
) -> Any:
    """Build atomics-free dV using source-key ownership."""

    T, target_arch, padded_n = _validate(
        target=target, architecture=architecture, dtype=dtype, batch=batch,
        n=n, heads=heads, head_dim=head_dim, threads=threads,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[8], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_attention_dv_raw(
        grad_output: T.Tensor((batch, n, heads, head_dim), dtype),
        q: T.Tensor((batch, n, heads, head_dim), dtype),
        k: T.Tensor((batch, n, heads, head_dim), dtype),
        v: T.Tensor((batch, n, heads, head_dim), dtype),
        bias: T.Tensor((batch, heads, n, n), dtype),
        mask: T.Tensor((batch, n, n), "bool"),
        scale: T.float32,
        lse: T.Tensor((batch, heads, padded_n), "float32"),
        grad_v: T.Tensor((batch, n, heads, head_dim), dtype),
    ):
        with T.Kernel(batch * n * heads * head_dim, threads=threads) as block:
            d = block % head_dim
            head = (block // head_dim) % heads
            key_index = (block // (head_dim * heads)) % n
            batch_index = block // (head_dim * heads * n)
            result = T.alloc_local((1,), "float32")
            result[0] = 0.0
            for query_index in T.serial(n):
                if mask[batch_index, query_index, key_index]:
                    score = T.alloc_local((1,), "float32")
                    score[0] = 0.0
                    for reduce_d in T.serial(head_dim):
                        score[0] += T.Cast(
                            "float32", q[batch_index, query_index, head, reduce_d]
                        ) * T.Cast(
                            "float32", k[batch_index, key_index, head, reduce_d]
                        )
                    score[0] = score[0] * scale + T.Cast(
                        "float32", bias[batch_index, head, query_index, key_index]
                    )
                    probability = T.exp(
                        score[0] - lse[batch_index, head, query_index]
                    )
                    result[0] += probability * T.Cast(
                        "float32", grad_output[batch_index, query_index, head, d]
                    )
            grad_v[batch_index, key_index, head, d] = T.Cast(dtype, result[0])

    return mindclade_tilelang_triangle_attention_dv_raw.with_attr(
        {"target": target_arch, "global_symbol": "mindclade_tilelang_triangle_attention_dv_raw"}
    )


def build_dbias(
    *,
    target: str,
    architecture: str,
    dtype: str,
    batch: int,
    n: int,
    heads: int,
    head_dim: int,
    threads: int = 128,
    **_: object,
) -> Any:
    """Build dense dBias; facade code reduces normalized broadcast axes."""

    T, target_arch, padded_n = _validate(
        target=target,
        architecture=architecture,
        dtype=dtype,
        batch=batch,
        n=n,
        heads=heads,
        head_dim=head_dim,
        threads=threads,
    )

    tilelang = __import__("tilelang")

    @tilelang.jit(out_idx=[9], target=target_arch)
    @T.prim_func
    def mindclade_tilelang_triangle_attention_dbias_raw(
        grad_output: T.Tensor((batch, n, heads, head_dim), dtype),
        q: T.Tensor((batch, n, heads, head_dim), dtype),
        k: T.Tensor((batch, n, heads, head_dim), dtype),
        v: T.Tensor((batch, n, heads, head_dim), dtype),
        bias: T.Tensor((batch, heads, n, n), dtype),
        mask: T.Tensor((batch, n, n), "bool"),
        scale: T.float32,
        lse: T.Tensor((batch, heads, padded_n), "float32"),
        delta: T.Tensor((batch, heads, padded_n), "float32"),
        grad_bias: T.Tensor((batch, heads, n, n), dtype),
    ):
        with T.Kernel(batch * heads * n * n, threads=threads) as block:
            key_index = block % n
            query_index = (block // n) % n
            head = (block // (n * n)) % heads
            batch_index = block // (n * n * heads)
            grad_score = T.alloc_local((1,), "float32")
            grad_score[0] = 0.0
            if mask[batch_index, query_index, key_index]:
                score = T.alloc_local((1,), "float32")
                grad_probability = T.alloc_local((1,), "float32")
                score[0] = 0.0
                grad_probability[0] = 0.0
                for d in T.serial(head_dim):
                    score[0] += T.Cast("float32", q[batch_index, query_index, head, d]) * T.Cast(
                        "float32", k[batch_index, key_index, head, d]
                    )
                    grad_probability[0] += T.Cast(
                        "float32", grad_output[batch_index, query_index, head, d]
                    ) * T.Cast("float32", v[batch_index, key_index, head, d])
                score[0] = score[0] * scale
                score[0] += T.Cast(
                    "float32", bias[batch_index, head, query_index, key_index]
                )
                probability = T.exp(score[0] - lse[batch_index, head, query_index])
                grad_score[0] = probability * (
                    grad_probability[0] - delta[batch_index, head, query_index]
                )
            grad_bias[batch_index, head, query_index, key_index] = T.Cast(
                dtype, grad_score[0]
            )

    return mindclade_tilelang_triangle_attention_dbias_raw.with_attr(
        {
            "target": target_arch,
            "global_symbol": "mindclade_tilelang_triangle_attention_dbias_raw",
        }
    )


# Kept only for build-tool compatibility with pre-v3 callers.  Production
# registry generation points at build_forward/build_forward_program directly.
build_forward = build_forward_program_group
build_backward = build_backward_program_group
build_tilelang_program = build_forward_program
