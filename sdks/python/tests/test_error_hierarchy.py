from __future__ import annotations

import unittest
from typing import cast

import grpc
from mindclade.common.v1 import error_detail_pb2
from mindclade.operation.v1 import operation_pb2
from mindclade.workflow.v1 import workflow_run_pb2
from mindclade_internal_sdk import (
    AuthenticationError,
    AuthorizationError,
    CancelledError,
    ConflictError,
    DeadlineExceededError,
    FenceState,
    FieldViolation,
    InvalidRequestError,
    MindcladeError,
    NotFoundError,
    OperationFailedError,
    PreconditionViolation,
    QuotaError,
    QuotaState,
    RateLimitError,
    RetryableServiceError,
    TransportError,
    UnavailableError,
    ValidationError,
    WorkflowRunFailedError,
    error_from_detail,
)
from mindclade_internal_sdk import errors as errors_module
from mindclade_internal_sdk.errors import (
    FENCE_PRECONDITION_TYPE,
    QUOTA_PRECONDITION_TYPE,
    RETRYABLE_CODES,
    RETRYABLE_STATUS_CODES,
    REVISION_PRECONDITION_TYPE,
    error_detail_fields,
    normalize_rpc_error,
    retryable_status,
)
from mindclade_internal_sdk.testing import FakeRpcError

_EXPECTED_TYPES: dict[grpc.StatusCode, type[MindcladeError]] = {
    grpc.StatusCode.OK: TransportError,
    grpc.StatusCode.CANCELLED: CancelledError,
    grpc.StatusCode.UNKNOWN: TransportError,
    grpc.StatusCode.INVALID_ARGUMENT: ValidationError,
    grpc.StatusCode.DEADLINE_EXCEEDED: DeadlineExceededError,
    grpc.StatusCode.NOT_FOUND: NotFoundError,
    grpc.StatusCode.ALREADY_EXISTS: ConflictError,
    grpc.StatusCode.PERMISSION_DENIED: AuthorizationError,
    grpc.StatusCode.RESOURCE_EXHAUSTED: RateLimitError,
    grpc.StatusCode.FAILED_PRECONDITION: ConflictError,
    grpc.StatusCode.ABORTED: ConflictError,
    grpc.StatusCode.OUT_OF_RANGE: TransportError,
    grpc.StatusCode.UNIMPLEMENTED: TransportError,
    grpc.StatusCode.INTERNAL: TransportError,
    grpc.StatusCode.UNAVAILABLE: RetryableServiceError,
    grpc.StatusCode.DATA_LOSS: TransportError,
    grpc.StatusCode.UNAUTHENTICATED: AuthenticationError,
}


def detail(
    *,
    code: error_detail_pb2.ErrorCode = error_detail_pb2.ERROR_CODE_RESOURCE_EXHAUSTED,
    retry_class: error_detail_pb2.RetryClass = error_detail_pb2.RETRY_CLASS_NEVER,
) -> error_detail_pb2.ErrorDetail:
    value = error_detail_pb2.ErrorDetail(
        code=code,
        message="bounded server message",
        retry_class=retry_class,
        error_id="diagnostics/error-1",
    )
    value.subject.resource_type = "training_run"
    value.subject.resource_id = "run-1"
    value.subject.etag = "etag-77"
    value.subject.resource_version = 77
    value.field_violations.add(field="spec.epochs", description="must be positive")
    value.precondition_violations.add(
        type=QUOTA_PRECONDITION_TYPE,
        subject="projects/project-1/gpuHours",
        description="project GPU-hour allowance is exhausted",
    )
    value.precondition_violations.add(
        type=FENCE_PRECONDITION_TYPE,
        subject="attempts/attempt-1",
        description="lease epoch is stale",
    )
    value.precondition_violations.add(
        type=REVISION_PRECONDITION_TYPE,
        subject="trainingRuns/run-1",
        description="resource version is stale",
    )
    value.retry_after.seconds = 2
    value.retry_after.nanos = 500_000_000
    return value


