from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import AsyncIterator, Iterable
from unittest.mock import patch

from google.protobuf.message import Message
from mindclade.common.v1 import resource_reference_pb2
from mindclade.inference.v1 import (
    inference_request_pb2,
    inference_result_pb2,
    inference_stream_pb2,
)
from mindclade.internal.inference.v1 import inference_service_pb2
from mindclade.job.v1 import lease_fencing_pb2
from mindclade.operation.v1 import operation_pb2
from mindclade_internal_sdk import (
    AsyncClient,
    CallOptions,
    CancelledError,
    Client,
    ClientConfig,
    Environment,
    UnavailableError,
)
from mindclade_internal_sdk._invocation import canonical_digest
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
    COMMIT_INFERENCE_RESULT,
    GET_INFERENCE_REQUEST,
    GET_INFERENCE_RESULT,
    SUBMIT_INFERENCE,
    WATCH_INFERENCE,
    Metadata,
)


def config() -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:1",
        insecure_for_testing=True,
        default_timeout=1,
    )


REQUEST_NAME = "tenants/tenant-1/projects/project-1/inferenceRequests/request-1"
OPERATION_NAME = "operations/op-1"


def operation() -> operation_pb2.Operation:
    return operation_pb2.Operation(
        operation_id=OPERATION_NAME,
        tenant_id="tenant-1",
        project_id="project-1",
        state=operation_pb2.OPERATION_STATE_SUCCEEDED,
        resource_version=2,
        done=True,
    )


def result() -> inference_result_pb2.InferenceResult:
    return inference_result_pb2.InferenceResult(
        name="tenants/tenant-1/projects/project-1/inferenceResults/result-1",
        request=resource_reference_pb2.ResourceRef(
            resource_type="inference_request",
            resource_id="request-1",
            tenant_id="tenant-1",
            project_id="project-1",
            name=REQUEST_NAME,
        ),
        outcome=inference_result_pb2.INFERENCE_RESULT_OUTCOME_SUCCEEDED,
        result_digest="sha256:" + "a" * 64,
    )


def stream_messages() -> list[inference_service_pb2.WatchInferenceResponse]:
    return [
        inference_service_pb2.WatchInferenceResponse(
            message=inference_stream_pb2.InferenceStreamMessage(
                request_name=REQUEST_NAME,
                sequence=1,
                resume_token="cursor-1",
                progress=inference_stream_pb2.InferenceProgress(lifecycle_state="RUNNING"),
            )
        ),
        inference_service_pb2.WatchInferenceResponse(
            message=inference_stream_pb2.InferenceStreamMessage(
                request_name=REQUEST_NAME,
                sequence=1,
                resume_token="cursor-1",
                heartbeat=inference_stream_pb2.InferenceHeartbeat(),
            )
        ),
        inference_service_pb2.WatchInferenceResponse(
            message=inference_stream_pb2.InferenceStreamMessage(
                request_name=REQUEST_NAME,
                sequence=2,
                resume_token="cursor-2",
                final_result=inference_stream_pb2.InferenceFinalUpdate(
                    outcome=inference_result_pb2.INFERENCE_RESULT_OUTCOME_SUCCEEDED,
                    result_digest="sha256:" + "a" * 64,
                ),
            )
        ),
    ]


