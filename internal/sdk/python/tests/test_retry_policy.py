from __future__ import annotations

import asyncio
import time
import unittest
from datetime import UTC, datetime, timedelta

import grpc
from google.protobuf.message import Message
from mindclade.internal.agent.v1 import agent_service_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import operation_pb2
from mindclade_internal_sdk import (
    AccessToken,
    AsyncClient,
    CallOptions,
    Client,
    ClientConfig,
    DeadlineExceededError,
    Environment,
    FixedJitter,
    RetryPolicy,
    SystemJitter,
    TransportError,
    UnavailableError,
)
from mindclade_internal_sdk._invocation import SyncInvoker, canonical_digest, command_context
from mindclade_internal_sdk._retry import DEFAULT_JITTER, retry_delay, should_retry
from mindclade_internal_sdk.calls import PreparedCall, prepare_call
from mindclade_internal_sdk.method_policy import (
    COMMIT_AGENT_STEP,
    IDEMPOTENT_MUTATION_METHODS,
    NEVER_RETRY_METHODS,
    SAFE_UNARY_METHODS,
    retry_permitted,
)
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeRpcError, FakeSyncTransport
from mindclade_internal_sdk.transport import EXPIRE_ATTEMPT_LEASES, GET_OPERATION, Metadata

OPERATION_NAME = "operations/op-1"


