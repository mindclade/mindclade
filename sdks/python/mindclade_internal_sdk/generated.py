"""Policy-preserving access to the complete generated internal RPC estate."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from google.protobuf.message import Message

from ._invocation import AsyncInvoker, SyncInvoker
from ._raw import AsyncWithRawResponse, WithRawResponse
from .calls import CallOptions, prepare_call
from .method_policy import retry_permitted
from .transport import INTERNAL_STREAM_METHODS, INTERNAL_UNARY_METHODS


class GeneratedRPCs(WithRawResponse):
    """Advanced generated-type escape hatch with SDK auth/deadline policy."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def unary(
        self,
        method: str,
        request: Message,
        *,
        options: CallOptions | None = None,
        idempotent: bool = False,
    ) -> Message:
        if method not in INTERNAL_UNARY_METHODS:
            raise ValueError("method is not a declared unary internal RPC")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        retry_safe = retry_permitted(method, request, call, self._invoker.config)
        if idempotent and not retry_safe:
            raise ValueError("idempotent=True cannot promote an unverified generated mutation")
        return self._invoker.unary(
            method,
            request,
            call=call,
            retry_safe=retry_safe,
        )

    def stream(
        self,
        method: str,
        request: Message,
        *,
        options: CallOptions | None = None,
    ) -> Iterator[Message]:
        if method not in INTERNAL_STREAM_METHODS:
            raise ValueError("method is not a declared server-streaming internal RPC")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        yield from self._invoker.stream(method, request, call=call)


class AsyncGeneratedRPCs(AsyncWithRawResponse):
    """Asyncio variant of the policy-preserving generated RPC escape hatch."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def unary(
        self,
        method: str,
        request: Message,
        *,
        options: CallOptions | None = None,
        idempotent: bool = False,
    ) -> Message:
        if method not in INTERNAL_UNARY_METHODS:
            raise ValueError("method is not a declared unary internal RPC")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        retry_safe = retry_permitted(method, request, call, self._invoker.config)
        if idempotent and not retry_safe:
            raise ValueError("idempotent=True cannot promote an unverified generated mutation")
        return await self._invoker.unary(
            method,
            request,
            call=call,
            retry_safe=retry_safe,
        )

    async def stream(
        self,
        method: str,
        request: Message,
        *,
        options: CallOptions | None = None,
    ) -> AsyncIterator[Message]:
        if method not in INTERNAL_STREAM_METHODS:
            raise ValueError("method is not a declared server-streaming internal RPC")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        async for response in self._invoker.stream(method, request, call=call):
            yield response