class StatusMappingTest(unittest.TestCase):
    def test_every_status_maps_to_its_contract_type(self) -> None:
        self.assertEqual(len(_EXPECTED_TYPES), len(list(grpc.StatusCode)))
        for status, expected in _EXPECTED_TYPES.items():
            error = normalize_rpc_error(
                FakeRpcError(status), fallback_request_id="client-request-1"
            )
            self.assertIsInstance(error, expected)
            self.assertEqual(error.status, status)
            self.assertEqual(error.code, status.name.lower())
            self.assertEqual(error.retryable, status in RETRYABLE_STATUS_CODES)

    def test_the_single_retryable_predicate_is_shared(self) -> None:
        self.assertIs(RETRYABLE_CODES, RETRYABLE_STATUS_CODES)
        self.assertEqual(
            RETRYABLE_STATUS_CODES,
            {
                grpc.StatusCode.ABORTED,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                grpc.StatusCode.UNAVAILABLE,
            },
        )
        for status in grpc.StatusCode:
            self.assertEqual(retryable_status(status), status in RETRYABLE_STATUS_CODES)
        self.assertFalse(retryable_status(None))

    def test_contract_names_remain_catchable_as_the_existing_names(self) -> None:
        with self.assertRaises(InvalidRequestError):
            raise normalize_rpc_error(
                FakeRpcError(grpc.StatusCode.INVALID_ARGUMENT), fallback_request_id="r"
            )
        with self.assertRaises(UnavailableError):
            raise normalize_rpc_error(
                FakeRpcError(grpc.StatusCode.UNAVAILABLE), fallback_request_id="r"
            )
        with self.assertRaises(RateLimitError):
            raise error_from_detail(
                error_detail_pb2.ErrorDetail(code=error_detail_pb2.ERROR_CODE_RESOURCE_EXHAUSTED)
            )
        # Every contract-named class exists and descends from the one base error.
        contract_names = (
            "AuthenticationError",
            "AuthorizationError",
            "ValidationError",
            "ConflictError",
            "NotFoundError",
            "RateLimitError",
            "QuotaError",
            "RetryableServiceError",
            "OperationFailedError",
            "CancelledError",
            "TransportError",
        )
        for name in contract_names:
            error_type = getattr(errors_module, name)
            self.assertTrue(issubclass(error_type, MindcladeError), name)


class TrailerReadingTest(unittest.TestCase):
    def test_request_id_alias_is_retired(self) -> None:
        error = normalize_rpc_error(
            FakeRpcError(
                grpc.StatusCode.UNAVAILABLE,
                (("x-mindclade-request-id", "legacy-alias-id"),),
            ),
            fallback_request_id="client-request-1",
        )
        self.assertEqual(error.request_id, "client-request-1")

    def test_canonical_request_id_is_read(self) -> None:
        error = normalize_rpc_error(
            FakeRpcError(grpc.StatusCode.UNAVAILABLE, (("x-request-id", "server-request-1"),)),
            fallback_request_id="client-request-1",
        )
        self.assertEqual(error.request_id, "server-request-1")

    def test_trace_id_is_read_from_the_trailer(self) -> None:
        error = normalize_rpc_error(
            FakeRpcError(grpc.StatusCode.ABORTED, (("x-trace-id", "trace-abc"),)),
            fallback_request_id="client-request-1",
        )
        self.assertEqual(error.trace_id, "trace-abc")
        self.assertIsNone(
            normalize_rpc_error(
                FakeRpcError(grpc.StatusCode.ABORTED), fallback_request_id="r"
            ).trace_id
        )

    def test_oversized_or_injected_trailer_values_are_rejected(self) -> None:
        error = normalize_rpc_error(
            FakeRpcError(
                grpc.StatusCode.UNAVAILABLE,
                (
                    ("x-request-id", "a" * 300),
                    ("x-trace-id", "trace\r\ninjected: yes"),
                ),
            ),
            fallback_request_id="client-request-1",
        )
        self.assertEqual(error.request_id, "client-request-1")
        self.assertIsNone(error.trace_id)

    def test_retry_after_trailer_is_parsed_and_capped(self) -> None:
        error = normalize_rpc_error(
            FakeRpcError(grpc.StatusCode.UNAVAILABLE, (("retry-after-ms", "1"),)),
            fallback_request_id="r",
        )
        self.assertEqual(error.retry_after, 0.001)
        capped = normalize_rpc_error(
            FakeRpcError(grpc.StatusCode.UNAVAILABLE, (("retry-after-ms", "600000"),)),
            fallback_request_id="r",
        )
        self.assertEqual(capped.retry_after, 30.0)

    def test_server_should_retry_override_is_recorded_in_both_directions(self) -> None:
        forbidden = normalize_rpc_error(
            FakeRpcError(grpc.StatusCode.UNAVAILABLE, (("x-mindclade-should-retry", "false"),)),
            fallback_request_id="r",
        )
        self.assertIs(forbidden.server_should_retry, False)
        self.assertFalse(forbidden.retryable)
        permitted = normalize_rpc_error(
            FakeRpcError(grpc.StatusCode.INTERNAL, (("x-mindclade-should-retry", "TRUE"),)),
            fallback_request_id="r",
        )
        self.assertIs(permitted.server_should_retry, True)
        self.assertTrue(permitted.retryable)