class SyncCredentials:
    """A workload-identity provider whose latency the test controls."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0

    def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return AccessToken("test-only-token", datetime.now(UTC) + timedelta(minutes=5))


class AsyncCredentials:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0

    async def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return AccessToken("test-only-token", datetime.now(UTC) + timedelta(minutes=5))


def config(
    *,
    retry: RetryPolicy | None = None,
    token_provider: object | None = None,
) -> ClientConfig:
    """Build a loopback client config; retries are jittered deterministically."""

    policy = retry or RetryPolicy(
        max_attempts=4,
        base_delay=0.001,
        max_delay=0.002,
        jitter=FixedJitter(1.0),
    )
    if token_provider is None:
        return ClientConfig(
            tenant_id="tenant-1",
            project_id="project-1",
            principal_id="principal-1",
            environment=Environment.LOCAL,
            endpoint="127.0.0.1:9443",
            insecure_for_testing=True,
            retry=policy,
            default_timeout=5.0,
        )
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:9443",
        token_provider=token_provider,  # type: ignore[arg-type]
        retry=policy,
        default_timeout=5.0,
    )


def succeeded() -> job_service_pb2.GetOperationResponse:
    return job_service_pb2.GetOperationResponse(
        operation=operation_pb2.Operation(
            operation_id=OPERATION_NAME,
            state=operation_pb2.OPERATION_STATE_SUCCEEDED,
            done=True,
        )
    )


class RetryDelayPolicyTest(unittest.TestCase):
    def test_full_jitter_is_bounded_by_cap_and_remaining(self) -> None:
        policy = RetryPolicy(max_attempts=4, base_delay=0.1, max_delay=2.0)
        for failures in range(1, 9):
            expected_cap = min(2.0, 0.1 * (2 ** (failures - 1)))
            self.assertAlmostEqual(
                retry_delay(policy, failures, 30.0, jitter=FixedJitter(1.0)),
                expected_cap,
            )
            self.assertEqual(retry_delay(policy, failures, 30.0, jitter=FixedJitter(0.0)), 0.0)
            self.assertAlmostEqual(
                retry_delay(policy, failures, 0.05, jitter=FixedJitter(1.0)),
                min(expected_cap, 0.05),
            )
            sampled = retry_delay(policy, failures, 30.0)
            self.assertGreaterEqual(sampled, 0.0)
            self.assertLessEqual(sampled, expected_cap)

    def test_delay_is_zero_when_no_budget_remains(self) -> None:
        policy = RetryPolicy(base_delay=0.1, max_delay=2.0)
        self.assertEqual(retry_delay(policy, 1, 0.0, jitter=FixedJitter(1.0)), 0.0)
        self.assertEqual(retry_delay(policy, 1, -5.0, jitter=FixedJitter(1.0)), 0.0)

    def test_server_hint_is_clamped_to_max_delay_and_still_jittered(self) -> None:
        policy = RetryPolicy(base_delay=0.1, max_delay=2.0)
        # A hint far beyond max_backoff collapses onto the cap exactly.
        for jitter in (FixedJitter(0.0), FixedJitter(1.0)):
            self.assertAlmostEqual(
                retry_delay(policy, 1, 30.0, retry_after=10.0, jitter=jitter),
                2.0,
            )
        # A small hint becomes the floor; the exponential headroom is jittered.
        self.assertAlmostEqual(
            retry_delay(policy, 1, 30.0, retry_after=0.05, jitter=FixedJitter(0.0)),
            0.05,
        )
        self.assertAlmostEqual(
            retry_delay(policy, 1, 30.0, retry_after=0.05, jitter=FixedJitter(1.0)),
            0.1,
        )
        zero_hint = retry_delay(policy, 1, 30.0, retry_after=0.0, jitter=FixedJitter(0.0))
        self.assertEqual(zero_hint, 0.0)
        # The remaining budget still wins over a generous hint.
        self.assertAlmostEqual(
            retry_delay(policy, 1, 0.25, retry_after=10.0, jitter=FixedJitter(1.0)),
            0.25,
        )

    def test_policy_jitter_is_used_when_no_explicit_source_is_given(self) -> None:
        policy = RetryPolicy(base_delay=0.1, max_delay=2.0, jitter=FixedJitter(0.5))
        self.assertAlmostEqual(retry_delay(policy, 1, 30.0), 0.05)

    def test_default_jitter_is_cryptographically_seeded(self) -> None:
        self.assertIsInstance(DEFAULT_JITTER, SystemJitter)
        self.assertEqual(DEFAULT_JITTER.uniform(0.0), 0.0)
        self.assertEqual(DEFAULT_JITTER.uniform(-1.0), 0.0)
        for _ in range(64):
            self.assertLessEqual(DEFAULT_JITTER.uniform(0.25), 0.25)

    def test_fixed_jitter_rejects_a_fraction_outside_the_unit_interval(self) -> None:
        with self.assertRaises(ValueError):
            FixedJitter(1.5)

    def test_should_retry_honours_budget_attempts_and_server_override(self) -> None:
        self.assertTrue(
            should_retry(retryable=True, server_override=None, attempt=1, attempts=4, remaining=1.0)
        )
        self.assertFalse(
            should_retry(retryable=True, server_override=None, attempt=4, attempts=4, remaining=1.0)
        )
        self.assertFalse(
            should_retry(retryable=True, server_override=None, attempt=1, attempts=4, remaining=0.0)
        )
        self.assertFalse(
            should_retry(
                retryable=True, server_override=False, attempt=1, attempts=4, remaining=1.0
            )
        )
        self.assertTrue(
            should_retry(
                retryable=False, server_override=True, attempt=1, attempts=4, remaining=1.0
            )
        )


class SyncRetryLoopTest(unittest.TestCase):
    def _client(self, handler: object, **kwargs: object) -> tuple[Client, FakeSyncTransport]:
        transport = FakeSyncTransport()
        transport.unary_handlers[GET_OPERATION] = handler  # type: ignore[assignment]
        client = Client(config(**kwargs), transport=transport)  # type: ignore[arg-type]
        self.addCleanup(client.close)
        return client, transport

    def test_should_retry_trailer_forbids_retry_of_a_retryable_status(self) -> None:
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(
                grpc.StatusCode.UNAVAILABLE,
                (("x-mindclade-should-retry", "false"),),
            )

        client, _ = self._client(handler)
        with self.assertRaises(UnavailableError) as raised:
            client.operations.get(OPERATION_NAME)
        self.assertEqual(attempts, 1)
        self.assertFalse(raised.exception.retryable)
        self.assertIs(raised.exception.server_should_retry, False)

    def test_should_retry_trailer_permits_retry_of_a_non_retryable_status(self) -> None:
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(
                grpc.StatusCode.INTERNAL,
                (("x-mindclade-should-retry", "true"),),
            )

        client, _ = self._client(handler)
        with self.assertRaises(TransportError) as raised:
            client.operations.get(OPERATION_NAME)
        self.assertEqual(attempts, 4)
        self.assertIs(raised.exception.server_should_retry, True)

    def test_should_retry_trailer_never_promotes_a_non_idempotent_call(self) -> None:
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(
                grpc.StatusCode.UNAVAILABLE,
                (("x-mindclade-should-retry", "true"),),
            )

        transport = FakeSyncTransport()
        transport.unary_handlers[GET_OPERATION] = handler
        invoker = SyncInvoker(config(), transport)
        call = prepare_call(None, default_timeout=2.0, require_idempotency=False)
        with self.assertRaises(UnavailableError):
            invoker.unary(
                GET_OPERATION,
                job_service_pb2.GetOperationRequest(name=OPERATION_NAME),
                call=call,
                retry_safe=False,
            )
        self.assertEqual(attempts, 1)

    def test_unparsable_should_retry_trailer_is_ignored(self) -> None:
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(
                grpc.StatusCode.UNAVAILABLE,
                (("x-mindclade-should-retry", "maybe"),),
            )

        client, _ = self._client(handler)
        with self.assertRaises(UnavailableError) as raised:
            client.operations.get(OPERATION_NAME)
        self.assertEqual(attempts, 4)
        self.assertIsNone(raised.exception.server_should_retry)

    def test_retry_count_and_timeout_metadata_on_every_attempt(self) -> None:
        observed: list[dict[str, str]] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout
            observed.append({key: str(value) for key, value in metadata})
            if len(observed) < 3:
                raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)
            return succeeded()

        client, _ = self._client(handler)
        client.operations.get(OPERATION_NAME, options=CallOptions(timeout=2.0))
        self.assertEqual([entry["x-mindclade-retry-count"] for entry in observed], ["0", "1", "2"])
        budgets = [int(entry["x-mindclade-timeout-ms"]) for entry in observed]
        self.assertTrue(all(budget >= 0 for budget in budgets))
        self.assertLessEqual(budgets[0], 2000)
        self.assertEqual(budgets, sorted(budgets, reverse=True))
        self.assertGreater(budgets[0], budgets[-1])

    def test_per_request_max_attempts_narrows_but_never_widens(self) -> None:
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)

        client, _ = self._client(handler)
        with self.assertRaises(UnavailableError):
            client.operations.get(OPERATION_NAME, options=CallOptions(max_attempts=2))
        self.assertEqual(attempts, 2)

        attempts = 0
        narrow, _ = self._client(
            handler,
            retry=RetryPolicy(
                max_attempts=3, base_delay=0.001, max_delay=0.002, jitter=FixedJitter(1.0)
            ),
        )
        with self.assertRaises(UnavailableError):
            narrow.operations.get(OPERATION_NAME, options=CallOptions(max_attempts=8))
        self.assertEqual(attempts, 3)

    def test_call_options_reject_an_out_of_range_max_attempts(self) -> None:
        for value in (0, 9, -1):
            with self.assertRaises(ValueError):
                CallOptions(max_attempts=value)

    def test_retry_trace_is_observable_on_the_raised_error(self) -> None:
        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)

        client, _ = self._client(handler)
        with self.assertRaises(UnavailableError) as raised:
            client.operations.get(OPERATION_NAME)
        trace = raised.exception.retry_trace
        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertEqual(trace.attempts, 4)
        self.assertGreater(trace.cumulative_delay_seconds, 0.0)
        self.assertEqual(trace.cause, "UNAVAILABLE")

    def test_retry_trace_records_a_single_attempt_for_a_terminal_status(self) -> None:
        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(grpc.StatusCode.NOT_FOUND)

        client, _ = self._client(handler)
        with self.assertRaises(Exception) as raised:
            client.operations.get(OPERATION_NAME)
        trace = getattr(raised.exception, "retry_trace", None)
        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertEqual(trace.attempts, 1)
        self.assertEqual(trace.cumulative_delay_seconds, 0.0)
        self.assertEqual(trace.cause, "NOT_FOUND")

    def test_timeout_is_a_total_budget_across_attempts(self) -> None:
        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise FakeRpcError(grpc.StatusCode.UNAVAILABLE, (("retry-after-ms", "40"),))

        client, transport = self._client(
            handler,
            retry=RetryPolicy(
                max_attempts=8, base_delay=0.01, max_delay=0.05, jitter=FixedJitter(1.0)
            ),
        )
        started = time.monotonic()
        with self.assertRaises(UnavailableError):
            client.operations.get(OPERATION_NAME, options=CallOptions(timeout=0.2))
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        timeouts = [call.timeout for call in transport.calls]
        self.assertTrue(all(value <= 0.2 for value in timeouts))
        self.assertEqual(timeouts, sorted(timeouts, reverse=True))

    def test_timeout_budget_covers_credential_acquisition(self) -> None:
        credentials = SyncCredentials(delay=0.2)

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            raise AssertionError("the deadline expired before any RPC should have started")

        transport = FakeSyncTransport()
        transport.unary_handlers[GET_OPERATION] = handler
        client = Client(config(token_provider=credentials), transport=transport)
        self.addCleanup(client.close)
        with self.assertRaises(DeadlineExceededError):
            client.operations.get(OPERATION_NAME, options=CallOptions(timeout=0.05))
        self.assertEqual(transport.calls, [])
        self.assertEqual(credentials.calls, 1)


class ExpireAttemptLeasesTest(unittest.TestCase):
    def test_expire_attempt_leases_is_never_retried(self) -> None:
        client_config = config()
        call = prepare_call(
            CallOptions(idempotency_key="idem-1"),
            default_timeout=2.0,
            require_idempotency=True,
        )
        request = job_service_pb2.ExpireAttemptLeasesRequest(
            parent="tenants/tenant-1/projects/project-1",
            limit=10,
        )
        request.context.request_id = call.request_id
        request.context.idempotency_key = call.idempotency_key or ""
        request.context.principal_id = client_config.principal_id
        request.context.tenant_id = client_config.tenant_id
        request.context.project_id = client_config.project_id
        self.assertFalse(retry_permitted(EXPIRE_ATTEMPT_LEASES, request, call, client_config))

        attempts = 0

        def handler(inbound: Message, timeout: float, metadata: Metadata) -> Message:
            del inbound, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)

        transport = FakeSyncTransport()
        transport.unary_handlers[EXPIRE_ATTEMPT_LEASES] = handler
        client = Client(client_config, transport=transport)
        self.addCleanup(client.close)
        with self.assertRaises(UnavailableError):
            client.generated.unary(EXPIRE_ATTEMPT_LEASES, request)
        self.assertEqual(attempts, 1)

    def test_the_never_retry_table_outranks_verified_command_intent(self) -> None:
        """A perfectly-formed CommandContext must not promote the raw-only RPC.

        ``ExpireAttemptLeasesRequest`` embeds a ``CommandContext`` exactly like
        every retryable mutation, so omission from the mutation tables is not a
        durable guarantee. The never-retry tier is checked first and is what
        actually holds the contract's "MUST NEVER be retried".
        """

        client_config = config()
        call = prepare_call(
            CallOptions(idempotency_key="k" * 32),
            default_timeout=2.0,
            require_idempotency=True,
        )
        request = job_service_pb2.ExpireAttemptLeasesRequest(
            parent="tenants/tenant-1/projects/project-1",
            limit=5,
        )
        unsigned = job_service_pb2.ExpireAttemptLeasesRequest()
        unsigned.CopyFrom(request)
        unsigned.ClearField("context")
        request.context.CopyFrom(
            command_context(client_config, call, request_digest=canonical_digest(unsigned))
        )
        self.assertFalse(retry_permitted(EXPIRE_ATTEMPT_LEASES, request, call, client_config))
        self.assertIn(EXPIRE_ATTEMPT_LEASES, NEVER_RETRY_METHODS)
        self.assertNotIn(EXPIRE_ATTEMPT_LEASES, IDEMPOTENT_MUTATION_METHODS)
        self.assertNotIn(EXPIRE_ATTEMPT_LEASES, SAFE_UNARY_METHODS)

    def test_the_three_retry_tiers_never_overlap(self) -> None:
        self.assertEqual(SAFE_UNARY_METHODS & IDEMPOTENT_MUTATION_METHODS, frozenset())
        self.assertEqual(SAFE_UNARY_METHODS & NEVER_RETRY_METHODS, frozenset())
        self.assertEqual(IDEMPOTENT_MUTATION_METHODS & NEVER_RETRY_METHODS, frozenset())


class DeclaredMutationTableTest(unittest.TestCase):
    """The escape hatch and the ergonomic facades must agree on one RPC's safety."""

    def _signed_commit_agent_step(
        self,
    ) -> tuple[agent_service_pb2.CommitAgentStepRequest, PreparedCall, ClientConfig]:
        client_config = config()
        call = prepare_call(
            CallOptions(idempotency_key="j" * 32),
            default_timeout=2.0,
            require_idempotency=True,
        )
        request = agent_service_pb2.CommitAgentStepRequest(
            run_etag="etag-1",
            expected_next_step_sequence=2,
        )
        unsigned = agent_service_pb2.CommitAgentStepRequest()
        unsigned.CopyFrom(request)
        unsigned.ClearField("context")
        request.context.CopyFrom(
            command_context(client_config, call, request_digest=canonical_digest(unsigned))
        )
        return request, call, client_config

    def test_a_verified_agent_mutation_is_retryable_through_the_escape_hatch(self) -> None:
        """``client.agents.commit_step`` retries, so the same RPC must retry here too."""

        request, call, client_config = self._signed_commit_agent_step()
        self.assertIn(COMMIT_AGENT_STEP, IDEMPOTENT_MUTATION_METHODS)
        self.assertTrue(retry_permitted(COMMIT_AGENT_STEP, request, call, client_config))

    def test_an_agent_mutation_without_command_intent_is_not_retryable(self) -> None:
        _, call, client_config = self._signed_commit_agent_step()
        bare = agent_service_pb2.CommitAgentStepRequest(
            run_etag="etag-1",
            expected_next_step_sequence=2,
        )
        self.assertFalse(retry_permitted(COMMIT_AGENT_STEP, bare, call, client_config))

    def test_a_tampered_agent_mutation_is_not_retryable(self) -> None:
        request, call, client_config = self._signed_commit_agent_step()
        tampered = agent_service_pb2.CommitAgentStepRequest()
        tampered.CopyFrom(request)
        tampered.run_etag = "etag-tampered"
        self.assertFalse(retry_permitted(COMMIT_AGENT_STEP, tampered, call, client_config))

    def test_an_undeclared_mutation_route_fails_closed(self) -> None:
        """A route reachable through the dispatch but undeclared must not retry."""

        request, call, client_config = self._signed_commit_agent_step()
        undeclared = "/mindclade.internal.agent.v1.AgentService/CommitAgentStepV2"
        self.assertNotIn(undeclared, IDEMPOTENT_MUTATION_METHODS)
        self.assertFalse(retry_permitted(undeclared, request, call, client_config))


class AsyncRetryLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_retry_matches_the_synchronous_schedule(self) -> None:
        observed: list[dict[str, str]] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout
            observed.append({key: str(value) for key, value in metadata})
            if len(observed) < 3:
                raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)
            return succeeded()

        transport = FakeAsyncTransport()
        transport.unary_handlers[GET_OPERATION] = handler
        client = AsyncClient(config(), transport=transport)
        try:
            operation = await client.operations.get(
                OPERATION_NAME, options=CallOptions(timeout=2.0)
            )
        finally:
            await client.close()
        self.assertTrue(operation.done)
        self.assertEqual([entry["x-mindclade-retry-count"] for entry in observed], ["0", "1", "2"])
        budgets = [int(entry["x-mindclade-timeout-ms"]) for entry in observed]
        self.assertEqual(budgets, sorted(budgets, reverse=True))

    async def test_async_should_retry_trailer_forbids_a_retry(self) -> None:
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(
                grpc.StatusCode.UNAVAILABLE,
                (("x-mindclade-should-retry", "false"),),
            )

        transport = FakeAsyncTransport()
        transport.unary_handlers[GET_OPERATION] = handler
        client = AsyncClient(config(), transport=transport)
        try:
            with self.assertRaises(UnavailableError):
                await client.operations.get(OPERATION_NAME)
        finally:
            await client.close()
        self.assertEqual(attempts, 1)

    async def test_async_per_request_max_attempts_and_retry_trace(self) -> None:
        attempts = 0

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del request, timeout, metadata
            nonlocal attempts
            attempts += 1
            raise FakeRpcError(grpc.StatusCode.UNAVAILABLE)

        transport = FakeAsyncTransport()
        transport.unary_handlers[GET_OPERATION] = handler
        client = AsyncClient(config(), transport=transport)
        try:
            with self.assertRaises(UnavailableError) as raised:
                await client.operations.get(OPERATION_NAME, options=CallOptions(max_attempts=2))
        finally:
            await client.close()
        self.assertEqual(attempts, 2)
        trace = raised.exception.retry_trace
        assert trace is not None
        self.assertEqual(trace.attempts, 2)
        self.assertEqual(trace.cause, "UNAVAILABLE")

    async def test_async_timeout_budget_covers_credential_acquisition(self) -> None:
        credentials = AsyncCredentials(delay=0.2)
        transport = FakeAsyncTransport()
        client = AsyncClient(config(token_provider=credentials), transport=transport)
        try:
            with self.assertRaises(DeadlineExceededError):
                await client.operations.get(OPERATION_NAME, options=CallOptions(timeout=0.05))
        finally:
            await client.close()
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