class SyncInferenceTest(unittest.TestCase):
    def test_generated_submit_commit_watch_and_wait(self) -> None:
        transport = FakeSyncTransport()
        captured_submit: list[inference_service_pb2.SubmitInferenceRequest] = []
        captured_commit: list[inference_service_pb2.CommitInferenceResultRequest] = []

        def unary(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            if isinstance(request, inference_service_pb2.SubmitInferenceRequest):
                captured_submit.append(request)
                return inference_service_pb2.SubmitInferenceResponse(operation=operation())
            if isinstance(request, inference_service_pb2.GetInferenceRequestRequest):
                return inference_service_pb2.GetInferenceRequestResponse(
                    inference_request=inference_request_pb2.InferenceRequest(name=REQUEST_NAME)
                )
            if isinstance(request, inference_service_pb2.GetInferenceResultRequest):
                return inference_service_pb2.GetInferenceResultResponse(
                    result=result(), operation=operation()
                )
            if isinstance(request, inference_service_pb2.CommitInferenceResultRequest):
                captured_commit.append(request)
                return inference_service_pb2.CommitInferenceResultResponse(
                    result=result(), operation=operation()
                )
            raise AssertionError(type(request))

        for method in (
            SUBMIT_INFERENCE,
            GET_INFERENCE_REQUEST,
            GET_INFERENCE_RESULT,
            COMMIT_INFERENCE_RESULT,
        ):
            transport.unary_handlers[method] = unary
        transport.stream_handlers[WATCH_INFERENCE] = lambda request, timeout, metadata: (
            stream_messages()
        )
        client = Client(config(), transport=transport)
        request = inference_request_pb2.InferenceRequest(name=REQUEST_NAME)
        submitted = client.inference.submit(
            request,
            options=CallOptions(
                request_id="request-1", trace_id="trace-1", idempotency_key="submit-1"
            ),
        )
        self.assertEqual(submitted.operation_id, OPERATION_NAME)
        self.assertFalse(request.HasField("context"))
        materialized = captured_submit[0].inference_request
        self.assertEqual(materialized.context.principal_id, "principal-1")
        canonical = inference_request_pb2.InferenceRequest()
        canonical.CopyFrom(materialized)
        canonical.ClearField("context")
        self.assertEqual(materialized.context.canonical_request_digest, canonical_digest(canonical))

        commit = inference_service_pb2.CommitInferenceResultRequest(
            inference_request=result().request,
            fence=lease_fencing_pb2.LeaseFence(
                job_id="jobs/job-1",
                run_id="runs/run-1",
                attempt_id="attempts/attempt-1",
                lease_epoch=1,
            ),
            result=result(),
            request_digest="sha256:" + "b" * 64,
        )
        client.inference.commit_result(commit, options=CallOptions(idempotency_key="commit-1"))
        self.assertTrue(captured_commit[0].context.canonical_request_digest)
        messages = list(client.inference.watch(OPERATION_NAME, timeout=1))
        self.assertEqual([item.sequence for item in messages], [1, 1, 2])
        terminal_result, terminal_operation = client.inference.wait(OPERATION_NAME, timeout=1)
        self.assertEqual(terminal_result.name, result().name)
        self.assertEqual(terminal_operation.operation_id, OPERATION_NAME)

    def test_watch_treats_zero_retry_after_as_immediate_retry(self) -> None:
        transport = FakeSyncTransport()
        attempts = 0

        def stream(request: Message, timeout: float, metadata: Metadata) -> list[Message]:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise UnavailableError(
                    "transient inference stream failure",
                    retryable=True,
                    retry_after=0.0,
                )
            return list(stream_messages())

        transport.stream_handlers[WATCH_INFERENCE] = stream
        client = Client(config(), transport=transport)
        messages = list(client.inference.watch(OPERATION_NAME, timeout=1))
        self.assertEqual(attempts, 2)
        self.assertEqual(messages[-1].sequence, 2)

    def test_watch_resumes_after_partial_eof_and_cancels_during_backoff(self) -> None:
        transport = FakeSyncTransport()
        attempts = 0

        def partial_stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> Iterable[Message]:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            messages = stream_messages()
            return messages[:1] if attempts == 1 else messages[1:]

        transport.stream_handlers[WATCH_INFERENCE] = partial_stream
        client = Client(config(), transport=transport)
        messages = list(client.inference.watch(OPERATION_NAME, timeout=1))
        self.assertEqual(attempts, 2)
        self.assertEqual([message.sequence for message in messages], [1, 1, 2])

        cancellation = threading.Event()

        def unavailable(request: Message, timeout: float, metadata: Metadata) -> list[Message]:
            del request, timeout, metadata
            cancellation.set()
            raise UnavailableError(
                "transient inference stream failure",
                retryable=True,
                retry_after=1.0,
            )

        transport.stream_handlers[WATCH_INFERENCE] = unavailable
        with patch("mindclade_internal_sdk.inference.time.sleep") as sleep:
            with self.assertRaises(CancelledError):
                list(
                    client.inference.watch(
                        OPERATION_NAME,
                        timeout=1,
                        cancellation=cancellation,
                    )
                )
            sleep.assert_not_called()


class AsyncInferenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_generated_submit_and_wait(self) -> None:
        transport = FakeAsyncTransport()

        def unary(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            if isinstance(request, inference_service_pb2.SubmitInferenceRequest):
                return inference_service_pb2.SubmitInferenceResponse(operation=operation())
            if isinstance(request, inference_service_pb2.GetInferenceResultRequest):
                return inference_service_pb2.GetInferenceResultResponse(
                    result=result(), operation=operation()
                )
            raise AssertionError(type(request))

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            for message in stream_messages():
                yield message

        transport.unary_handlers[SUBMIT_INFERENCE] = unary
        transport.unary_handlers[GET_INFERENCE_RESULT] = unary
        transport.stream_handlers[WATCH_INFERENCE] = stream
        client = AsyncClient(config(), transport=transport)
        submitted = await client.inference.submit(
            inference_request_pb2.InferenceRequest(name=REQUEST_NAME),
            options=CallOptions(idempotency_key="submit-async"),
        )
        self.assertEqual(submitted.operation_id, OPERATION_NAME)
        terminal_result, terminal_operation = await client.inference.wait(OPERATION_NAME, timeout=1)
        self.assertEqual(terminal_result.name, result().name)
        self.assertEqual(terminal_operation.operation_id, OPERATION_NAME)

    async def test_watch_treats_zero_retry_after_as_immediate_retry(self) -> None:
        transport = FakeAsyncTransport()
        attempts = 0

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise UnavailableError(
                    "transient inference stream failure",
                    retryable=True,
                    retry_after=0.0,
                )
            for message in stream_messages():
                yield message

        transport.stream_handlers[WATCH_INFERENCE] = stream
        client = AsyncClient(config(), transport=transport)
        messages = [message async for message in client.inference.watch(OPERATION_NAME, timeout=1)]
        self.assertEqual(attempts, 2)
        self.assertEqual(messages[-1].sequence, 2)

    async def test_watch_resumes_after_partial_eof_and_cancels_during_backoff(self) -> None:
        transport = FakeAsyncTransport()
        attempts = 0

        async def partial_stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            messages = stream_messages()
            selected = messages[:1] if attempts == 1 else messages[1:]
            for message in selected:
                yield message

        transport.stream_handlers[WATCH_INFERENCE] = partial_stream
        client = AsyncClient(config(), transport=transport)
        messages = [message async for message in client.inference.watch(OPERATION_NAME, timeout=1)]
        self.assertEqual(attempts, 2)
        self.assertEqual([message.sequence for message in messages], [1, 1, 2])

        cancellation = asyncio.Event()

        async def unavailable(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            cancellation.set()
            raise UnavailableError(
                "transient inference stream failure",
                retryable=True,
                retry_after=1.0,
            )
            yield Message()  # pragma: no cover - preserve the async-generator type

        transport.stream_handlers[WATCH_INFERENCE] = unavailable
        with patch("mindclade_internal_sdk.inference.asyncio.sleep") as sleep:
            with self.assertRaises(CancelledError):
                _ = [
                    message
                    async for message in client.inference.watch(
                        OPERATION_NAME,
                        timeout=1,
                        cancellation=cancellation,
                    )
                ]
            sleep.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
