"""Stable, payload-safe error normalization for internal RPCs.

Every error leaving this SDK is sanitized: provider strings, SQL, SQLSTATE,
Pub/Sub internals, and stack traces never reach the caller. Structured server
detail arrives only through the generated ``mindclade.common.v1.ErrorDetail``
message and is exposed as typed fields.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, cast

import grpc
from mindclade.common.v1 import error_detail_pb2
from mindclade.operation.v1 import operation_pb2
from mindclade.workflow.v1 import workflow_run_pb2

REQUEST_ID_METADATA = "x-request-id"
TRACE_ID_METADATA = "x-trace-id"
RETRY_AFTER_METADATA = "retry-after-ms"
SHOULD_RETRY_METADATA = "x-mindclade-should-retry"

# The one retryable-status predicate for the whole SDK. Nothing else in this
# package may define a second set of retryable gRPC statuses.
RETRYABLE_STATUS_CODES = frozenset(
    {
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.UNAVAILABLE,
    }
)

# Retained name for existing importers; the authoritative name is above.
RETRYABLE_CODES = RETRYABLE_STATUS_CODES

# Precondition-violation ``type`` values this SDK recognises and projects onto
# typed fields. Anything else is carried verbatim as a precondition violation
# and never widens retryability or authorizes an action.
QUOTA_PRECONDITION_TYPE = "QUOTA_EXHAUSTED"
FENCE_PRECONDITION_TYPE = "LEASE_FENCE"
REVISION_PRECONDITION_TYPE = "RESOURCE_VERSION"

_MAX_RETRY_AFTER_MILLISECONDS = 30_000
_MAX_DETAIL_TEXT = 1024
_MAX_DETAIL_ITEMS = 128


def retryable_status(status: grpc.StatusCode | None) -> bool:
    """Return whether a gRPC status is implicitly retryable for a safe call."""

    return status in RETRYABLE_STATUS_CODES


def _safe_text(value: object, *, limit: int = _MAX_DETAIL_TEXT) -> str:
    """Bound a server-supplied string and strip anything that could forge a log line."""

    if not isinstance(value, str):
        return ""
    trimmed = value[:limit]
    return "".join(character for character in trimmed if character.isprintable())


# Protobuf owns these wire models. The facade sanitizes the values it copies out
# of a server ``ErrorDetail`` but re-uses the generated messages rather than
# declaring a parallel pair, which the boundary law forbids and which would give
# callers two incompatible shapes for the same contract type.
FieldViolation = error_detail_pb2.FieldViolation
PreconditionViolation = error_detail_pb2.PreconditionViolation


@dataclass(frozen=True, slots=True)
class QuotaState:
    """Durable quota facts attached to an exhausted-resource failure."""

    subject: str
    description: str


@dataclass(frozen=True, slots=True)
class FenceState:
    """Lease-fencing facts attached to a rejected fenced mutation."""

    subject: str
    description: str


@dataclass(frozen=True, slots=True)
class RetryTrace:
    """Observable retry accounting for the error that finally left the SDK."""

    attempts: int
    cumulative_delay_seconds: float
    cause: str


class MindcladeError(Exception):
    """Base SDK error containing only bounded, sanitized transport detail."""

    def __init__(
        self,
        message: str,
        *,
        status: grpc.StatusCode | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
        code: str | None = None,
        trace_id: str | None = None,
        operation_id: str | None = None,
        field_violations: tuple[FieldViolation, ...] = (),
        precondition_violations: tuple[PreconditionViolation, ...] = (),
        quota: QuotaState | None = None,
        fence: FenceState | None = None,
        conflict_revision: str | None = None,
        diagnostic_reference: str | None = None,
        server_should_retry: bool | None = None,
        retry_trace: RetryTrace | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id
        self.retryable = retryable
        self.retry_after = retry_after
        self.code = code or (status.name.lower() if status is not None else "unknown")
        self.trace_id = trace_id
        self.operation_id = operation_id
        self.field_violations = field_violations
        self.precondition_violations = precondition_violations
        self.quota = quota
        self.fence = fence
        self.conflict_revision = conflict_revision
        self.diagnostic_reference = diagnostic_reference
        self.server_should_retry = server_should_retry
        self.retry_trace = retry_trace


class AuthenticationError(MindcladeError):
    pass


class AuthorizationError(MindcladeError):
    pass


class InvalidRequestError(MindcladeError):
    pass


class ValidationError(InvalidRequestError):
    """Contract name for INVALID_ARGUMENT; catchable as ``InvalidRequestError``."""


class NotFoundError(MindcladeError):
    pass


class ConflictError(MindcladeError):
    pass


class RateLimitError(MindcladeError):
    pass


class QuotaError(RateLimitError):
    """RESOURCE_EXHAUSTED carrying durable quota state rather than a rate limit."""


class DeadlineExceededError(MindcladeError):
    pass


class CancelledError(MindcladeError):
    pass


class UnavailableError(MindcladeError):
    pass


class RetryableServiceError(UnavailableError):
    """Contract name for UNAVAILABLE; catchable as ``UnavailableError``."""


class OperationTimeoutError(MindcladeError):
    pass


class PaginationLimitError(MindcladeError):
    """Automatic pagination stopped before implying a complete result."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status=grpc.StatusCode.RESOURCE_EXHAUSTED, retryable=False)


