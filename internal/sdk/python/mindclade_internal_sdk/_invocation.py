"""Shared call metadata, bounded retries, deadlines, and command context."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterable, Callable, Generator
from datetime import UTC, datetime, timedelta
from typing import cast

import grpc
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.common.v1 import command_context_pb2

from ._metadata import is_credential_metadata_key
from ._raw import active_capture
from ._retry import retry_delay as _policy_retry_delay
from ._retry import should_retry
from .auth import AccessToken, AsyncTokenProvider, SyncTokenProvider
from .calls import NullObserver, Observer, PreparedCall, RpcObservation
from .config import ClientConfig, ConfigurationError
from .errors import (
    AuthenticationError,
    CancelledError,
    DeadlineExceededError,
    MindcladeError,
    RetryTrace,
    TransportError,
    normalize_rpc_error,
)
from .transport import AsyncTransport, Metadata, SyncStreamCall, SyncTransport

_CANCELLATION_CHECK_SECONDS = 0.01


def canonical_digest(message: Message) -> str:
    return "sha256:" + hashlib.sha256(message.SerializeToString(deterministic=True)).hexdigest()


def _deadline_timestamp(timeout: float) -> Timestamp:
    value = Timestamp()
    value.FromDatetime(datetime.now(UTC) + timedelta(seconds=timeout))
    return value


def command_context(
    config: ClientConfig,
    call: PreparedCall,
    *,
    request_digest: str,
) -> command_context_pb2.CommandContext:
    return command_context_pb2.CommandContext(
        request_id=call.request_id,
        idempotency_key=call.idempotency_key or "",
        principal_id=config.principal_id,
        trace_id=call.trace_id,
        deadline=_deadline_timestamp(call.timeout),
        canonical_request_digest=request_digest,
        tenant_id=config.tenant_id,
        project_id=config.project_id,
        correlation_id=call.request_id,
    )


def _base_metadata(
    config: ClientConfig,
    call: PreparedCall,
    *,
    attempt_index: int = 0,
    remaining: float | None = None,
) -> list[tuple[str, str]]:
    """Build the request metadata every attempt carries.

    ``attempt_index`` is the 0-based retry counter the server sees, and
    ``remaining`` is what is left of the caller's total budget, published in
    milliseconds so a server can shed load rather than exhaust the client.
    """

    budget = call.timeout if remaining is None else remaining
    values = [
        ("x-mindclade-expected-tenant", config.tenant_id),
        ("x-mindclade-expected-project", config.project_id),
        ("x-mindclade-expected-principal", config.principal_id),
        ("x-request-id", call.request_id),
        ("x-trace-id", call.trace_id),
        ("x-mindclade-sdk", config.user_agent),
        ("x-mindclade-retry-count", str(max(0, attempt_index))),
        ("x-mindclade-timeout-ms", str(max(0, int(max(0.0, budget) * 1000)))),
    ]
    if call.idempotency_key:
        values.append(("idempotency-key", call.idempotency_key))
    if call.lease_token:
        values.append(("x-mindclade-lease-token", call.lease_token))
    # Caller metadata is appended last and re-checked here: ``ClientConfig``
    # already rejected reserved and credential-bearing keys, and this second
    # pass means a mapping mutated after validation still cannot shadow an SDK
    # key or smuggle a credential onto the wire.
    if config.custom_metadata:
        reserved = {key for key, _ in values}
        for key, value in config.custom_metadata.items():
            if key in reserved or is_credential_metadata_key(key):
                continue
            values.append((key, value))
    return values


def _authorized_metadata(
    config: ClientConfig,
    call: PreparedCall,
    token: AccessToken | None,
    *,
    attempt_index: int = 0,
    remaining: float | None = None,
) -> Metadata:
    values = _base_metadata(config, call, attempt_index=attempt_index, remaining=remaining)
    if token is not None:
        try:
            authorization = token.authorization_header()
        except ValueError as error:
            raise AuthenticationError(
                "workload-identity token is not usable",
                request_id=call.request_id,
            ) from error
        values.append(("authorization", authorization))
    return tuple(values)


def _credential_error(call: PreparedCall) -> AuthenticationError:
    """Convert an untrusted credential-provider failure without copying its detail."""

    return AuthenticationError(
        "workload-identity credential acquisition failed",
        status=grpc.StatusCode.UNAUTHENTICATED,
        request_id=call.request_id,
        retryable=False,
    )


def _credential_deadline_error(call: PreparedCall) -> DeadlineExceededError:
    return DeadlineExceededError(
        "Mindclade call deadline expired during credential acquisition",
        status=grpc.StatusCode.DEADLINE_EXCEEDED,
        request_id=call.request_id,
        retryable=True,
    )


def _caller_cancelled(call: PreparedCall) -> CancelledError:
    return CancelledError(
        "Mindclade stream was cancelled by the caller",
        status=grpc.StatusCode.CANCELLED,
        request_id=call.request_id,
        retryable=False,
    )


class _CancelOnce:
    """Invoke a transport's non-blocking cancellation hook at most once."""

    def __init__(self, cancel: Callable[[], object]) -> None:
        self._cancel = cancel
        self._lock = threading.Lock()
        self._called = False

    def __call__(self) -> None:
        with self._lock:
            if self._called:
                return
            self._called = True
        # A cleanup hook supplied by an injected transport must not replace the
        # SDK's typed cancellation or the stream's primary failure.
        with contextlib.suppress(Exception):
            self._cancel()


