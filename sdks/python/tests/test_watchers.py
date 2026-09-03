"""Parity tests for the one resumable watcher every streaming RPC now shares."""

from __future__ import annotations

import threading
import unittest
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from google.protobuf.message import Message
from mindclade.inference.v1 import inference_stream_pb2
from mindclade.internal.inference.v1 import inference_service_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.internal.training.v1 import training_service_pb2
from mindclade.internal.workflow.v1 import workflow_service_pb2
from mindclade.operation.v1 import operation_pb2
from mindclade.training.v1 import training_run_pb2
from mindclade.workflow.v1 import workflow_run_pb2
from mindclade_internal_sdk import (
    AsyncClient,
    CallOptions,
    CancelledError,
    Client,
    ClientConfig,
    Environment,
    FixedJitter,
    OperationTimeoutError,
    ProtocolError,
    RetryPolicy,
    UnavailableError,
)
from mindclade_internal_sdk._watch import (
    MAX_WATCH_ATTEMPT_SECONDS,
    AsyncWatchStream,
    WatchStream,
    watch_budget,
    watch_call,
)
from mindclade_internal_sdk.calls import PreparedCall
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
    WATCH_INFERENCE,
    WATCH_OPERATION,
    WATCH_TRAINING_RUN,
    WATCH_WORKFLOW_RUN,
    Metadata,
)

TENANT = "tenant-1"
PROJECT = "project-1"
PARENT = f"tenants/{TENANT}/projects/{PROJECT}"
OPERATION = "operations/op-1"
TRAINING_RUN = f"{PARENT}/trainingRuns/run-1"
WORKFLOW_RUN = f"{PARENT}/workflowRuns/run-1"
INFERENCE_REQUEST = f"{PARENT}/inferenceRequests/request-1"


def config(**overrides: object) -> ClientConfig:
    settings: dict[str, object] = {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "principal_id": "principal-1",
        "environment": Environment.LOCAL,
        "endpoint": "127.0.0.1:1",
        "insecure_for_testing": True,
        "default_timeout": 1,
        "retry": RetryPolicy(max_attempts=4, base_delay=0.001, max_delay=0.002),
    }
    settings.update(overrides)
    return ClientConfig(**settings)  # pyright: ignore[reportArgumentType]


def operation_event(sequence: int, *, done: bool = False) -> job_service_pb2.WatchOperationResponse:
    state = (
        operation_pb2.OPERATION_STATE_SUCCEEDED if done else operation_pb2.OPERATION_STATE_RUNNING
    )
    return job_service_pb2.WatchOperationResponse(
        sequence=sequence,
        operation=operation_pb2.Operation(
            operation_id=OPERATION,
            tenant_id=TENANT,
            project_id=PROJECT,
            state=state,
            done=done,
        ),
    )


def training_event(
    sequence: int, *, done: bool = False
) -> training_service_pb2.WatchTrainingRunResponse:
    state = (
        training_run_pb2.TRAINING_RUN_STATE_COMPLETED
        if done
        else training_run_pb2.TRAINING_RUN_STATE_RUNNING
    )
    return training_service_pb2.WatchTrainingRunResponse(
        sequence=sequence,
        training_run=training_run_pb2.TrainingRun(name=TRAINING_RUN, state=state),
    )


def workflow_event(
    sequence: int, *, done: bool = False
) -> workflow_service_pb2.WatchWorkflowRunResponse:
    state = (
        workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED
        if done
        else workflow_run_pb2.WORKFLOW_RUN_STATE_RUNNING
    )
    return workflow_service_pb2.WatchWorkflowRunResponse(
        workflow_run=workflow_run_pb2.WorkflowRun(
            name=WORKFLOW_RUN,
            transition_sequence=sequence,
            state=state,
        )
    )


def inference_event(
    sequence: int, *, done: bool = False
) -> inference_service_pb2.WatchInferenceResponse:
    message = inference_stream_pb2.InferenceStreamMessage(
        request_name=INFERENCE_REQUEST,
        sequence=sequence,
        resume_token=f"cursor-{sequence}",
    )
    if done:
        message.final_result.CopyFrom(inference_stream_pb2.InferenceFinalUpdate())
    else:
        message.progress.CopyFrom(inference_stream_pb2.InferenceProgress(lifecycle_state="RUNNING"))
    return inference_service_pb2.WatchInferenceResponse(message=message)


