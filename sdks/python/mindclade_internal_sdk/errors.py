"""Stable, payload-safe error normalization for internal RPCs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import grpc
from mindclade.operation.v1 import operation_pb2
from mindclade.workflow.v1 import workflow_run_pb2

RETRYABLE_CODES = frozenset(
    {
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.UNAVAILABLE,
    }
)


class MindcladeError(Exception):
    """Base SDK error containing only bounded transport metadata."""

    def __init__(
        self,
        message: str,
        *,
        status: grpc.StatusCode | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id
        self.retryable = retryable
        self.retry_after = retry_after


class AuthenticationError(MindcladeError):
    pass


class AuthorizationError(MindcladeError):
    pass


class InvalidRequestError(MindcladeError):
    pass


class NotFoundError(MindcladeError):
    pass


class ConflictError(MindcladeError):
    pass


class RateLimitError(MindcladeError):
    pass


class DeadlineExceededError(MindcladeError):
    pass


class CancelledError(MindcladeError):
    pass


class UnavailableError(MindcladeError):
    pass


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
        super().__init__(
            "Mindclade operation reached a failed terminal state",
            status=(
                grpc.StatusCode.CANCELLED
                if operation.state == operation_pb2.OPERATION_STATE_CANCELLED
                else grpc.StatusCode.FAILED_PRECONDITION
            ),
            retryable=False,
        )


class WorkflowRunFailedError(MindcladeError):
    """A failed/cancelled/expired workflow with generated state attached."""

    def __init__(self, run: workflow_run_pb2.WorkflowRun) -> None:
        self.run = workflow_run_pb2.WorkflowRun()
        self.run.CopyFrom(run)
        super().__init__(
            "Mindclade workflow run reached a failed terminal state",
            status=(
                grpc.StatusCode.CANCELLED
                if run.state == workflow_run_pb2.WORKFLOW_RUN_STATE_CANCELLED
                else grpc.StatusCode.FAILED_PRECONDITION
            ),
            retryable=False,
        )


class ProtocolError(MindcladeError):
    """The remote endpoint violated a generated response invariant."""


class TransportError(MindcladeError):
    pass


def _metadata_request_id(metadata: Iterable[tuple[str, str | bytes]] | None) -> str | None:
    if metadata is None:
        return None
    for key, value in metadata:
        if key.lower() in {"x-request-id", "x-mindclade-request-id"}:
            decoded = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else value
            if decoded and len(decoded) <= 256 and "\n" not in decoded and "\r" not in decoded:
                return decoded
    return None


def _rpc_request_id(error: grpc.RpcError, fallback: str | None) -> str | None:
    for accessor_name in ("trailing_metadata", "initial_metadata"):
        accessor: Any = getattr(error, accessor_name, None)
        if not callable(accessor):
            continue
        try:
            raw_metadata = accessor()
            metadata = cast(Iterable[tuple[str, str | bytes]] | None, raw_metadata)
            request_id = _metadata_request_id(metadata)
        except Exception:  # pragma: no cover - defensive provider boundary
            continue
        if request_id:
            return request_id
    return fallback


def _metadata_retry_after(metadata: Iterable[tuple[str, str | bytes]] | None) -> float | None:
    if metadata is None:
        return None
    for key, value in metadata:
        if key.lower() != "retry-after-ms":
            continue
        decoded = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else value
        if not decoded.isascii() or not decoded.isdecimal():
            return None
        milliseconds = int(decoded)
        if milliseconds > 30_000:
            milliseconds = 30_000
        return milliseconds / 1_000
    return None


def _rpc_retry_after(error: grpc.RpcError) -> float | None:
    for accessor_name in ("trailing_metadata", "initial_metadata"):
        accessor: Any = getattr(error, accessor_name, None)
        if not callable(accessor):
            continue
        try:
            raw_metadata = accessor()
            metadata = cast(Iterable[tuple[str, str | bytes]] | None, raw_metadata)
            retry_after = _metadata_retry_after(metadata)
        except Exception:  # pragma: no cover - defensive provider boundary
            continue
        if retry_after is not None:
            return retry_after
    return None


def normalize_rpc_error(error: grpc.RpcError, *, fallback_request_id: str) -> MindcladeError:
    """Map gRPC status without copying provider detail strings or payloads."""

    status_accessor: Any = getattr(error, "code", None)
    status = status_accessor() if callable(status_accessor) else None
    if not isinstance(status, grpc.StatusCode):
        status = None
    request_id = _rpc_request_id(error, fallback_request_id)
    retryable = status in RETRYABLE_CODES
    error_type: type[MindcladeError]
    if status is grpc.StatusCode.UNAUTHENTICATED:
        error_type = AuthenticationError
    elif status is grpc.StatusCode.PERMISSION_DENIED:
        error_type = AuthorizationError
    elif status is grpc.StatusCode.INVALID_ARGUMENT:
        error_type = InvalidRequestError
    elif status is grpc.StatusCode.NOT_FOUND:
        error_type = NotFoundError
    elif status in {
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.ALREADY_EXISTS,
        grpc.StatusCode.FAILED_PRECONDITION,
    }:
        error_type = ConflictError
    elif status is grpc.StatusCode.RESOURCE_EXHAUSTED:
        error_type = RateLimitError
    elif status is grpc.StatusCode.DEADLINE_EXCEEDED:
        error_type = DeadlineExceededError
    elif status is grpc.StatusCode.CANCELLED:
        error_type = CancelledError
    elif status is grpc.StatusCode.UNAVAILABLE:
        error_type = UnavailableError
    else:
        error_type = TransportError
    status_name = status.name.lower() if status is not None else "unknown"
    return error_type(
        f"Mindclade RPC failed with status {status_name}",
        status=status,
        request_id=request_id,
        retryable=retryable,
        retry_after=_rpc_retry_after(error),
    )