def _cancel_sync_call_when_requested(
    cancellation: threading.Event,
    stopped: threading.Event,
    caller_cancelled: threading.Event,
    cancel_once: _CancelOnce,
) -> None:
    """Cancel one live gRPC call without shortening its transport deadline."""

    while not stopped.is_set():
        if cancellation.wait(_CANCELLATION_CHECK_SECONDS):
            caller_cancelled.set()
            cancel_once()
            return


async def _cancel_async_call_when_requested(
    cancellation: asyncio.Event,
    caller_cancelled: asyncio.Event,
    cancel_once: _CancelOnce,
) -> None:
    """Cancel one live asyncio gRPC call when the caller's event is set."""

    await cancellation.wait()
    caller_cancelled.set()
    cancel_once()


def _observe(
    observer: Observer,
    *,
    method: str,
    attempt: int,
    started: float,
    status: str,
    call: PreparedCall,
    metadata: Metadata = (),
    cumulative_delay: float = 0.0,
) -> None:
    """Publish one bounded attempt record.

    Only metadata KEY NAMES travel to the observer; no value, payload, access
    token, or lease token can reach it. Telemetry is also deliberately isolated
    from application correctness, so an observer that raises cannot fail a call.
    """

    with contextlib.suppress(Exception):
        observer.observe(
            RpcObservation(
                method=method,
                attempt=attempt,
                elapsed_seconds=max(0.0, time.monotonic() - started),
                status=status,
                request_id=call.request_id,
                trace_id=call.trace_id,
                retry_count=max(0, attempt - 1),
                cumulative_delay_seconds=max(0.0, cumulative_delay),
                metadata_keys=tuple(sorted({str(key) for key, _ in metadata})),
            )
        )


def retry_delay(
    config: ClientConfig,
    failures: int,
    remaining: float,
    *,
    retry_after: float | None = None,
) -> float:
    """Compute one backoff delay through the SDK's single retry policy.

    This is a thin adapter so callers holding a :class:`ClientConfig` do not
    need to reach into ``config.retry``; the policy itself lives in
    :mod:`mindclade_internal_sdk._retry` and is shared by every retry site.
    """

    return _policy_retry_delay(config.retry, failures, remaining, retry_after=retry_after)


def _attempt_budget(config: ClientConfig, call: PreparedCall, *, retry_safe: bool) -> int:
    """Return the attempt cap, where a per-request limit may only narrow policy."""

    if not retry_safe:
        return 1
    attempts = config.retry.max_attempts
    if call.max_attempts is not None:
        attempts = min(attempts, call.max_attempts)
    return max(1, attempts)


def _with_trace(
    error: MindcladeError,
    attempts: int,
    cumulative_delay: float,
) -> MindcladeError:
    """Stamp observable retry accounting onto the error that leaves the SDK."""

    error.retry_trace = RetryTrace(
        attempts=max(1, attempts),
        cumulative_delay_seconds=max(0.0, cumulative_delay),
        cause=error.status.name if error.status is not None else "UNKNOWN",
    )
    return error