class QuietSyncStream:
    """Yields one event, then blocks until cancelled, so cancellation is observable."""

    def __init__(self, *, first: Message) -> None:
        self.started = threading.Event()
        self.released = threading.Event()
        self.cancel_count = 0
        self._first: Message | None = first

    def __iter__(self) -> QuietSyncStream:
        return self

    def __next__(self) -> Message:
        if self._first is not None:
            first, self._first = self._first, None
            return first
        self.started.set()
        self.released.wait(timeout=5)
        raise StopIteration

    def cancel(self) -> bool:
        self.cancel_count += 1
        self.released.set()
        return True


class WatchCallTest(unittest.TestCase):
    def test_watch_call_preserves_lease_token_and_idempotency_key(self) -> None:
        base = PreparedCall(
            timeout=300.0,
            request_id="request-1",
            trace_id="trace-1",
            idempotency_key="key-1",
            lease_token="lease-1",
        )
        derived = watch_call(base, 12.5)
        self.assertEqual(derived.timeout, 12.5)
        self.assertEqual(derived.request_id, "request-1")
        self.assertEqual(derived.trace_id, "trace-1")
        self.assertEqual(derived.idempotency_key, "key-1")
        self.assertEqual(derived.lease_token, "lease-1")

    def test_watch_call_clamps_one_attempt_without_shortening_identity(self) -> None:
        base = PreparedCall(
            timeout=1.0,
            request_id="request-1",
            trace_id="trace-1",
            idempotency_key=None,
        )
        self.assertEqual(watch_call(base, 10_000.0).timeout, MAX_WATCH_ATTEMPT_SECONDS)
        self.assertEqual(watch_call(base, -5.0).timeout, 0.001)

    def test_watch_budget_intersects_the_per_request_timeout(self) -> None:
        _, wide = watch_budget(60.0, CallOptions(timeout=5.0))
        self.assertEqual(wide, 5.0)
        _, narrow = watch_budget(3.0, CallOptions(timeout=30.0))
        self.assertEqual(narrow, 3.0)
        _, plain = watch_budget(7.0, None)
        self.assertEqual(plain, 7.0)

    def test_watch_budget_rejects_an_unbounded_timeout(self) -> None:
        for timeout in (0.0, -1.0, 86_401.0):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "watch timeout"):
                watch_budget(timeout, None)