class OperationFailedError(MindcladeError):
    """A durable failed/cancelled operation with its generated state attached."""

    def __init__(self, operation: operation_pb2.Operation) -> None:
        self.operation = operation_pb2.Operation()
        self.operation.CopyFrom(operation)
        detail = error_detail_fields(operation.error) if operation.HasField("error") else {}
        detail.pop("retryable", None)
        super().__init__(
            "Mindclade operation reached a failed terminal state",
            status=(
                grpc.StatusCode.CANCELLED
                if operation.state == operation_pb2.OPERATION_STATE_CANCELLED
                else grpc.StatusCode.FAILED_PRECONDITION
            ),
            retryable=False,
            operation_id=operation.operation_id or None,
            **detail,
        )


class WorkflowRunFailedError(MindcladeError):
    """A failed/cancelled/expired workflow with generated state attached."""

    def __init__(self, run: workflow_run_pb2.WorkflowRun) -> None:
        self.run = workflow_run_pb2.WorkflowRun()
        self.run.CopyFrom(run)
        detail = error_detail_fields(run.failure) if run.HasField("failure") else {}
        detail.pop("retryable", None)
        super().__init__(
            "Mindclade workflow run reached a failed terminal state",
            status=(
                grpc.StatusCode.CANCELLED
                if run.state == workflow_run_pb2.WORKFLOW_RUN_STATE_CANCELLED
                else grpc.StatusCode.FAILED_PRECONDITION
            ),
            retryable=False,
            **detail,
        )


class ProtocolError(MindcladeError):
    """The remote endpoint violated a generated response invariant."""


class TransportError(MindcladeError):
    pass


_STATUS_ERRORS: dict[grpc.StatusCode, type[MindcladeError]] = {
    grpc.StatusCode.UNAUTHENTICATED: AuthenticationError,
    grpc.StatusCode.PERMISSION_DENIED: AuthorizationError,
    grpc.StatusCode.INVALID_ARGUMENT: ValidationError,
    grpc.StatusCode.NOT_FOUND: NotFoundError,
    grpc.StatusCode.ABORTED: ConflictError,
    grpc.StatusCode.ALREADY_EXISTS: ConflictError,
    grpc.StatusCode.FAILED_PRECONDITION: ConflictError,
    grpc.StatusCode.RESOURCE_EXHAUSTED: RateLimitError,
    grpc.StatusCode.DEADLINE_EXCEEDED: DeadlineExceededError,
    grpc.StatusCode.CANCELLED: CancelledError,
    grpc.StatusCode.UNAVAILABLE: RetryableServiceError,
}

_DETAIL_CODE_STATUS: dict[int, grpc.StatusCode] = {
    error_detail_pb2.ERROR_CODE_INVALID_ARGUMENT: grpc.StatusCode.INVALID_ARGUMENT,
    error_detail_pb2.ERROR_CODE_FAILED_PRECONDITION: grpc.StatusCode.FAILED_PRECONDITION,
    error_detail_pb2.ERROR_CODE_NOT_FOUND: grpc.StatusCode.NOT_FOUND,
    error_detail_pb2.ERROR_CODE_ALREADY_EXISTS: grpc.StatusCode.ALREADY_EXISTS,
    error_detail_pb2.ERROR_CODE_PERMISSION_DENIED: grpc.StatusCode.PERMISSION_DENIED,
    error_detail_pb2.ERROR_CODE_UNAUTHENTICATED: grpc.StatusCode.UNAUTHENTICATED,
    error_detail_pb2.ERROR_CODE_RESOURCE_EXHAUSTED: grpc.StatusCode.RESOURCE_EXHAUSTED,
    error_detail_pb2.ERROR_CODE_ABORTED: grpc.StatusCode.ABORTED,
    error_detail_pb2.ERROR_CODE_CONFLICT: grpc.StatusCode.ABORTED,
    error_detail_pb2.ERROR_CODE_UNAVAILABLE: grpc.StatusCode.UNAVAILABLE,
    error_detail_pb2.ERROR_CODE_DEADLINE_EXCEEDED: grpc.StatusCode.DEADLINE_EXCEEDED,
    error_detail_pb2.ERROR_CODE_CANCELLED: grpc.StatusCode.CANCELLED,
    error_detail_pb2.ERROR_CODE_INTERNAL: grpc.StatusCode.INTERNAL,
    error_detail_pb2.ERROR_CODE_DATA_LOSS: grpc.StatusCode.DATA_LOSS,
    error_detail_pb2.ERROR_CODE_UNSUPPORTED: grpc.StatusCode.UNIMPLEMENTED,
    error_detail_pb2.ERROR_CODE_POLICY_DENIED: grpc.StatusCode.PERMISSION_DENIED,
}

