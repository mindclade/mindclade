"""Durable-operation polling, watch, and cancellation helpers."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import cast

import grpc
from google.protobuf.message import Message
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import operation_pb2

from ._invocation import (
    AsyncInvoker,
    SyncInvoker,
    canonical_digest,
    command_context,
    retry_delay,
)
from ._validation import required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import (
    CancelledError,
    DeadlineExceededError,
    MindcladeError,
    OperationFailedError,
    OperationTimeoutError,
    ProtocolError,
    UnavailableError,
)
from .transport import CANCEL_OPERATION, GET_OPERATION, LIST_OPERATIONS, WATCH_OPERATION

_TERMINAL_STATES = frozenset(
    {
        operation_pb2.OPERATION_STATE_SUCCEEDED,
        operation_pb2.OPERATION_STATE_FAILED,
        operation_pb2.OPERATION_STATE_CANCELLED,
    }
)
_FAILED_STATES = frozenset(
    {
        operation_pb2.OPERATION_STATE_FAILED,
        operation_pb2.OPERATION_STATE_CANCELLED,
    }
)
_CANCELLATION_POLL_SECONDS = 0.25
_MAX_OPERATION_PAGE_SIZE = 200


def _operation_from_response(
    response: object,
    *,
    label: str,
) -> operation_pb2.Operation:
    if not isinstance(response, Message):
        raise ProtocolError(
            f"{label} response violated its generated contract",
            status=grpc.StatusCode.DATA_LOSS,
        )
    operation = required_response_message(
        response,
        "operation",
        operation_pb2.Operation,
        label=label,
    )
    required_text("operation id", operation.operation_id)
    if operation.state == operation_pb2.OPERATION_STATE_UNSPECIFIED:
        raise ProtocolError(
            f"{label} returned an unspecified operation state",
            status=grpc.StatusCode.DATA_LOSS,
        )
    if operation.done != (operation.state in _TERMINAL_STATES):
        raise ProtocolError(
            f"{label} returned inconsistent terminal operation state",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return operation


def _raise_if_operation_failed(operation: operation_pb2.Operation) -> None:
    if operation.state in _FAILED_STATES or operation.HasField("error"):
        raise OperationFailedError(operation)


def _validate_listed_operation(
    operation: operation_pb2.Operation, tenant_id: str, project_id: str
) -> None:
    required_text("operation id", operation.operation_id)
    if (
        operation.tenant_id != tenant_id
        or operation.project_id != project_id
        or operation.state == operation_pb2.OPERATION_STATE_UNSPECIFIED
        or operation.done != (operation.state in _TERMINAL_STATES)
    ):
        raise ProtocolError(
            "ListOperations returned invalid or cross-project durable state",
            status=grpc.StatusCode.DATA_LOSS,
        )


class Operations:
    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def list(
        self,
        request: job_service_pb2.ListOperationsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.ListOperationsResponse:
        value = job_service_pb2.ListOperationsRequest()
        if request is not None:
            value.CopyFrom(request)
        parent = self._invoker.config.project_parent
        if value.parent and value.parent != parent:
            raise ValueError("operation list parent must match the configured project")
        if value.page.page_size > _MAX_OPERATION_PAGE_SIZE:
            raise ValueError("operation page size cannot exceed 200")
        value.parent = parent
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        raw = self._invoker.unary(LIST_OPERATIONS, value, call=call, retry_safe=True)
        if not isinstance(raw, job_service_pb2.ListOperationsResponse):
            raise ProtocolError(
                "ListOperations response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )
        response = job_service_pb2.ListOperationsResponse()
        response.CopyFrom(raw)
        for operation in response.operations:
            _validate_listed_operation(
                operation,
                self._invoker.config.tenant_id,
                self._invoker.config.project_id,
            )
        return response

    def get(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            job_service_pb2.GetOperationResponse,
            self._invoker.unary(
                GET_OPERATION,
                job_service_pb2.GetOperationRequest(
                    name=required_text("operation name", name),
                    if_none_match=if_none_match,
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return _operation_from_response(response, label="operation get")

    def cancel(
        self,
        name: str,
        *,
        etag: str,
        reason: str,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        request = job_service_pb2.CancelOperationRequest(
            name=required_text("operation name", name),
            etag=required_text("operation etag", etag),
            reason=required_text("cancellation reason", reason, maximum=1024),
        )
        request.context.CopyFrom(
            command_context(
                self._invoker.config,
                call,
                request_digest=canonical_digest(request),
            )
        )
        response = cast(
            job_service_pb2.CancelOperationResponse,
            self._invoker.unary(
                CANCEL_OPERATION,
                request,
                call=call,
                retry_safe=True,
            ),
        )
        return _operation_from_response(response, label="operation cancellation")

    def wait(
        self,
        name: str,
        *,
        timeout: float = 300.0,
        poll_interval: float | None = None,
        cancellation: threading.Event | None = None,
    ) -> operation_pb2.Operation:
        if timeout <= 0:
            raise ValueError("wait timeout must be positive")
        interval = poll_interval or self._invoker.config.poll_interval
        if interval <= 0:
            raise ValueError("poll interval must be positive")
        deadline = time.monotonic() + timeout
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("operation wait was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OperationTimeoutError("operation did not finish before the wait deadline")
            operation = self.get(
                name,
                options=CallOptions(timeout=min(self._invoker.config.default_timeout, remaining)),
            )
            if operation.done:
                _raise_if_operation_failed(operation)
                return operation
            sleep_for = min(interval, max(0.0, deadline - time.monotonic()))
            if cancellation is not None:
                if cancellation.wait(sleep_for):
                    raise CancelledError("operation wait was cancelled")
            else:
                time.sleep(sleep_for)

    def watch(
        self,
        name: str,
        *,
        after_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: threading.Event | None = None,
        options: CallOptions | None = None,
    ) -> Iterator[job_service_pb2.WatchOperationResponse]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if timeout <= 0:
            raise ValueError("watch timeout must be positive")
        if cancellation is not None and cancellation.is_set():
            raise CancelledError("operation watch was cancelled")
        merged = options or CallOptions(timeout=timeout)
        base_call = prepare_call(
            merged,
            default_timeout=timeout,
            require_idempotency=False,
        )
        operation_name = required_text("operation name", name)
        deadline = time.monotonic() + base_call.timeout
        sequence = after_sequence
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("operation watch was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OperationTimeoutError("operation watch exceeded its total deadline")
            stream_timeout = (
                min(remaining, _CANCELLATION_POLL_SECONDS)
                if cancellation is not None
                else remaining
            )
            call = PreparedCall(
                timeout=stream_timeout,
                request_id=base_call.request_id,
                trace_id=base_call.trace_id,
                idempotency_key=None,
            )
            request = job_service_pb2.WatchOperationRequest(
                name=operation_name,
                after_sequence=sequence,
            )
            received = False
            try:
                for raw_response in self._invoker.stream(
                    WATCH_OPERATION,
                    request,
                    call=call,
                ):
                    received = True
                    response = cast(job_service_pb2.WatchOperationResponse, raw_response)
                    if response.sequence <= sequence:
                        raise ProtocolError(
                            "operation watch sequence did not advance",
                            status=grpc.StatusCode.DATA_LOSS,
                        )
                    operation = _operation_from_response(response, label="operation watch")
                    if operation.operation_id != operation_name:
                        raise ProtocolError(
                            "operation watch returned a different operation",
                            status=grpc.StatusCode.DATA_LOSS,
                        )
                    sequence = response.sequence
                    failures = 0
                    _raise_if_operation_failed(operation)
                    yield response
                    if operation.done:
                        return
                stream_error: MindcladeError = UnavailableError(
                    "operation watch closed before a terminal event",
                    retryable=True,
                )
            except DeadlineExceededError:
                if cancellation is not None and time.monotonic() < deadline:
                    continue
                raise OperationTimeoutError("operation watch exceeded its total deadline") from None
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            if received:
                failures = 0
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            delay = retry_delay(
                self._invoker.config,
                failures,
                deadline - time.monotonic(),
                retry_after=stream_error.retry_after,
            )
            if cancellation is not None:
                if cancellation.wait(delay):
                    raise CancelledError("operation watch was cancelled")
            elif delay > 0:
                time.sleep(delay)


class AsyncOperations:
    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def list(
        self,
        request: job_service_pb2.ListOperationsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.ListOperationsResponse:
        value = job_service_pb2.ListOperationsRequest()
        if request is not None:
            value.CopyFrom(request)
        parent = self._invoker.config.project_parent
        if value.parent and value.parent != parent:
            raise ValueError("operation list parent must match the configured project")
        if value.page.page_size > _MAX_OPERATION_PAGE_SIZE:
            raise ValueError("operation page size cannot exceed 200")
        value.parent = parent
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        raw = await self._invoker.unary(LIST_OPERATIONS, value, call=call, retry_safe=True)
        if not isinstance(raw, job_service_pb2.ListOperationsResponse):
            raise ProtocolError(
                "ListOperations response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )
        response = job_service_pb2.ListOperationsResponse()
        response.CopyFrom(raw)
        for operation in response.operations:
            _validate_listed_operation(
                operation,
                self._invoker.config.tenant_id,
                self._invoker.config.project_id,
            )
        return response

    async def get(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            job_service_pb2.GetOperationResponse,
            await self._invoker.unary(
                GET_OPERATION,
                job_service_pb2.GetOperationRequest(
                    name=required_text("operation name", name),
                    if_none_match=if_none_match,
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return _operation_from_response(response, label="operation get")

    async def cancel(
        self,
        name: str,
        *,
        etag: str,
        reason: str,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        request = job_service_pb2.CancelOperationRequest(
            name=required_text("operation name", name),
            etag=required_text("operation etag", etag),
            reason=required_text("cancellation reason", reason, maximum=1024),
        )
        request.context.CopyFrom(
            command_context(
                self._invoker.config,
                call,
                request_digest=canonical_digest(request),
            )
        )
        response = cast(
            job_service_pb2.CancelOperationResponse,
            await self._invoker.unary(
                CANCEL_OPERATION,
                request,
                call=call,
                retry_safe=True,
            ),
        )
        return _operation_from_response(response, label="operation cancellation")

    async def wait(
        self,
        name: str,
        *,
        timeout: float = 300.0,
        poll_interval: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> operation_pb2.Operation:
        if timeout <= 0:
            raise ValueError("wait timeout must be positive")
        interval = poll_interval or self._invoker.config.poll_interval
        if interval <= 0:
            raise ValueError("poll interval must be positive")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("operation wait was cancelled")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OperationTimeoutError("operation did not finish before the wait deadline")
            operation = await self.get(
                name,
                options=CallOptions(timeout=min(self._invoker.config.default_timeout, remaining)),
            )
            if operation.done:
                _raise_if_operation_failed(operation)
                return operation
            sleep_for = min(interval, max(0.0, deadline - loop.time()))
            if cancellation is None:
                await asyncio.sleep(sleep_for)
            else:
                try:
                    await asyncio.wait_for(cancellation.wait(), timeout=sleep_for)
                except TimeoutError:
                    pass
                else:
                    raise CancelledError("operation wait was cancelled")

    async def watch(
        self,
        name: str,
        *,
        after_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: asyncio.Event | None = None,
        options: CallOptions | None = None,
    ) -> AsyncIterator[job_service_pb2.WatchOperationResponse]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if timeout <= 0:
            raise ValueError("watch timeout must be positive")
        if cancellation is not None and cancellation.is_set():
            raise CancelledError("operation watch was cancelled")
        merged = options or CallOptions(timeout=timeout)
        base_call = prepare_call(
            merged,
            default_timeout=timeout,
            require_idempotency=False,
        )
        operation_name = required_text("operation name", name)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + base_call.timeout
        sequence = after_sequence
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("operation watch was cancelled")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OperationTimeoutError("operation watch exceeded its total deadline")
            stream_timeout = (
                min(remaining, _CANCELLATION_POLL_SECONDS)
                if cancellation is not None
                else remaining
            )
            call = PreparedCall(
                timeout=stream_timeout,
                request_id=base_call.request_id,
                trace_id=base_call.trace_id,
                idempotency_key=None,
            )
            request = job_service_pb2.WatchOperationRequest(
                name=operation_name,
                after_sequence=sequence,
            )
            received = False
            try:
                async with asyncio.timeout(stream_timeout):
                    async for raw_response in self._invoker.stream(
                        WATCH_OPERATION,
                        request,
                        call=call,
                    ):
                        received = True
                        response = cast(job_service_pb2.WatchOperationResponse, raw_response)
                        if response.sequence <= sequence:
                            raise ProtocolError(
                                "operation watch sequence did not advance",
                                status=grpc.StatusCode.DATA_LOSS,
                            )
                        operation = _operation_from_response(
                            response,
                            label="operation watch",
                        )
                        if operation.operation_id != operation_name:
                            raise ProtocolError(
                                "operation watch returned a different operation",
                                status=grpc.StatusCode.DATA_LOSS,
                            )
                        sequence = response.sequence
                        failures = 0
                        _raise_if_operation_failed(operation)
                        yield response
                        if operation.done:
                            return
                stream_error: MindcladeError = UnavailableError(
                    "operation watch closed before a terminal event",
                    retryable=True,
                )
            except TimeoutError:
                if cancellation is not None and loop.time() < deadline:
                    continue
                raise OperationTimeoutError("operation watch exceeded its total deadline") from None
            except DeadlineExceededError:
                if cancellation is not None and loop.time() < deadline:
                    continue
                raise OperationTimeoutError("operation watch exceeded its total deadline") from None
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            if received:
                failures = 0
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            delay = retry_delay(
                self._invoker.config,
                failures,
                deadline - loop.time(),
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
                    raise CancelledError("operation watch was cancelled")