def _exhausted_budget(call: PreparedCall) -> TransportError:
    """Fail closed when a retry loop somehow ends without a transport result."""

    return TransportError(
        "Mindclade call exhausted its retry budget without a transport result",
        status=grpc.StatusCode.UNAVAILABLE,
        request_id=call.request_id,
        retryable=False,
    )


class SyncInvoker:
    def __init__(
        self,
        config: ClientConfig,
        transport: SyncTransport,
        *,
        observer: Observer | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.observer = observer or NullObserver()

    def _token(self, call: PreparedCall, *, timeout: float) -> AccessToken | None:
        provider = self.config.token_provider
        if provider is None:
            return None
        if inspect.iscoroutinefunction(provider.get_token):
            raise ConfigurationError("synchronous client requires a synchronous token provider")
        try:
            result = cast(
                object,
                cast(SyncTokenProvider, provider).get_token(timeout=timeout),
            )
        except TimeoutError:
            raise _credential_deadline_error(call) from None
        except Exception:
            raise _credential_error(call) from None
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise ConfigurationError("synchronous client requires a synchronous token provider")
        if not isinstance(result, AccessToken):
            raise AuthenticationError(
                "workload-identity provider returned an invalid token",
                status=grpc.StatusCode.UNAUTHENTICATED,
                request_id=call.request_id,
            )
        return result

    def unary(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        retry_safe: bool,
    ) -> Message:
        response, _ = self._unary(
            method,
            request,
            call=call,
            retry_safe=retry_safe,
            include_metadata=False,
        )
        return response

    def unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        retry_safe: bool,
    ) -> tuple[Message, Metadata]:
        """Invoke a unary RPC and copy its response headers and trailers."""

        return self._unary(
            method,
            request,
            call=call,
            retry_safe=retry_safe,
            include_metadata=True,
        )

    def _unary(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        retry_safe: bool,
        include_metadata: bool,
    ) -> tuple[Message, Metadata]:
        # ``call.timeout`` is one total budget covering credential acquisition,
        # every attempt, and every backoff delay between them.
        deadline = time.monotonic() + call.timeout
        attempts = _attempt_budget(self.config, call, retry_safe=retry_safe)
        # A raw-response call arms a capture, which needs response metadata even
        # when the ergonomic caller did not ask for it.
        capture = active_capture()
        capturing = include_metadata or capture is not None
        last_error: MindcladeError | None = None
        attempts_used = 0
        cumulative_delay = 0.0
        for attempt in range(1, attempts + 1):
            attempts_used = attempt
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_error is not None:
                    raise _with_trace(last_error, attempts_used, cumulative_delay)
                remaining = 0.001
            started = time.monotonic()
            metadata: Metadata = ()
            try:
                token = self._token(call, timeout=remaining)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _credential_deadline_error(call)
                metadata = _authorized_metadata(
                    self.config,
                    call,
                    token,
                    attempt_index=attempt - 1,
                    remaining=remaining,
                )
                if capturing:
                    response, response_metadata = self.transport.unary_unary_with_metadata(
                        method,
                        request,
                        timeout=remaining,
                        metadata=metadata,
                    )
                else:
                    response = self.transport.unary_unary(
                        method,
                        request,
                        timeout=remaining,
                        metadata=metadata,
                    )
                    response_metadata = ()
            except grpc.RpcError as error:
                normalized = normalize_rpc_error(error, fallback_request_id=call.request_id)
                _observe(
                    self.observer,
                    method=method,
                    attempt=attempt,
                    started=started,
                    status=normalized.status.name if normalized.status else "UNKNOWN",
                    call=call,
                    metadata=metadata,
                    cumulative_delay=cumulative_delay,
                )
                last_error = normalized
                remaining = deadline - time.monotonic()
                if not retry_safe or not should_retry(
                    retryable=normalized.retryable,
                    server_override=normalized.server_should_retry,
                    attempt=attempt,
                    attempts=attempts,
                    remaining=remaining,
                ):
                    raise _with_trace(normalized, attempts_used, cumulative_delay) from None
                delay = retry_delay(
                    self.config,
                    attempt,
                    remaining,
                    retry_after=normalized.retry_after,
                )
                cumulative_delay += delay
                time.sleep(delay)
                continue
            _observe(
                self.observer,
                method=method,
                attempt=attempt,
                started=started,
                status="OK",
                call=call,
                metadata=metadata,
                cumulative_delay=cumulative_delay,
            )
            if capture is not None:
                capture.record(
                    grpc.StatusCode.OK,
                    response_metadata,
                    call.request_id,
                    call.trace_id,
                )
            return response, response_metadata
        if last_error is not None:
            raise _with_trace(last_error, attempts_used, cumulative_delay)
        raise _exhausted_budget(call)

    def stream(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        cancellation: threading.Event | None = None,
    ) -> Generator[Message, None, None]:
        deadline = time.monotonic() + call.timeout
        stream: SyncStreamCall | None = None
        cancel_once: _CancelOnce | None = None
        stopped = threading.Event()
        caller_cancelled = threading.Event()
        watcher: threading.Thread | None = None
        try:
            if cancellation is not None and cancellation.is_set():
                raise _caller_cancelled(call)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            token = self._token(call, timeout=remaining)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            stream = self.transport.unary_stream(
                method,
                request,
                timeout=remaining,
                metadata=_authorized_metadata(
                    self.config,
                    call,
                    token,
                    attempt_index=0,
                    remaining=remaining,
                ),
            )
            cancel = getattr(stream, "cancel", None)
            if callable(cancel):
                cancel_once = _CancelOnce(cancel)
            if cancellation is not None:
                if cancel_once is None:
                    raise ConfigurationError(
                        "synchronous stream transport must support cancellation"
                    )
                watcher = threading.Thread(
                    target=_cancel_sync_call_when_requested,
                    args=(cancellation, stopped, caller_cancelled, cancel_once),
                    name="mindclade-stream-cancellation",
                    daemon=True,
                )
                watcher.start()
            yield from stream
            if cancellation is not None and (caller_cancelled.is_set() or cancellation.is_set()):
                raise _caller_cancelled(call)
        except grpc.RpcError as error:
            if cancellation is not None and (caller_cancelled.is_set() or cancellation.is_set()):
                raise _caller_cancelled(call) from None
            raise normalize_rpc_error(error, fallback_request_id=call.request_id) from None
        finally:
            stopped.set()
            if cancel_once is not None:
                cancel_once()
            if watcher is not None:
                watcher.join()