_RETRYABLE_DETAIL_CLASSES = frozenset(
    {
        error_detail_pb2.RETRY_CLASS_SAFE,
        error_detail_pb2.RETRY_CLASS_AFTER_RECONCILIATION,
    }
)


def _bounded_metadata_value(value: str | bytes) -> str | None:
    decoded = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else value
    if not decoded or len(decoded) > 256 or "\n" in decoded or "\r" in decoded:
        return None
    return decoded


def _metadata_value(
    metadata: Iterable[tuple[str, str | bytes]] | None,
    key: str,
) -> str | None:
    if metadata is None:
        return None
    for candidate, value in metadata:
        if candidate.lower() != key:
            continue
        decoded = _bounded_metadata_value(value)
        if decoded is not None:
            return decoded
    return None


def _metadata_request_id(metadata: Iterable[tuple[str, str | bytes]] | None) -> str | None:
    # The historical "x-mindclade-request-id" alias is retired; only the
    # canonical key is read so a stale server cannot shadow the real id.
    return _metadata_value(metadata, REQUEST_ID_METADATA)


def _metadata_trace_id(metadata: Iterable[tuple[str, str | bytes]] | None) -> str | None:
    return _metadata_value(metadata, TRACE_ID_METADATA)


def _metadata_should_retry(metadata: Iterable[tuple[str, str | bytes]] | None) -> bool | None:
    decoded = _metadata_value(metadata, SHOULD_RETRY_METADATA)
    if decoded is None:
        return None
    normalized = decoded.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _metadata_retry_after(metadata: Iterable[tuple[str, str | bytes]] | None) -> float | None:
    if metadata is None:
        return None
    for key, value in metadata:
        if key.lower() != RETRY_AFTER_METADATA:
            continue
        decoded = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else value
        if not decoded.isascii() or not decoded.isdecimal():
            return None
        milliseconds = int(decoded)
        if milliseconds > _MAX_RETRY_AFTER_MILLISECONDS:
            milliseconds = _MAX_RETRY_AFTER_MILLISECONDS
        return milliseconds / 1_000
    return None


def _scan_metadata(
    error: grpc.RpcError,
    read: Callable[[Iterable[tuple[str, str | bytes]] | None], object | None],
) -> object | None:
    """Read one bounded value from a gRPC error's trailers, then its headers."""

    for accessor_name in ("trailing_metadata", "initial_metadata"):
        accessor: Any = getattr(error, accessor_name, None)
        if not callable(accessor):
            continue
        try:
            raw_metadata = accessor()
            metadata = cast(Iterable[tuple[str, str | bytes]] | None, raw_metadata)
            found = read(metadata)
        except Exception:  # pragma: no cover - defensive provider boundary
            continue
        if found is not None:
            return found
    return None


def _rpc_request_id(error: grpc.RpcError, fallback: str | None) -> str | None:
    found = _scan_metadata(error, _metadata_request_id)
    return found if isinstance(found, str) else fallback


def _rpc_trace_id(error: grpc.RpcError) -> str | None:
    found = _scan_metadata(error, _metadata_trace_id)
    return found if isinstance(found, str) else None


def _rpc_should_retry(error: grpc.RpcError) -> bool | None:
    found = _scan_metadata(error, _metadata_should_retry)
    return found if isinstance(found, bool) else None


def _rpc_retry_after(error: grpc.RpcError) -> float | None:
    found = _scan_metadata(error, _metadata_retry_after)
    return found if isinstance(found, float) else None


