"""The SDK's single retry policy: one predicate, full jitter, one total budget.

Every retry decision in this package is taken here so that the synchronous
invoker, the asynchronous invoker, and the resumable watchers cannot drift
apart. Randomness is cryptographically seeded by default and injectable so
tests can script an exact schedule instead of sleeping on a real clock.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from .config import RetryPolicy

# 2**30 already exceeds every configurable maximum delay; clamping the exponent
# keeps a long-lived call from computing an unbounded float.
_MAX_EXPONENT = 30


class JitterSource(Protocol):
    """Randomness seam for retry backoff.

    ``uniform`` receives an inclusive upper bound and returns a value inside
    ``[0, upper_bound]``. A non-positive bound must return ``0.0``.
    """

    def uniform(self, upper_bound: float) -> float: ...


class SystemJitter:
    """Cryptographically seeded full jitter.

    ``secrets.SystemRandom`` is used deliberately: the process-wide ``random``
    module is seeded predictably and is shared with application code, so two
    clients recovering from the same outage could otherwise synchronize.
    """

    __slots__ = ("_random",)

    def __init__(self) -> None:
        self._random = secrets.SystemRandom()

    def uniform(self, upper_bound: float) -> float:
        if not upper_bound > 0:
            return 0.0
        return self._random.uniform(0.0, upper_bound)


class FixedJitter:
    """Deterministic jitter for tests, returning ``fraction * upper_bound``."""

    __slots__ = ("fraction",)

    def __init__(self, fraction: float = 1.0) -> None:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("jitter fraction must be in [0.0, 1.0]")
        self.fraction = float(fraction)

    def uniform(self, upper_bound: float) -> float:
        if not upper_bound > 0:
            return 0.0
        return upper_bound * self.fraction


DEFAULT_JITTER: JitterSource = SystemJitter()


def retry_delay(
    policy: RetryPolicy,
    failures: int,
    remaining: float,
    *,
    retry_after: float | None = None,
    jitter: JitterSource | None = None,
) -> float:
    """Return one bounded backoff delay for the ``failures``-th consecutive failure.

    Without a server hint the delay is full jitter over the exponential window
    ``[0, min(max_delay, remaining, base_delay * 2**(failures - 1))]``.

    With a ``retry-after-ms`` hint the hint becomes the delay's floor, clamped
    to ``max_delay`` (the contract's ``max_backoff``) and to the caller's
    remaining budget. Any headroom left between that floor and the exponential
    window is still jittered, so a server that hints one value to many clients
    does not resynchronize them.
    """

    remaining = max(0.0, remaining)
    window = min(policy.max_delay, remaining)
    if window <= 0:
        return 0.0
    exponent = min(max(0, failures - 1), _MAX_EXPONENT)
    ceiling = min(window, policy.base_delay * (2.0**exponent))
    floor = 0.0
    if retry_after is not None:
        floor = min(window, max(0.0, retry_after))
        ceiling = max(floor, ceiling)
    source = jitter or policy.jitter or DEFAULT_JITTER
    return floor + source.uniform(ceiling - floor)


def should_retry(
    *,
    retryable: bool,
    server_override: bool | None,
    attempt: int,
    attempts: int,
    remaining: float,
) -> bool:
    """Decide whether one more attempt is permitted for an already-safe call.

    Callers gate this behind their own per-RPC eligibility decision: a
    non-idempotent RPC never reaches here, so an ``x-mindclade-should-retry``
    trailer can never promote one. Within a safe call the trailer overrides the
    status predicate in both directions.
    """

    if attempt >= attempts or attempts <= 1:
        return False
    if remaining <= 0:
        return False
    if server_override is not None:
        return server_override
    return retryable