class SyncWatcherTest(unittest.TestCase):
    def test_generic_watcher_resumes_from_the_last_acknowledged_cursor(self) -> None:
        transport = FakeSyncTransport()
        cursors: list[int] = []
        attempts = 0

        def stream(request: Message, timeout: float, metadata: Metadata) -> Iterable[Message]:
            del timeout, metadata
            nonlocal attempts
            attempts += 1
            typed = request
            assert isinstance(typed, job_service_pb2.WatchOperationRequest)
            cursors.append(typed.after_sequence)
            if attempts == 1:
                return [operation_event(1), operation_event(2)]
            return [operation_event(3, done=True)]

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = Client(config(), transport=transport)
        events = list(client.operations.watch(OPERATION, timeout=1))
        self.assertEqual([event.sequence for event in events], [1, 2, 3])
        self.assertEqual(cursors, [0, 2])

    def test_watch_reconnects_only_within_the_remaining_deadline(self) -> None:
        transport = FakeSyncTransport()

        def stream(request: Message, timeout: float, metadata: Metadata) -> Iterable[Message]:
            del request, timeout, metadata
            return []

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = Client(config(), transport=transport)
        with self.assertRaises(UnavailableError):
            list(client.operations.watch(OPERATION, timeout=1))
        timeouts = [call.timeout for call in transport.calls if call.method == WATCH_OPERATION]
        self.assertEqual(len(timeouts), 4)
        self.assertEqual(timeouts, sorted(timeouts, reverse=True))
        self.assertLessEqual(timeouts[0], 1.0)
        self.assertGreater(timeouts[-1], 0.0)

    def test_watch_raises_the_domain_timeout_once_the_budget_is_spent(self) -> None:
        transport = FakeSyncTransport()
        transport.stream_handlers[WATCH_OPERATION] = lambda request, timeout, metadata: []
        # Attempts are plentiful and the budget is not: a spent deadline must
        # outrank an unspent attempt count, so the caller learns they timed out.
        policy = RetryPolicy(
            max_attempts=8,
            base_delay=0.1,
            max_delay=0.1,
            jitter=FixedJitter(1.0),
        )
        client = Client(config(retry=policy), transport=transport)
        with self.assertRaises(OperationTimeoutError):
            list(client.operations.watch(OPERATION, timeout=0.15))
        attempts = [call for call in transport.calls if call.method == WATCH_OPERATION]
        self.assertLess(len(attempts), policy.max_attempts)

    def test_watch_preserves_sequence_and_identity_checks(self) -> None:
        cases: tuple[tuple[str, Message], ...] = (
            ("non-advancing sequence", operation_event(0)),
            (
                "wrong operation",
                job_service_pb2.WatchOperationResponse(
                    sequence=1,
                    operation=operation_pb2.Operation(
                        operation_id="operations/other",
                        state=operation_pb2.OPERATION_STATE_RUNNING,
                    ),
                ),
            ),
        )
        for label, event in cases:
            with self.subTest(label=label):
                transport = FakeSyncTransport()
                transport.stream_handlers[WATCH_OPERATION] = (
                    lambda request, timeout, metadata, event=event: [event]
                )
                client = Client(config(), transport=transport)
                with self.assertRaises(ProtocolError):
                    list(client.operations.watch(OPERATION, timeout=1))

    def test_workflow_watch_preserves_its_contiguity_check(self) -> None:
        transport = FakeSyncTransport()
        transport.stream_handlers[WATCH_WORKFLOW_RUN] = lambda request, timeout, metadata: [
            workflow_event(2)
        ]
        client = Client(config(), transport=transport)
        with self.assertRaisesRegex(ProtocolError, "non-contiguous"):
            list(client.workflows.watch(WORKFLOW_RUN, timeout=1))

    def test_training_watch_preserves_its_contiguity_check(self) -> None:
        transport = FakeSyncTransport()
        transport.stream_handlers[WATCH_TRAINING_RUN] = lambda request, timeout, metadata: [
            training_event(3)
        ]
        client = Client(config(), transport=transport)
        with self.assertRaisesRegex(ProtocolError, "not contiguous"):
            list(client.training.watch(TRAINING_RUN, timeout=1))

    def test_watch_carries_the_caller_lease_token_on_every_attempt(self) -> None:
        transport = FakeSyncTransport()
        attempts = 0

        def stream(request: Message, timeout: float, metadata: Metadata) -> Iterable[Message]:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return []
            return [operation_event(1, done=True)]

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = Client(config(), transport=transport)
        events = list(
            client.operations.watch(
                OPERATION,
                timeout=1,
                options=CallOptions(lease_token="lease-1", idempotency_key="key-1"),
            )
        )
        self.assertEqual(len(events), 1)
        stream_calls = [call for call in transport.calls if call.method == WATCH_OPERATION]
        self.assertEqual(len(stream_calls), 2)
        for call in stream_calls:
            self.assertIn("x-mindclade-lease-token", call.metadata_keys)
            self.assertIn("idempotency-key", call.metadata_keys)

    def test_every_watcher_honours_call_options(self) -> None:
        parent = PARENT
        watchers: tuple[tuple[str, str, Callable[[Client, CallOptions], Any]], ...] = (
            (
                "operation",
                WATCH_OPERATION,
                lambda client, options: client.operations.watch(
                    OPERATION, timeout=60, options=options
                ),
            ),
            (
                "training",
                WATCH_TRAINING_RUN,
                lambda client, options: client.training.watch(
                    f"{parent}/trainingRuns/run-1", timeout=60, options=options
                ),
            ),
            (
                "inference",
                WATCH_INFERENCE,
                lambda client, options: client.inference.watch(
                    OPERATION, timeout=60, options=options
                ),
            ),
            (
                "workflow",
                WATCH_WORKFLOW_RUN,
                lambda client, options: client.workflows.watch(
                    WORKFLOW_RUN, timeout=60, options=options
                ),
            ),
        )
        for label, method, build in watchers:
            with self.subTest(label=label):
                transport = FakeSyncTransport()
                transport.stream_handlers[method] = lambda request, timeout, metadata: []
                client = Client(config(), transport=transport)
                options = CallOptions(timeout=0.5, request_id="request-1", trace_id="trace-1")
                stream = build(client, options)
                self.assertEqual(stream.request_id, "request-1")
                self.assertEqual(stream.trace_id, "trace-1")
                with self.assertRaises((UnavailableError, OperationTimeoutError, TimeoutError)):
                    list(stream)
                calls = [call for call in transport.calls if call.method == method]
                self.assertGreaterEqual(len(calls), 1)
                # The 60-second watch timeout is narrowed by the option, never widened.
                self.assertLessEqual(calls[0].timeout, 0.5)

    def test_watch_stream_is_a_context_manager_that_stops_reconnecting(self) -> None:
        transport = FakeSyncTransport()
        transport.stream_handlers[WATCH_OPERATION] = lambda request, timeout, metadata: [
            operation_event(1),
            operation_event(2),
        ]
        client = Client(config(), transport=transport)
        with client.operations.watch(OPERATION, timeout=1) as events:
            self.assertEqual(next(events).sequence, 1)
        self.assertEqual(len([c for c in transport.calls if c.method == WATCH_OPERATION]), 1)

    def test_watch_stream_exposes_its_last_acknowledged_cursor(self) -> None:
        transport = FakeSyncTransport()
        transport.stream_handlers[WATCH_OPERATION] = lambda request, timeout, metadata: [
            operation_event(1),
            operation_event(7),
        ]
        client = Client(config(), transport=transport)
        with client.operations.watch(OPERATION, timeout=1) as events:
            self.assertEqual(events.cursor, 0)
            next(events)
            self.assertEqual(events.cursor, 1)
            next(events)
            self.assertEqual(events.cursor, 7)

    def test_leaving_the_context_cancels_the_live_call(self) -> None:
        transport = FakeSyncTransport()
        quiet = QuietSyncStream(first=operation_event(1))
        transport.stream_handlers[WATCH_OPERATION] = lambda request, timeout, metadata: quiet
        client = Client(config(), transport=transport)
        with client.operations.watch(OPERATION, timeout=5) as events:
            self.assertEqual(next(events).sequence, 1)
            self.assertEqual(quiet.cancel_count, 0)
        self.assertEqual(quiet.cancel_count, 1)

    def test_resume_watch_requires_an_explicit_cursor(self) -> None:
        transport = FakeSyncTransport()
        seen: list[int] = []

        def stream(request: Message, timeout: float, metadata: Metadata) -> Iterable[Message]:
            del timeout, metadata
            assert isinstance(request, job_service_pb2.WatchOperationRequest)
            seen.append(request.after_sequence)
            return [operation_event(9, done=True)]

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = Client(config(), transport=transport)
        with self.assertRaises(TypeError):
            client.operations.resume_watch(OPERATION, timeout=1)  # pyright: ignore[reportCallIssue]
        events = list(client.operations.resume_watch(OPERATION, after_sequence=8, timeout=1))
        self.assertEqual([event.sequence for event in events], [9])
        self.assertEqual(seen, [8])

    def test_resume_watch_rejects_a_negative_cursor(self) -> None:
        client = Client(config(), transport=FakeSyncTransport())
        with self.assertRaisesRegex(ValueError, "after_sequence"):
            client.operations.resume_watch(OPERATION, after_sequence=-1)

    def test_watch_surfaces_the_underlying_cause_when_retries_run_out(self) -> None:
        transport = FakeSyncTransport()

        def stream(request: Message, timeout: float, metadata: Metadata) -> Iterable[Message]:
            del request, timeout, metadata
            raise UnavailableError("workflow backend is draining", retryable=True, retry_after=0.0)

        transport.stream_handlers[WATCH_WORKFLOW_RUN] = stream
        client = Client(config(), transport=transport)
        with self.assertRaises(UnavailableError) as raised:
            list(client.workflows.watch(WORKFLOW_RUN, timeout=1))
        self.assertIn("draining", str(raised.exception))

    def test_pre_set_cancellation_never_opens_a_stream(self) -> None:
        transport = FakeSyncTransport()
        transport.stream_handlers[WATCH_OPERATION] = lambda request, timeout, metadata: []
        client = Client(config(), transport=transport)
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaises(CancelledError):
            client.operations.watch(OPERATION, timeout=1, cancellation=cancellation)
        self.assertEqual(transport.calls, [])

    def test_watch_returns_a_watch_stream_on_every_domain(self) -> None:
        client = Client(config(), transport=FakeSyncTransport())
        self.assertIsInstance(client.operations.watch(OPERATION, timeout=1), WatchStream)
        self.assertIsInstance(client.training.watch(TRAINING_RUN, timeout=1), WatchStream)
        self.assertIsInstance(client.inference.watch(OPERATION, timeout=1), WatchStream)
        self.assertIsInstance(client.workflows.watch(WORKFLOW_RUN, timeout=1), WatchStream)


