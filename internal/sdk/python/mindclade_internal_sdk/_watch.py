"""One resumable watcher shared by every server-streaming RPC in this SDK.

Operations, training runs, inference streams, and workflow runs used to carry
four near-identical reconnect loops that had quietly drifted apart: one dropped
the caller's lease token, one discarded the failure that ended the stream, two
ignored ``CallOptions.timeout``, and only two clamped a per-attempt deadline.
This module is the single implementation; each domain supplies a
:class:`WatchSpec` describing what its cursor is and what its own sequence and
identity checks are, and nothing else.

The invariants the loop guarantees, uniformly:

* **Reconnection stays inside the caller's deadline.** The total budget is
  fixed once, every attempt gets only what is left of it, and exhaustion raises
  the domain's timeout error rather than reconnecting once more.
* **Resumption uses the last acknowledged cursor.** The cursor advances only
  when ``accept`` has validated an item, so a reconnect never re-reads or skips.
* **Domain checks are preserved verbatim.** Sequence contiguity, identity
  matching, and terminal-state detection live in ``accept`` and run on every
  item on every attempt, including after a reconnect.
* **The real cause survives.** When the retry budget runs out, the error that
  actually ended the stream is what the caller sees.

The returned stream is both an iterator and a context manager, so
``with client.operations.watch(...) as events:`` releases the live gRPC call
deterministically at block exit instead of at the next garbage collection.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Any, Self, cast

from google.protobuf.message import Message

from ._invocation import AsyncInvoker, SyncInvoker
from ._retry import retry_delay
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import DeadlineExceededError, MindcladeError

# A gRPC deadline is also a liveness bound: no single watch attempt is allowed
# to sit on one connection longer than this, even when the caller's total watch
# budget is hours.
MAX_WATCH_ATTEMPT_SECONDS = 300.0

# The longest total budget a watch may be given, mirroring the bound the
# workflow watcher already enforced.
MAX_WATCH_BUDGET_SECONDS = 86_400.0

type Accepted[ItemT, CursorT] = tuple[ItemT, CursorT, bool]


@dataclass(frozen=True, slots=True)
class WatchSpec[ItemT, CursorT]:
    """Everything one domain's resumable stream needs that is not shared."""

    method: str
    """Fully-qualified gRPC method of the server-streaming RPC."""
    build_request: Callable[[CursorT, float], Message]
    """Build the request for one attempt from the cursor and remaining budget."""
    accept: Callable[[Message, CursorT], Accepted[ItemT, CursorT]]
    """Validate one response, returning ``(item, next_cursor, terminal)``."""
    closed_error: Callable[[], MindcladeError]
    """The error describing a stream that ended before a terminal event."""
    timeout_error: Callable[[], BaseException]
    """The error raised when the caller's total budget is exhausted."""
    cancelled_error: Callable[[], BaseException]
    """The error raised when the caller's cancellation event is set."""


def watch_call(base: PreparedCall, remaining: float) -> PreparedCall:
    """Derive one attempt's call from the watch's prepared call.

    The request id, trace id, idempotency key, and lease token are carried
    forward unchanged: a watch that authenticates with a lease must keep doing
    so after a reconnect, and correlation must survive one too.
    """

    return replace(base, timeout=max(0.001, min(remaining, MAX_WATCH_ATTEMPT_SECONDS)))


def watch_budget(
    timeout: float,
    options: CallOptions | None,
) -> tuple[PreparedCall, float]:
    """Intersect the watch timeout with any per-request timeout the caller set."""

    if not 0 < timeout <= MAX_WATCH_BUDGET_SECONDS:
        raise ValueError(f"watch timeout must be in (0, {int(MAX_WATCH_BUDGET_SECONDS)}] seconds")
    base = prepare_call(
        options,
        default_timeout=min(timeout, MAX_WATCH_ATTEMPT_SECONDS),
        require_idempotency=False,
    )
    total = min(timeout, options.timeout) if options is not None and options.timeout else timeout
    return base, total


def _terminal_deadline(remaining: float) -> bool:
    return remaining <= 0


