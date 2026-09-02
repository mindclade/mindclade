"""Shared call metadata, bounded retries, deadlines, and command context."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import random
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import grpc
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.common.v1 import command_context_pb2

from .auth import AccessToken, AsyncTokenProvider, SyncTokenProvider
from .calls import NullObserver, Observer, PreparedCall, RpcObservation
from .config import ClientConfig, ConfigurationError
from .errors import (
    AuthenticationError,
    DeadlineExceededError,
    MindcladeError,
    normalize_rpc_error,
)
from .transport import AsyncTransport, Metadata, SyncTransport


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


def _base_metadata(config: ClientConfig, call: PreparedCall) -> list[tuple[str, str]]:
    values = [
        ("x-mindclade-expected-tenant", config.tenant_id),
        ("x-mindclade-expected-project", config.project_id),
        ("x-mindclade-expected-principal", config.principal_id),
        ("x-request-id", call.request_id),
        ("x-trace-id", call.trace_id),
        ("x-mindclade-sdk", config.user_agent),
    ]
    if call.idempotency_key:
        values.append(("idempotency-key", call.idempotency_key))
    if call.lease_token:
        values.append(("x-mindclade-lease-token", call.lease_token))
    return values


def _authorized_metadata(
    config: ClientConfig,
    call: PreparedCall,
    token: AccessToken | None,
) -> Metadata:
    values = _base_metadata(config, call)
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


def _observe(
    observer: Observer,
    *,
    method: str,
    attempt: int,
    started: float,
    status: str,
    request_id: str,
) -> None:
    # Telemetry is deliberately isolated from application correctness.
    with contextlib.suppress(Exception):
        observer.observe(
            RpcObservation(
                method=method,
                attempt=attempt,
                elapsed_seconds=max(0.0, time.monotonic() - started),
                status=status,
                request_id=request_id,
            )
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
        """Invoke unary RPC and copy its initial response metadata."""

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
        deadline = time.monotonic() + call.timeout
        attempts = self.config.retry.max_attempts if retry_safe else 1
        last_error: MindcladeError | None = None
        for attempt in range(1, attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                remaining = 0.001
            started = time.monotonic()
            try:
                token = self._token(call, timeout=remaining)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _credential_deadline_error(call)
                metadata = _authorized_metadata(self.config, call, token)
                if include_metadata:
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
                    request_id=call.request_id,
                )
                last_error = normalized
                if not (retry_safe and normalized.retryable and attempt < attempts):
                    raise normalized from error
                remaining = max(0.0, deadline - time.monotonic())
                if normalized.retry_after is not None:
                    delay = min(self.config.retry.max_delay, normalized.retry_after, remaining)
                    if remaining <= 0:
                        raise normalized from error
                else:
                    delay = min(
                        self.config.retry.max_delay,
                        self.config.retry.base_delay * (2 ** (attempt - 1)),
                        remaining,
                    )
                if delay < 0 or (delay == 0 and normalized.retry_after is None):
                    raise normalized from error
                time.sleep(
                    delay if normalized.retry_after is not None else random.uniform(0.0, delay)
                )
                continue
            _observe(
                self.observer,
                method=method,
                attempt=attempt,
                started=started,
                status="OK",
                request_id=call.request_id,
            )
            return response, response_metadata
        assert last_error is not None
        raise last_error

    def stream(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
    ) -> Iterator[Message]:
        deadline = time.monotonic() + call.timeout
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            token = self._token(call, timeout=remaining)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            yield from self.transport.unary_stream(
                method,
                request,
                timeout=remaining,
                metadata=_authorized_metadata(self.config, call, token),
            )
        except grpc.RpcError as error:
            raise normalize_rpc_error(error, fallback_request_id=call.request_id) from error


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
        """Invoke unary RPC and copy its initial response metadata."""

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
        deadline = loop.time() + call.timeout
        attempts = self.config.retry.max_attempts if retry_safe else 1
        last_error: MindcladeError | None = None
        for attempt in range(1, attempts + 1):
            remaining = deadline - loop.time()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                remaining = 0.001
            started = time.monotonic()
            try:
                token = await self._token(call, timeout=remaining)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise _credential_deadline_error(call)
                metadata = _authorized_metadata(self.config, call, token)
                if include_metadata:
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
                    request_id=call.request_id,
                )
                last_error = normalized
                if not (retry_safe and normalized.retryable and attempt < attempts):
                    raise normalized from error
                remaining = max(0.0, deadline - loop.time())
                if normalized.retry_after is not None:
                    delay = min(self.config.retry.max_delay, normalized.retry_after, remaining)
                    if remaining <= 0:
                        raise normalized from error
                else:
                    delay = min(
                        self.config.retry.max_delay,
                        self.config.retry.base_delay * (2 ** (attempt - 1)),
                        remaining,
                    )
                if delay < 0 or (delay == 0 and normalized.retry_after is None):
                    raise normalized from error
                await asyncio.sleep(
                    delay if normalized.retry_after is not None else random.uniform(0.0, delay)
                )
                continue
            _observe(
                self.observer,
                method=method,
                attempt=attempt,
                started=started,
                status="OK",
                request_id=call.request_id,
            )
            return response, response_metadata
        assert last_error is not None
        raise last_error

    async def stream(
        self,
        method: str,
        request: Message,
        *,
        call: PreparedCall,
    ) -> AsyncIterator[Message]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + call.timeout
        try:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            token = await self._token(call, timeout=remaining)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise _credential_deadline_error(call)
            async for response in self.transport.unary_stream(
                method,
                request,
                timeout=remaining,
                metadata=_authorized_metadata(self.config, call, token),
            ):
                yield response
        except grpc.RpcError as error:
            raise normalize_rpc_error(error, fallback_request_id=call.request_id) from error