class ErrorDetailProjectionTest(unittest.TestCase):
    def test_error_detail_populates_typed_fields_only(self) -> None:
        error = error_from_detail(
            detail(retry_class=error_detail_pb2.RETRY_CLASS_AFTER_RECONCILIATION),
            request_id="request-1",
            trace_id="trace-1",
            operation_id="operations/op-1",
        )
        self.assertIsInstance(error, QuotaError)
        self.assertIsInstance(error, RateLimitError)
        self.assertEqual(error.code, "resource_exhausted")
        self.assertEqual(error.status, grpc.StatusCode.RESOURCE_EXHAUSTED)
        self.assertEqual(error.request_id, "request-1")
        self.assertEqual(error.trace_id, "trace-1")
        self.assertEqual(error.operation_id, "operations/op-1")
        self.assertTrue(error.retryable)
        self.assertAlmostEqual(error.retry_after or 0.0, 2.5)
        self.assertEqual(
            error.field_violations,
            (FieldViolation(field="spec.epochs", description="must be positive"),),
        )
        self.assertEqual(len(error.precondition_violations), 3)
        self.assertIn(
            PreconditionViolation(
                type=FENCE_PRECONDITION_TYPE,
                subject="attempts/attempt-1",
                description="lease epoch is stale",
            ),
            error.precondition_violations,
        )
        self.assertEqual(
            error.quota,
            QuotaState(
                subject="projects/project-1/gpuHours",
                description="project GPU-hour allowance is exhausted",
            ),
        )
        self.assertEqual(
            error.fence,
            FenceState(subject="attempts/attempt-1", description="lease epoch is stale"),
        )
        self.assertEqual(error.conflict_revision, "etag-77")
        self.assertEqual(error.diagnostic_reference, "diagnostics/error-1")
        # The detail's own message never becomes the exception message.
        self.assertEqual(str(error), "Mindclade request failed with code resource_exhausted")
        self.assertNotIn("bounded server message", str(error))

    def test_rate_limit_without_quota_state_is_not_a_quota_error(self) -> None:
        plain = error_detail_pb2.ErrorDetail(
            code=error_detail_pb2.ERROR_CODE_RESOURCE_EXHAUSTED,
            message="slow down",
        )
        error = error_from_detail(plain)
        self.assertIsInstance(error, RateLimitError)
        self.assertNotIsInstance(error, QuotaError)
        self.assertIsNone(error.quota)

    def test_unrecognized_error_code_never_authorizes_retry(self) -> None:
        unknown = error_detail_pb2.ErrorDetail()
        unknown.code = cast(error_detail_pb2.ErrorCode, 9999)
        unknown.retry_class = cast(error_detail_pb2.RetryClass, 4242)
        fields = error_detail_fields(unknown)
        self.assertEqual(fields["code"], "unknown")
        self.assertIs(fields["retryable"], False)
        error = error_from_detail(unknown)
        self.assertIsInstance(error, TransportError)
        self.assertEqual(error.code, "unknown")
        self.assertFalse(error.retryable)
        self.assertIsNone(error.status)

    def test_unspecified_error_code_is_reported_as_unknown(self) -> None:
        fields = error_detail_fields(error_detail_pb2.ErrorDetail())
        self.assertEqual(fields["code"], "unknown")
        self.assertIs(fields["retryable"], False)

    def test_unrecognized_precondition_type_is_carried_but_projects_nothing(self) -> None:
        value = error_detail_pb2.ErrorDetail(code=error_detail_pb2.ERROR_CODE_FAILED_PRECONDITION)
        value.precondition_violations.add(
            type="CONFIGURATION", subject="jobs/job-1", description="fixture precondition"
        )
        error = error_from_detail(value)
        self.assertIsInstance(error, ConflictError)
        self.assertEqual(len(error.precondition_violations), 1)
        self.assertIsNone(error.quota)
        self.assertIsNone(error.fence)
        self.assertIsNone(error.conflict_revision)

    def test_detail_text_is_bounded_and_stripped_of_control_characters(self) -> None:
        value = error_detail_pb2.ErrorDetail(code=error_detail_pb2.ERROR_CODE_INVALID_ARGUMENT)
        value.field_violations.add(field="spec\r\nname", description="x" * 5000)
        error = error_from_detail(value)
        violation = error.field_violations[0]
        self.assertEqual(violation.field, "specname")
        self.assertEqual(len(violation.description), 1024)


