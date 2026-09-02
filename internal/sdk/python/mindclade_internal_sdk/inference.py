"""Generated-type-only inference façade with resumable typed streaming."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import cast

from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.inference.v1 import (
    inference_request_pb2,
    inference_result_pb2,
    inference_stream_pb2,
)
from mindclade.internal.inference.v1 import inference_service_pb2
from mindclade.job.v1 import operation_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context, retry_delay
from ._validation import required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import CancelledError, MindcladeError, ProtocolError, UnavailableError
from .transport import (
    COMMIT_INFERENCE_RESULT,
    GET_INFERENCE_REQUEST,
    GET_INFERENCE_RESULT,
    SUBMIT_INFERENCE,
    WATCH_INFERENCE,
)


def _timestamp_after(seconds: float) -> Timestamp:
    value = Timestamp()
    value.FromNanoseconds(time.time_ns() + int(seconds * 1_000_000_000))
    return value


def _mutation_call(
    options: CallOptions | None,
    existing_key: str,
    default_timeout: float,
) -> PreparedCall:
    selected = options
    if selected is None and existing_key:
        selected = CallOptions(idempotency_key=existing_key)
    return prepare_call(selected, default_timeout=default_timeout, require_idempotency=True)


def _materialize_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: inference_request_pb2.InferenceRequest,
    options: CallOptions | None,
) -> tuple[inference_request_pb2.InferenceRequest, PreparedCall]:
    value = inference_request_pb2.InferenceRequest()
    value.CopyFrom(request)
    existing_key = value.context.idempotency_key if value.HasField("context") else ""
    value.ClearField("context")
    value.tenant_id = invoker.config.tenant_id
    value.project_id = invoker.config.project_id
    required_text("inference request name", value.name)
    call = _mutation_call(options, existing_key, invoker.config.default_timeout)
    value.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(value))
    )
    return value, call


def _materialize_commit(
    invoker: SyncInvoker | AsyncInvoker,
    command: inference_service_pb2.CommitInferenceResultRequest,
    options: CallOptions | None,
) -> tuple[inference_service_pb2.CommitInferenceResultRequest, PreparedCall]:
    value = inference_service_pb2.CommitInferenceResultRequest()
    value.CopyFrom(command)
    existing_key = value.context.idempotency_key if value.HasField("context") else ""
    value.ClearField("context")
    if not value.HasField("inference_request") or not value.HasField("fence"):
        raise ValueError("inference request reference and lease fence are required")
    if not value.HasField("result") or not value.request_digest:
        raise ValueError("inference result and request digest are required")
    call = _mutation_call(options, existing_key, invoker.config.default_timeout)
    value.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(value))
    )
    return value, call


def _watch_call(base: PreparedCall, remaining: float) -> PreparedCall:
    return PreparedCall(
        timeout=max(0.001, min(remaining, 300.0)),
        request_id=base.request_id,
        trace_id=base.trace_id,
        idempotency_key=None,
    )


def _watch_request(
    operation_name: str,
    cursor: inference_stream_pb2.InferenceStreamCursor | None,
    remaining: float,
) -> inference_service_pb2.WatchInferenceRequest:
    request = inference_service_pb2.WatchInferenceRequest(
        operation_name=required_text("inference operation name", operation_name),
        deadline=_timestamp_after(remaining),
    )
    if cursor is not None:
        request.cursor.CopyFrom(cursor)
    return request


def _accept_message(
    response: inference_service_pb2.WatchInferenceResponse,
    cursor: inference_stream_pb2.InferenceStreamCursor | None,
) -> tuple[inference_stream_pb2.InferenceStreamMessage, inference_stream_pb2.InferenceStreamCursor]:
    message = required_response_message(
        response,
        "message",
        inference_stream_pb2.InferenceStreamMessage,
        label="inference watch",
    )
    required_text("inference request name", message.request_name)
    required_text("inference resume token", message.resume_token)
    if message.sequence <= 0 or message.WhichOneof("update") is None:
        raise ProtocolError("inference watch returned an incomplete message")
    after = cursor.after_sequence if cursor is not None else 0
    if message.WhichOneof("update") == "heartbeat":
        if (
            cursor is None
            or message.request_name != cursor.request_name
            or message.sequence != cursor.after_sequence
            or message.resume_token != cursor.resume_token
        ):
            raise ProtocolError("inference heartbeat is not bound to durable cursor")
        result = inference_stream_pb2.InferenceStreamCursor()
        result.CopyFrom(cursor)
        return message, result
    if cursor is not None and message.request_name != cursor.request_name:
        raise ProtocolError("inference watch changed request identity")
    if message.sequence != after + 1:
        raise ProtocolError("inference watch sequence is not contiguous")
    return message, inference_stream_pb2.InferenceStreamCursor(
        request_name=message.request_name,
        after_sequence=message.sequence,
        resume_token=message.resume_token,
    )


class Inference:
    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def submit(
        self,
        request: inference_request_pb2.InferenceRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value, call = _materialize_request(self._invoker, request, options)
        response = cast(
            inference_service_pb2.SubmitInferenceResponse,
            self._invoker.unary(
                SUBMIT_INFERENCE,
                inference_service_pb2.SubmitInferenceRequest(inference_request=value),
                call=call,
                retry_safe=True,
            ),
        )
        operation = required_response_message(
            response, "operation", operation_pb2.Operation, label="inference submit"
        )
        required_text("operation id", operation.operation_id)
        return operation

    def get_request(
        self, name: str, *, options: CallOptions | None = None
    ) -> inference_request_pb2.InferenceRequest:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            inference_service_pb2.GetInferenceRequestResponse,
            self._invoker.unary(
                GET_INFERENCE_REQUEST,
                inference_service_pb2.GetInferenceRequestRequest(
                    name=required_text("inference request name", name)
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "inference_request",
            inference_request_pb2.InferenceRequest,
            label="inference get request",
        )

    def get_result(
        self, operation_name: str, *, options: CallOptions | None = None
    ) -> tuple[inference_result_pb2.InferenceResult, operation_pb2.Operation]:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            inference_service_pb2.GetInferenceResultResponse,
            self._invoker.unary(
                GET_INFERENCE_RESULT,
                inference_service_pb2.GetInferenceResultRequest(
                    operation_name=required_text("inference operation name", operation_name)
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return (
            required_response_message(
                response,
                "result",
                inference_result_pb2.InferenceResult,
                label="inference get result",
            ),
            required_response_message(
                response,
                "operation",
                operation_pb2.Operation,
                label="inference get result",
            ),
        )

    def commit_result(
        self,
        command: inference_service_pb2.CommitInferenceResultRequest,
        *,
        options: CallOptions | None = None,
    ) -> tuple[inference_result_pb2.InferenceResult, operation_pb2.Operation]:
        value, call = _materialize_commit(self._invoker, command, options)
        response = cast(
            inference_service_pb2.CommitInferenceResultResponse,
            self._invoker.unary(COMMIT_INFERENCE_RESULT, value, call=call, retry_safe=True),
        )
        return (
            required_response_message(
                response,
                "result",
                inference_result_pb2.InferenceResult,
                label="inference commit",
            ),
            required_response_message(
                response,
                "operation",
                operation_pb2.Operation,
                label="inference commit",
            ),
        )

    def watch(
        self,
        operation_name: str,
        *,
        cursor: inference_stream_pb2.InferenceStreamCursor | None = None,
        timeout: float = 300.0,
        cancellation: threading.Event | None = None,
        options: CallOptions | None = None,
    ) -> Iterator[inference_stream_pb2.InferenceStreamMessage]:
        if timeout <= 0:
            raise ValueError("watch timeout must be positive")
        base = prepare_call(
            options or CallOptions(timeout=min(timeout, 300.0)),
            default_timeout=min(timeout, 300.0),
            require_idempotency=False,
        )
        current = None
        if cursor is not None:
            current = inference_stream_pb2.InferenceStreamCursor()
            current.CopyFrom(cursor)
        deadline = time.monotonic() + base.timeout
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("inference watch was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("inference watch deadline expired")
            try:
                for raw in self._invoker.stream(
                    WATCH_INFERENCE,
                    _watch_request(operation_name, current, remaining),
                    call=_watch_call(base, remaining),
                ):
                    response = cast(inference_service_pb2.WatchInferenceResponse, raw)
                    message, current = _accept_message(response, current)
                    failures = 0
                    yield message
                    if message.WhichOneof("update") in {"final_result", "failure"}:
                        return
                stream_error: MindcladeError = UnavailableError(
                    "inference watch closed before terminal durable truth",
                    retryable=True,
                )
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            retry_remaining = deadline - time.monotonic()
            if retry_remaining <= 0:
                raise TimeoutError("inference watch deadline expired") from stream_error
            delay = retry_delay(
                self._invoker.config,
                failures,
                retry_remaining,
                retry_after=stream_error.retry_after,
            )
            if cancellation is not None:
                if cancellation.wait(delay):
                    raise CancelledError("inference watch was cancelled")
            elif delay > 0:
                time.sleep(delay)

    def wait(
        self,
        operation_name: str,
        *,
        cursor: inference_stream_pb2.InferenceStreamCursor | None = None,
        timeout: float = 300.0,
        options: CallOptions | None = None,
    ) -> tuple[inference_result_pb2.InferenceResult, operation_pb2.Operation]:
        for message in self.watch(operation_name, cursor=cursor, timeout=timeout, options=options):
            if message.WhichOneof("update") == "failure":
                raise ProtocolError("inference watch reported durable failure")
            if message.WhichOneof("update") == "final_result":
                return self.get_result(operation_name, options=options)
        raise ProtocolError("inference watch ended before terminal truth")


class AsyncInference:
    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def submit(
        self,
        request: inference_request_pb2.InferenceRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value, call = _materialize_request(self._invoker, request, options)
        response = cast(
            inference_service_pb2.SubmitInferenceResponse,
            await self._invoker.unary(
                SUBMIT_INFERENCE,
                inference_service_pb2.SubmitInferenceRequest(inference_request=value),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response, "operation", operation_pb2.Operation, label="inference submit"
        )

    async def get_request(
        self, name: str, *, options: CallOptions | None = None
    ) -> inference_request_pb2.InferenceRequest:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            inference_service_pb2.GetInferenceRequestResponse,
            await self._invoker.unary(
                GET_INFERENCE_REQUEST,
                inference_service_pb2.GetInferenceRequestRequest(
                    name=required_text("inference request name", name)
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "inference_request",
            inference_request_pb2.InferenceRequest,
            label="inference get request",
        )

    async def get_result(
        self, operation_name: str, *, options: CallOptions | None = None
    ) -> tuple[inference_result_pb2.InferenceResult, operation_pb2.Operation]:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            inference_service_pb2.GetInferenceResultResponse,
            await self._invoker.unary(
                GET_INFERENCE_RESULT,
                inference_service_pb2.GetInferenceResultRequest(
                    operation_name=required_text("inference operation name", operation_name)
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return (
            required_response_message(
                response,
                "result",
                inference_result_pb2.InferenceResult,
                label="inference get result",
            ),
            required_response_message(
                response,
                "operation",
                operation_pb2.Operation,
                label="inference get result",
            ),
        )

    async def commit_result(
        self,
        command: inference_service_pb2.CommitInferenceResultRequest,
        *,
        options: CallOptions | None = None,
    ) -> tuple[inference_result_pb2.InferenceResult, operation_pb2.Operation]:
        value, call = _materialize_commit(self._invoker, command, options)
        response = cast(
            inference_service_pb2.CommitInferenceResultResponse,
            await self._invoker.unary(COMMIT_INFERENCE_RESULT, value, call=call, retry_safe=True),
        )
        return (
            required_response_message(
                response,
                "result",
                inference_result_pb2.InferenceResult,
                label="inference commit",
            ),
            required_response_message(
                response,
                "operation",
                operation_pb2.Operation,
                label="inference commit",
            ),
        )

    async def watch(
        self,
        operation_name: str,
        *,
        cursor: inference_stream_pb2.InferenceStreamCursor | None = None,
        timeout: float = 300.0,
        cancellation: asyncio.Event | None = None,
        options: CallOptions | None = None,
    ) -> AsyncIterator[inference_stream_pb2.InferenceStreamMessage]:
        if timeout <= 0:
            raise ValueError("watch timeout must be positive")
        base = prepare_call(
            options or CallOptions(timeout=min(timeout, 300.0)),
            default_timeout=min(timeout, 300.0),
            require_idempotency=False,
        )
        current = None
        if cursor is not None:
            current = inference_stream_pb2.InferenceStreamCursor()
            current.CopyFrom(cursor)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + base.timeout
        failures = 0
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CancelledError("inference watch was cancelled")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("inference watch deadline expired")
            try:
                async for raw in self._invoker.stream(
                    WATCH_INFERENCE,
                    _watch_request(operation_name, current, remaining),
                    call=_watch_call(base, remaining),
                ):
                    response = cast(inference_service_pb2.WatchInferenceResponse, raw)
                    message, current = _accept_message(response, current)
                    failures = 0
                    yield message
                    if message.WhichOneof("update") in {"final_result", "failure"}:
                        return
                stream_error: MindcladeError = UnavailableError(
                    "inference watch closed before terminal durable truth",
                    retryable=True,
                )
            except MindcladeError as error:
                if not error.retryable:
                    raise
                stream_error = error
            failures += 1
            if failures >= self._invoker.config.retry.max_attempts:
                raise stream_error
            retry_remaining = deadline - loop.time()
            if retry_remaining <= 0:
                raise TimeoutError("inference watch deadline expired") from stream_error
            delay = retry_delay(
                self._invoker.config,
                failures,
                retry_remaining,
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
                    raise CancelledError("inference watch was cancelled")

    async def wait(
        self,
        operation_name: str,
        *,
        cursor: inference_stream_pb2.InferenceStreamCursor | None = None,
        timeout: float = 300.0,
        options: CallOptions | None = None,
    ) -> tuple[inference_result_pb2.InferenceResult, operation_pb2.Operation]:
        async for message in self.watch(
            operation_name, cursor=cursor, timeout=timeout, options=options
        ):
            if message.WhichOneof("update") == "failure":
                raise ProtocolError("inference watch reported durable failure")
            if message.WhichOneof("update") == "final_result":
                return await self.get_result(operation_name, options=options)
        raise ProtocolError("inference watch ended before terminal truth")
