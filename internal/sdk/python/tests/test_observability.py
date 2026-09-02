"""Observer and logging tests: bounded facts only, and never a payload or token."""

from __future__ import annotations

import logging
import unittest
from typing import Any

import grpc
from google.protobuf.message import Message
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import job_pb2
from mindclade_internal_sdk import (
    LOGGER_NAME,
    AsyncClient,
    AuthorizationError,
    CallOptions,
    Client,
    ClientConfig,
    ConfigurationError,
    Environment,
    LoggingObserver,
    RetryPolicy,
    RpcObservation,
    UnavailableError,
    default_observer,
    log_level_from_env,
)
from mindclade_internal_sdk._logging import LOG_LEVELS
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeRpcError, FakeSyncTransport
from mindclade_internal_sdk.transport import GET_JOB, Metadata

BEARER = "Bearer super-secret-access-token"
LEASE = "lease-token-value-abcdef"
JOB_ID = "confidential-job-name"
SECRET_JOB_ID = f"jobs/{JOB_ID}"


def config(**overrides: Any) -> ClientConfig:
    settings: dict[str, Any] = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "principal_id": "principal-1",
        "environment": Environment.LOCAL,
        "endpoint": "127.0.0.1:1",
        "insecure_for_testing": True,
        "default_timeout": 1,
        "retry": RetryPolicy(max_attempts=3, base_delay=0.001, max_delay=0.002),
    }
    settings.update(overrides)
    return ClientConfig(**settings)


def job_response(request: Message, timeout: float, metadata: Metadata) -> Message:
    del request, timeout, metadata
    return job_service_pb2.GetJobResponse(
        job=job_pb2.Job(
            job_id=SECRET_JOB_ID,
            operation_id="operations/op-1",
            tenant_id="tenant-1",
            project_id="project-1",
            state=job_pb2.JOB_STATE_RUNNING,
            resource_version=1,
            etag="etag-1",
        )
    )


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[RpcObservation] = []

    def observe(self, event: RpcObservation) -> None:
        self.events.append(event)


class ExplodingObserver:
    def __init__(self) -> None:
        self.calls = 0

    def observe(self, event: RpcObservation) -> None:
        del event
        self.calls += 1
        raise RuntimeError("telemetry backend is down")