class DurableFailureTest(unittest.TestCase):
    def test_operation_failure_populates_typed_fields_from_its_detail(self) -> None:
        operation = operation_pb2.Operation(
            operation_id="operations/op-1",
            state=operation_pb2.OPERATION_STATE_FAILED,
        )
        operation.error.CopyFrom(
            detail(
                code=error_detail_pb2.ERROR_CODE_FAILED_PRECONDITION,
                retry_class=error_detail_pb2.RETRY_CLASS_SAFE,
            )
        )
        error = OperationFailedError(operation)
        self.assertEqual(str(error), "Mindclade operation reached a failed terminal state")
        self.assertEqual(error.operation_id, "operations/op-1")
        self.assertEqual(error.code, "failed_precondition")
        self.assertEqual(error.diagnostic_reference, "diagnostics/error-1")
        self.assertIsNotNone(error.quota)
        self.assertIsNotNone(error.fence)
        self.assertEqual(error.conflict_revision, "etag-77")
        # A durable terminal failure is never retryable regardless of the hint.
        self.assertFalse(error.retryable)
        self.assertEqual(error.operation.operation_id, "operations/op-1")

    def test_operation_failure_without_detail_keeps_its_status_derived_code(self) -> None:
        error = OperationFailedError(
            operation_pb2.Operation(
                operation_id="operations/op-2",
                state=operation_pb2.OPERATION_STATE_CANCELLED,
            )
        )
        self.assertEqual(error.status, grpc.StatusCode.CANCELLED)
        self.assertEqual(error.code, "cancelled")
        self.assertEqual(error.field_violations, ())

    def test_workflow_failure_populates_typed_fields_from_its_detail(self) -> None:
        run = workflow_run_pb2.WorkflowRun(state=workflow_run_pb2.WORKFLOW_RUN_STATE_FAILED)
        run.failure.CopyFrom(detail(code=error_detail_pb2.ERROR_CODE_CONFLICT))
        error = WorkflowRunFailedError(run)
        self.assertEqual(str(error), "Mindclade workflow run reached a failed terminal state")
        self.assertEqual(error.code, "conflict")
        self.assertFalse(error.retryable)
        self.assertEqual(error.conflict_revision, "etag-77")


class SanitizationTest(unittest.TestCase):
    def test_errors_never_carry_provider_detail_or_payload(self) -> None:
        leak = (
            'pq: duplicate key value violates unique constraint "jobs_pkey" (SQLSTATE 23505)\n'
            "  at libs/go/persistence/transactions.go:211"
        )
        error = normalize_rpc_error(
            FakeRpcError(grpc.StatusCode.ABORTED, details=leak),
            fallback_request_id="client-request-1",
        )
        for rendered in (str(error), repr(error)):
            self.assertNotIn("SQLSTATE", rendered)
            self.assertNotIn("jobs_pkey", rendered)
            self.assertNotIn("transactions.go", rendered)
        self.assertEqual(str(error), "Mindclade RPC failed with status aborted")

    def test_every_contract_field_is_present_on_the_base_error(self) -> None:
        error = MindcladeError("bounded")
        for attribute in (
            "code",
            "status",
            "request_id",
            "trace_id",
            "operation_id",
            "retryable",
            "retry_after",
            "field_violations",
            "precondition_violations",
            "quota",
            "fence",
            "conflict_revision",
            "diagnostic_reference",
            "server_should_retry",
            "retry_trace",
        ):
            self.assertTrue(hasattr(error, attribute), attribute)
        self.assertEqual(error.code, "unknown")


if __name__ == "__main__":
    unittest.main()