def _detail_code(detail: error_detail_pb2.ErrorDetail) -> str:
    """Return the stable lowercase code, never trusting an unrecognized enum."""

    try:
        name = error_detail_pb2.ErrorCode.Name(detail.code)
    except ValueError:
        return "unknown"
    if name == "ERROR_CODE_UNSPECIFIED":
        return "unknown"
    return name.removeprefix("ERROR_CODE_").lower()


def error_detail_fields(detail: error_detail_pb2.ErrorDetail) -> dict[str, Any]:
    """Project a generated ``ErrorDetail`` onto sanitized typed error fields.

    The generated message stays the wire model; this only copies bounded,
    contract-declared non-secret fields out of it. An unrecognized enum value
    yields ``code="unknown"`` and never marks the failure retryable.
    """

    field_violations = tuple(
        FieldViolation(
            field=_safe_text(violation.field, limit=256),
            description=_safe_text(violation.description),
        )
        for violation in list(detail.field_violations)[:_MAX_DETAIL_ITEMS]
    )
    precondition_violations = tuple(
        PreconditionViolation(
            type=_safe_text(violation.type, limit=256),
            subject=_safe_text(violation.subject, limit=256),
            description=_safe_text(violation.description),
        )
        for violation in list(detail.precondition_violations)[:_MAX_DETAIL_ITEMS]
    )
    quota: QuotaState | None = None
    fence: FenceState | None = None
    conflict_revision: str | None = None
    for violation in precondition_violations:
        if violation.type == QUOTA_PRECONDITION_TYPE and quota is None:
            quota = QuotaState(subject=violation.subject, description=violation.description)
        elif violation.type == FENCE_PRECONDITION_TYPE and fence is None:
            fence = FenceState(subject=violation.subject, description=violation.description)
        elif violation.type == REVISION_PRECONDITION_TYPE and conflict_revision is None:
            subject = detail.subject
            conflict_revision = _safe_text(subject.etag, limit=256) or (
                str(subject.resource_version) if subject.resource_version else None
            )
    retry_after: float | None = None
    if detail.HasField("retry_after"):
        seconds = detail.retry_after.seconds + detail.retry_after.nanos / 1_000_000_000
        retry_after = max(0.0, min(seconds, _MAX_RETRY_AFTER_MILLISECONDS / 1_000))
    return {
        "code": _detail_code(detail),
        "retryable": detail.retry_class in _RETRYABLE_DETAIL_CLASSES,
        "retry_after": retry_after,
        "field_violations": field_violations,
        "precondition_violations": precondition_violations,
        "quota": quota,
        "fence": fence,
        "conflict_revision": conflict_revision,
        "diagnostic_reference": _safe_text(detail.error_id, limit=256) or None,
    }


def error_from_detail(
    detail: error_detail_pb2.ErrorDetail,
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    operation_id: str | None = None,
) -> MindcladeError:
    """Build a typed SDK error from structured, durable server failure detail.

    The detail message's own text is never used as the exception message; the
    message stays a fixed sanitized string and every server-supplied value is
    reachable only through the typed fields.
    """

    fields = error_detail_fields(detail)
    status = _DETAIL_CODE_STATUS.get(detail.code)
    error_type = TransportError if status is None else _STATUS_ERRORS.get(status, TransportError)
    if error_type is RateLimitError and fields["quota"] is not None:
        error_type = QuotaError
    code = cast(str, fields["code"])
    return error_type(
        f"Mindclade request failed with code {code}",
        status=status,
        request_id=request_id,
        trace_id=trace_id,
        operation_id=operation_id,
        **fields,
    )


def normalize_rpc_error(error: grpc.RpcError, *, fallback_request_id: str) -> MindcladeError:
    """Map gRPC status without copying provider detail strings or payloads."""

    status_accessor: Any = getattr(error, "code", None)
    status = status_accessor() if callable(status_accessor) else None
    if not isinstance(status, grpc.StatusCode):
        status = None
    request_id = _rpc_request_id(error, fallback_request_id)
    override = _rpc_should_retry(error)
    retryable = retryable_status(status) if override is None else override
    error_type = TransportError if status is None else _STATUS_ERRORS.get(status, TransportError)
    status_name = status.name.lower() if status is not None else "unknown"
    return error_type(
        f"Mindclade RPC failed with status {status_name}",
        status=status,
        request_id=request_id,
        retryable=retryable,
        retry_after=_rpc_retry_after(error),
        code=status_name,
        trace_id=_rpc_trace_id(error),
        server_should_retry=override,
    )