class AsyncInvoker:
    def __init__(
        self,
        config: ClientConfig,
        transport: AsyncTransport,
        *,
        observer: Observer | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.observer = observer or NullObserver()

    async def _token(self, call: PreparedCall, *, timeout: float) -> AccessToken | None:
        provider = self.config.token_provider
        if provider is None:
            return None
        try:
            result = cast(AsyncTokenProvider, provider).get_token(timeout=timeout)
        except Exception:
            raise _credential_error(call) from None
        if not inspect.isawaitable(result):
            raise ConfigurationError("asynchronous client requires an async token provider")
        try:
            token = cast(object, await asyncio.wait_for(result, timeout=timeout))
        except TimeoutError:
            raise _credential_deadline_error(call) from None
        except Exception:
            raise _credential_error(call) from None
        if not isinstance(token, AccessToken):
            raise AuthenticationError(
                "workload-identity provider returned an invalid token",
                status=grpc.StatusCode.UNAUTHENTICATED,
                request_id=call.request_id,
            )
        return token

    async def unary(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        retry_safe: bool,
    ) -> Message:
        response, _ = await self._unary(
            method,
            request,
            call=call,
            retry_safe=retry_safe,
            include_metadata=False,
        )
        return response

    async def unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        retry_safe: bool,
    ) -> tuple[Message, Metadata]:
        """Invoke a unary RPC and copy its response headers and trailers."""

        return await self._unary(
            method,
            request,
            call=call,
            retry_safe=retry_safe,
            include_metadata=True,
        )

    async def _unary(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        retry_safe: bool,
        include_metadata: bool,
    ) -> tuple[Message, Metadata]:
        loop = asyncio.get_running_loop()
        # ``call.timeout`` is one total budget covering credential acquisition,
        # every attempt, and every backoff delay between them.
        deadline = loop.time() + call.timeout
        attempts = _attempt_budget(self.config, call, retry_safe=retry_safe)
        # A raw-response call arms a capture, which needs response metadata even
        # when the ergonomic caller did not ask for it.
        capture = active_capture()
        capturing = include_metadata or capture is not None
        last_error: MindcladeError | None = None
        attempts_used = 0
        cumulative_delay = 0.0
        for attempt in range(1, attempts + 1):
            attempts_used = attempt
            remaining = deadline - loop.time()
            if remaining <= 0:
                if last_error is not None:
                    raise _with_trace(last_error, attempts_used, cumulative_delay)
                remaining = 0.001
            started = time.monotonic()
            metadata: Metadata = ()
            try:
                token = await self._token(call, timeout=remaining)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise _credential_deadline_error(call)
                metadata = _authorized_metadata(
                    self.config,
                    call,
                    token,
                    attempt_index=attempt - 1,
                    remaining=remaining,
                )
                if capturing:
                    response, response_metadata = await self.transport.unary_unary_with_metadata(
                        method,
                        request,
                        timeout=remaining,
                        metadata=metadata,
                    )
                else:
                    response = await self.transport.unary_unary(
                        method,
                        request,
                        timeout=remaining,
                        metadata=metadata,
                    )
                    response_metadata = ()
            except grpc.RpcError as error:
                normalized = normalize_rpc_error(error, fallback_request_id=call.request_id)
                _observe(
                    self.observer,
                    method=method,
                    attempt=attempt,
                    started=started,
                    status=normalized.status.name if normalized.status else "UNKNOWN",
                    call=call,
                    metadata=metadata,
                    cumulative_delay=cumulative_delay,
                )
                last_error = normalized
                remaining = deadline - loop.time()
                if not retry_safe or not should_retry(
                    retryable=normalized.retryable,
                    server_override=normalized.server_should_retry,
                    attempt=attempt,
                    attempts=attempts,
                    remaining=remaining,
                ):
                    raise _with_trace(normalized, attempts_used, cumulative_delay) from None
                delay = retry_delay(
                    self.config,
                    attempt,
                    remaining,
                    retry_after=normalized.retry_after,
                )
                cumulative_delay += delay
                await asyncio.sleep(delay)
                continue
            _observe(
                self.observer,
                method=method,
                attempt=attempt,
                started=started,
                status="OK",
                call=call,
                metadata=metadata,
                cumulative_delay=cumulative_delay,
            )
            if capture is not None:
                capture.record(
                    grpc.StatusCode.OK,
                    response_metadata,
                    call.request_id,
                    call.trace_id,
                )
            return response, response_metadata
        if last_error is not None:
            raise _with_trace(last_error, attempts_used, cumulative_delay)
        raise _exhausted_budget(call)

    async def stream(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
        cancellation: asyncio.Event | None = None,
    ) -> AsyncGenerator[Message, None]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + call.timeout
        stream: AsyncIterable[Message] | None = None
        cancel_once: _CancelOnce | None = None
        caller_cancelled = asyncio.Event()
        watcher: asyncio.Task[None] | None = None
        try:
            if cancellation is not None and cancellation.is_set():
                raise _caller_cancelled(call)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            token = await self._token(call, timeout=remaining)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            stream = self.transport.unary_stream(
                method,
                request,
                timeout=remaining,
                metadata=_authorized_metadata(
                    self.config,
                    call,
                    token,
                    attempt_index=0,
                    remaining=remaining,
                ),
            )
            cancel = getattr(stream, "cancel", None)
            if callable(cancel):
                cancel_once = _CancelOnce(cancel)
            if cancellation is not None:
                if cancel_once is None:
                    raise ConfigurationError(
                        "asynchronous stream transport must support cancellation"
                    )
                watcher = asyncio.create_task(
                    _cancel_async_call_when_requested(
                        cancellation,
                        caller_cancelled,
                        cancel_once,
                    ),
                    name="mindclade-stream-cancellation",
                )
            async for response in stream:
                yield response
            if cancellation is not None and (caller_cancelled.is_set() or cancellation.is_set()):
                raise _caller_cancelled(call)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            externally_cancelled = task is not None and task.cancelling() > 0
            if (
                cancellation is not None
                and (caller_cancelled.is_set() or cancellation.is_set())
                and not externally_cancelled
            ):
                raise _caller_cancelled(call) from None
            raise
        except grpc.RpcError as error:
            if cancellation is not None and (caller_cancelled.is_set() or cancellation.is_set()):
                raise _caller_cancelled(call) from None
            raise normalize_rpc_error(error, fallback_request_id=call.request_id) from None
        finally:
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
            if cancel_once is not None:
                cancel_once()