class ObserverTest(unittest.TestCase):
    def test_observer_receives_method_attempt_elapsed_status_and_identity(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        observer = RecordingObserver()
        client = Client(config(), transport=transport, observer=observer)
        client.jobs.get(JOB_ID, options=CallOptions(request_id="req-1", trace_id="trace-1"))
        self.assertEqual(len(observer.events), 1)
        event = observer.events[0]
        self.assertEqual(event.method, GET_JOB)
        self.assertEqual(event.attempt, 1)
        self.assertEqual(event.status, "OK")
        self.assertEqual(event.request_id, "req-1")
        self.assertEqual(event.trace_id, "trace-1")
        self.assertEqual(event.retry_count, 0)
        self.assertEqual(event.cumulative_delay_seconds, 0.0)
        self.assertGreaterEqual(event.elapsed_seconds, 0.0)

    def test_observer_receives_metadata_key_names_only(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        observer = RecordingObserver()
        client = Client(
            config(custom_metadata={"x-team": "platform"}),
            transport=transport,
            observer=observer,
        )
        client.jobs.get(JOB_ID, options=CallOptions(lease_token=LEASE))
        event = observer.events[0]
        self.assertIn("x-mindclade-lease-token", event.metadata_keys)
        self.assertIn("x-team", event.metadata_keys)
        self.assertEqual(list(event.metadata_keys), sorted(event.metadata_keys))
        rendered = repr(event)
        for forbidden in (LEASE, BEARER, "platform", SECRET_JOB_ID):
            self.assertNotIn(forbidden, rendered)

    def test_observer_reports_retry_accounting_across_attempts(self) -> None:
        transport = FakeSyncTransport()
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)
            return job_response(request, timeout, metadata)

        transport.unary_handlers[GET_JOB] = handler
        observer = RecordingObserver()
        client = Client(config(), transport=transport, observer=observer)
        client.jobs.get(JOB_ID)
        self.assertEqual([event.attempt for event in observer.events], [1, 2, 3])
        self.assertEqual([event.retry_count for event in observer.events], [0, 1, 2])
        self.assertEqual([event.status for event in observer.events], ["UNAVAILABLE"] * 2 + ["OK"])
        delays = [event.cumulative_delay_seconds for event in observer.events]
        self.assertEqual(delays, sorted(delays))
        self.assertGreater(delays[-1], 0.0)

    def test_observer_failure_never_breaks_the_call(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        observer = ExplodingObserver()
        client = Client(config(), transport=transport, observer=observer)
        self.assertEqual(client.jobs.get(JOB_ID).job_id, SECRET_JOB_ID)
        self.assertEqual(observer.calls, 1)


class LogLevelTest(unittest.TestCase):
    def test_mindclade_log_levels_map_to_stdlib_levels(self) -> None:
        expected = {
            "error": logging.ERROR,
            "warn": logging.WARNING,
            "warning": logging.WARNING,
            "info": logging.INFO,
            "debug": logging.DEBUG,
            "DEBUG": logging.DEBUG,
            " info ": logging.INFO,
        }
        for raw, level in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(log_level_from_env({"MINDCLADE_LOG": raw}), level)

    def test_off_installs_no_observer_at_all(self) -> None:
        for raw in ("off", "none", "OFF"):
            with self.subTest(raw=raw):
                self.assertIsNone(log_level_from_env({"MINDCLADE_LOG": raw}))
                self.assertIsNone(default_observer({"MINDCLADE_LOG": raw}))

    def test_an_unset_variable_installs_no_observer(self) -> None:
        self.assertIsNone(log_level_from_env({}))
        self.assertIsNone(default_observer({}))

    def test_an_unknown_level_is_a_configuration_error(self) -> None:
        with self.assertRaises(ConfigurationError) as raised:
            log_level_from_env({"MINDCLADE_LOG": "verbose"})
        self.assertIn("debug", str(raised.exception))

    def test_default_observer_uses_the_selected_level(self) -> None:
        observer = default_observer({"MINDCLADE_LOG": "warn"})
        self.assertIsInstance(observer, LoggingObserver)
        assert observer is not None
        self.assertEqual(observer.level, logging.WARNING)

    def test_declared_levels_cover_the_contract(self) -> None:
        self.assertEqual(
            set(LOG_LEVELS), {"off", "none", "error", "warn", "warning", "info", "debug"}
        )


class LoggingObserverTest(unittest.TestCase):
    def test_logging_observer_emits_bounded_facts(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        client = Client(
            config(),
            transport=transport,
            observer=LoggingObserver(level=logging.INFO),
        )
        with self.assertLogs(LOGGER_NAME, level=logging.INFO) as captured:
            client.jobs.get(JOB_ID, options=CallOptions(request_id="req-1", lease_token=LEASE))
        self.assertEqual(len(captured.output), 1)
        line = captured.output[0]
        self.assertIn("method=" + GET_JOB, line)
        self.assertIn("status=OK", line)
        self.assertIn("request_id=req-1", line)
        self.assertIn("retry_count=0", line)
        self.assertIn("metadata_keys=", line)
        self.assertIn("x-mindclade-lease-token", line)

    def test_logging_observer_never_logs_payloads_or_tokens(self) -> None:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        client = Client(
            config(custom_metadata={"x-team": "confidential-team-name"}),
            transport=transport,
            observer=LoggingObserver(level=logging.DEBUG),
        )
        with self.assertLogs(LOGGER_NAME, level=logging.DEBUG) as captured:
            client.jobs.get(JOB_ID, options=CallOptions(lease_token=LEASE))
        line = "\n".join(captured.output)
        for forbidden in (LEASE, BEARER, "confidential-team-name", SECRET_JOB_ID):
            self.assertNotIn(forbidden, line)

    def test_logging_observer_logs_a_failed_attempt_without_provider_detail(self) -> None:
        transport = FakeSyncTransport()

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(
                grpc.StatusCode.PERMISSION_DENIED,
                details="ERROR: permission denied for relation jobs (SQLSTATE 42501)",
            )

        transport.unary_handlers[GET_JOB] = handler
        client = Client(
            config(),
            transport=transport,
            observer=LoggingObserver(level=logging.ERROR),
        )
        with (
            self.assertLogs(LOGGER_NAME, level=logging.ERROR) as captured,
            self.assertRaises(AuthorizationError),
        ):
            client.jobs.get(JOB_ID)
        line = "\n".join(captured.output)
        self.assertIn("status=PERMISSION_DENIED", line)
        self.assertNotIn("SQLSTATE", line)
        self.assertNotIn("relation jobs", line)

    def test_the_sdk_never_configures_the_root_logger(self) -> None:
        sdk_logger = logging.getLogger(LOGGER_NAME)
        LoggingObserver()
        self.assertEqual(sdk_logger.handlers, [])
        self.assertTrue(sdk_logger.propagate)

    def test_a_disabled_level_builds_no_record_at_all(self) -> None:
        quiet = logging.getLogger("mindclade_internal_sdk.test.quiet")
        quiet.propagate = False
        quiet.setLevel(logging.CRITICAL)
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = Capture()
        quiet.addHandler(handler)
        try:
            observer = LoggingObserver(quiet, level=logging.DEBUG)
            observer.observe(
                RpcObservation(
                    method=GET_JOB,
                    attempt=1,
                    elapsed_seconds=0.0,
                    status="OK",
                    request_id="req-1",
                )
            )
        finally:
            quiet.removeHandler(handler)
        self.assertEqual(records, [])


class AsyncObserverTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_observer_receives_the_same_bounded_facts(self) -> None:
        transport = FakeAsyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        observer = RecordingObserver()
        client = AsyncClient(config(), transport=transport, observer=observer)
        await client.jobs.get(JOB_ID, options=CallOptions(request_id="req-1"))
        event = observer.events[0]
        self.assertEqual(event.method, GET_JOB)
        self.assertEqual(event.status, "OK")
        self.assertEqual(event.request_id, "req-1")
        self.assertIn("x-mindclade-sdk", event.metadata_keys)
        self.assertNotIn(SECRET_JOB_ID, repr(event))

    async def test_async_observer_reports_retry_accounting(self) -> None:
        transport = FakeAsyncTransport()
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)
            return job_response(request, timeout, metadata)

        transport.unary_handlers[GET_JOB] = handler
        observer = RecordingObserver()
        client = AsyncClient(config(), transport=transport, observer=observer)
        await client.jobs.get(JOB_ID)
        self.assertEqual([event.retry_count for event in observer.events], [0, 1])
        self.assertGreater(observer.events[-1].cumulative_delay_seconds, 0.0)

    async def test_async_observer_failure_never_breaks_the_call(self) -> None:
        transport = FakeAsyncTransport()
        transport.unary_handlers[GET_JOB] = job_response
        observer = ExplodingObserver()
        client = AsyncClient(config(), transport=transport, observer=observer)
        job = await client.jobs.get(JOB_ID)
        self.assertEqual(job.job_id, SECRET_JOB_ID)
        self.assertEqual(observer.calls, 1)


class UnavailableErrorObservationTest(unittest.TestCase):
    def test_a_terminal_failure_is_observed_on_every_attempt(self) -> None:
        transport = FakeSyncTransport()

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)

        transport.unary_handlers[GET_JOB] = handler
        observer = RecordingObserver()
        client = Client(config(), transport=transport, observer=observer)
        with self.assertRaises(UnavailableError):
            client.jobs.get(JOB_ID)
        self.assertEqual([event.attempt for event in observer.events], [1, 2, 3])
        self.assertTrue(all(event.status == "UNAVAILABLE" for event in observer.events))


if __name__ == "__main__":
    unittest.main()
