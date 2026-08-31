from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from common.v1.error_detail_pb2 import ErrorDetail as ErrorDetail


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "invalid_argument"
    FAILED_PRECONDITION = "failed_precondition"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    PERMISSION_DENIED = "permission_denied"
    UNAUTHENTICATED = "unauthenticated"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    ABORTED = "aborted"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    INTERNAL = "internal"
    DATA_LOSS = "data_loss"
    UNSUPPORTED = "unsupported"
    POLICY_DENIED = "policy_denied"


@dataclass(frozen=True)
class ContractError(Exception):
    code: ErrorCode
    message: str
    retryable: bool = False


def map_exception(error: Exception) -> ContractError:
    return (
        error
        if isinstance(error, ContractError)
        else ContractError(ErrorCode.INTERNAL, "internal error")
    )


def to_error_detail(error: ContractError, *, subject_ref: str = "") -> ErrorDetail:
    """Project an in-process exception into the authoritative generated wire type."""
    return ErrorDetail(
        code=error.code.value,
        message=error.message,
        retry_class="retryable" if error.retryable else "non_retryable",
        subject_ref=subject_ref,
    )


def from_error_detail(detail: ErrorDetail) -> ContractError:
    """Validate and map a generated wire error into the in-process exception type."""
    if detail.retry_class not in {"", "retryable", "non_retryable"}:
        raise ValueError("unknown retry class")
    try:
        code = ErrorCode(detail.code)
    except ValueError as error:
        raise ValueError("unknown error code") from error
    return ContractError(
        code=code,
        message=detail.message,
        retryable=detail.retry_class == "retryable",
    )