class AsyncWatcherTest(unittest.IsolatedAsyncioTestCase):
    async def test_generic_watcher_resumes_from_the_last_acknowledged_cursor(self) -> None:
        transport = FakeAsyncTransport()
        cursors: list[int] = []
        attempts = 0

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del timeout, metadata
            nonlocal attempts
            attempts += 1
            assert isinstance(request, job_service_pb2.WatchOperationRequest)
            cursors.append(request.after_sequence)
            events = (
                [operation_event(1), operation_event(2)]
                if attempts == 1
                else [operation_event(3, done=True)]
            )
            for event in events:
                yield event

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = AsyncClient(config(), transport=transport)
        events = [event async for event in client.operations.watch(OPERATION, timeout=1)]
        self.assertEqual([event.sequence for event in events], [1, 2, 3])
        self.assertEqual(cursors, [0, 2])

    async def test_async_watch_stream_is_an_async_context_manager(self) -> None:
        transport = FakeAsyncTransport()

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            for event in (operation_event(1), operation_event(2)):
                yield event

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = AsyncClient(config(), transport=transport)
        async with client.operations.watch(OPERATION, timeout=1) as events:
            first = await events.__anext__()
            self.assertEqual(first.sequence, 1)
            self.assertEqual(events.cursor, 1)
        self.assertEqual(len([c for c in transport.calls if c.method == WATCH_OPERATION]), 1)

    async def test_async_resume_watch_requires_an_explicit_cursor(self) -> None:
        transport = FakeAsyncTransport()
        seen: list[int] = []

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del timeout, metadata
            assert isinstance(request, job_service_pb2.WatchOperationRequest)
            seen.append(request.after_sequence)
            yield operation_event(5, done=True)

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = AsyncClient(config(), transport=transport)
        events = [
            event
            async for event in client.operations.resume_watch(
                OPERATION, after_sequence=4, timeout=1
            )
        ]
        self.assertEqual([event.sequence for event in events], [5])
        self.assertEqual(seen, [4])

    async def test_async_watch_carries_the_caller_lease_token(self) -> None:
        transport = FakeAsyncTransport()

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            yield operation_event(1, done=True)

        transport.stream_handlers[WATCH_OPERATION] = stream
        client = AsyncClient(config(), transport=transport)
        events = [
            event
            async for event in client.operations.watch(
                OPERATION, timeout=1, options=CallOptions(lease_token="lease-1")
            )
        ]
        self.assertEqual(len(events), 1)
        call = next(c for c in transport.calls if c.method == WATCH_OPERATION)
        self.assertIn("x-mindclade-lease-token", call.metadata_keys)

    async def test_async_watch_surfaces_the_underlying_cause(self) -> None:
        transport = FakeAsyncTransport()

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del request, timeout, metadata
            raise UnavailableError("inference backend is draining", retryable=True, retry_after=0.0)
            yield  # pragma: no cover - unreachable, keeps this an async generator

        transport.stream_handlers[WATCH_INFERENCE] = stream
        client = AsyncClient(config(), transport=transport)
        with self.assertRaises(UnavailableError) as raised:
            _ = [message async for message in client.inference.watch(OPERATION, timeout=1)]
        self.assertIn("draining", str(raised.exception))

    async def test_async_watch_returns_a_stream_on_every_domain(self) -> None:
        client = AsyncClient(config(), transport=FakeAsyncTransport())
        self.assertIsInstance(client.operations.watch(OPERATION, timeout=1), AsyncWatchStream)
        self.assertIsInstance(client.training.watch(TRAINING_RUN, timeout=1), AsyncWatchStream)
        self.assertIsInstance(client.inference.watch(OPERATION, timeout=1), AsyncWatchStream)
        self.assertIsInstance(client.workflows.watch(WORKFLOW_RUN, timeout=1), AsyncWatchStream)

    async def test_async_inference_watch_resumes_from_its_durable_cursor(self) -> None:
        transport = FakeAsyncTransport()
        cursors: list[str] = []
        attempts = 0

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del timeout, metadata
            nonlocal attempts
            attempts += 1
            assert isinstance(request, inference_service_pb2.WatchInferenceRequest)
            cursors.append(request.cursor.resume_token)
            if attempts == 1:
                yield inference_event(1)
                return
            yield inference_event(2, done=True)

        transport.stream_handlers[WATCH_INFERENCE] = stream
        client = AsyncClient(config(), transport=transport)
        messages = [message async for message in client.inference.watch(OPERATION, timeout=1)]
        self.assertEqual([message.sequence for message in messages], [1, 2])
        self.assertEqual(cursors, ["", "cursor-1"])


if __name__ == "__main__":
    unittest.main()