class WatchStream[ItemT, CursorT](Iterator[ItemT]):
    """A resumable synchronous watch that is also a context manager."""

    __slots__ = ("_call", "_cursor", "_iterator", "_spec")

    def __init__(
        self,
        invoker: SyncInvoker,
        spec: WatchSpec[ItemT, CursorT],
        *,
        cursor: CursorT,
        call: PreparedCall,
        total: float,
        cancellation: threading.Event | None,
    ) -> None:
        self._spec = spec
        self._call = call
        self._cursor = cursor
        self._iterator = self._run(invoker, spec, call, total, cancellation)

    @property
    def request_id(self) -> str:
        """The request id every attempt of this watch carries."""

        return self._call.request_id

    @property
    def trace_id(self) -> str:
        return self._call.trace_id

    @property
    def cursor(self) -> CursorT:
        """The last acknowledged cursor, readable after an exception."""

        return self._cursor

    def _run(
        self,
        invoker: SyncInvoker,
        spec: WatchSpec[ItemT, CursorT],
        base: PreparedCall,
        total: float,
        cancellation: threading.Event | None,
    ) -> Iterator[ItemT]:
        deadline = time.monotonic() + total
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise spec.cancelled_error()
            remaining = deadline - time.monotonic()
            if _terminal_deadline(remaining):
                raise spec.timeout_error()
            received = False
            stream_error: MindcladeError
            stream = invoker.stream(
                spec.method,
                spec.build_request(self._cursor, remaining),
                call=watch_call(base, remaining),
                cancellation=cancellation,
            )
            try:
                try:
                    for raw in stream:
                        if cancellation is not None and cancellation.is_set():
                            raise spec.cancelled_error()
                        item, next_cursor, terminal = spec.accept(raw, self._cursor)
                        self._cursor = next_cursor
                        received = True
                        failures = 0
                        yield item
                        if terminal:
                            return
                finally:
                    stream.close()
            except DeadlineExceededError as error:
                # A per-attempt deadline is only fatal once the caller's whole
                # budget is gone; otherwise the attempt was merely clamped.
                if _terminal_deadline(deadline - time.monotonic()):
                    raise spec.timeout_error() from None
                stream_error = error
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            else:
                stream_error = spec.closed_error()
            if received:
                failures = 0
            failures += 1
            if failures >= invoker.config.retry.max_attempts:
                raise stream_error
            remaining = deadline - time.monotonic()
            if _terminal_deadline(remaining):
                raise spec.timeout_error()
            delay = retry_delay(
                invoker.config.retry,
                failures,
                remaining,
                retry_after=stream_error.retry_after,
            )
            if cancellation is not None:
                if cancellation.wait(delay):
                    raise spec.cancelled_error()
            elif delay > 0:
                time.sleep(delay)

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> ItemT:
        return next(self._iterator)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        """Release the live call without starting another attempt."""

        cast(Any, self._iterator).close()


class AsyncWatchStream[ItemT, CursorT](AsyncIterator[ItemT]):
    """A resumable asyncio watch that is also an async context manager."""

    __slots__ = ("_call", "_cursor", "_iterator", "_spec")

    def __init__(
        self,
        invoker: AsyncInvoker,
        spec: WatchSpec[ItemT, CursorT],
        *,
        cursor: CursorT,
        call: PreparedCall,
        total: float,
        cancellation: asyncio.Event | None,
    ) -> None:
        self._spec = spec
        self._call = call
        self._cursor = cursor
        self._iterator = self._run(invoker, spec, call, total, cancellation)

    @property
    def request_id(self) -> str:
        return self._call.request_id

    @property
    def trace_id(self) -> str:
        return self._call.trace_id

    @property
    def cursor(self) -> CursorT:
        return self._cursor

    async def _run(
        self,
        invoker: AsyncInvoker,
        spec: WatchSpec[ItemT, CursorT],
        base: PreparedCall,
        total: float,
        cancellation: asyncio.Event | None,
    ) -> AsyncIterator[ItemT]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + total
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise spec.cancelled_error()
            remaining = deadline - loop.time()
            if _terminal_deadline(remaining):
                raise spec.timeout_error()
            received = False
            stream_error: MindcladeError
            try:
                stream = invoker.stream(
                    spec.method,
                    spec.build_request(self._cursor, remaining),
                    call=watch_call(base, remaining),
                    cancellation=cancellation,
                )
                try:
                    async with asyncio.timeout(remaining):
                        async for raw in stream:
                            if cancellation is not None and cancellation.is_set():
                                raise spec.cancelled_error()
                            item, next_cursor, terminal = spec.accept(raw, self._cursor)
                            self._cursor = next_cursor
                            received = True
                            failures = 0
                            yield item
                            if terminal:
                                return
                finally:
                    await stream.aclose()
            except TimeoutError:
                raise spec.timeout_error() from None
            except DeadlineExceededError as error:
                if _terminal_deadline(deadline - loop.time()):
                    raise spec.timeout_error() from None
                stream_error = error
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            else:
                stream_error = spec.closed_error()
            if received:
                failures = 0
            failures += 1
            if failures >= invoker.config.retry.max_attempts:
                raise stream_error
            remaining = deadline - loop.time()
            if _terminal_deadline(remaining):
                raise spec.timeout_error()
            delay = retry_delay(
                invoker.config.retry,
                failures,
                remaining,
                retry_after=stream_error.retry_after,
            )
            if cancellation is None:
                if delay > 0:
                    await asyncio.sleep(delay)
            else:
                try:
                    await asyncio.wait_for(cancellation.wait(), timeout=delay)
                except TimeoutError:
                    pass
                else:
                    raise spec.cancelled_error()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ItemT:
        return await self._iterator.__anext__()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        await self.aclose()

    async def aclose(self) -> None:
        """Release the live call without starting another attempt."""

        await cast(Any, self._iterator).aclose()
