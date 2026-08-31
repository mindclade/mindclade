from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from common.v1.error_detail_pb2 import (
    ERROR_CODE_ABORTED,
    ERROR_CODE_ALREADY_EXISTS,
    ERROR_CODE_CANCELLED,
    ERROR_CODE_CONFLICT,
    ERROR_CODE_DATA_LOSS,
    ERROR_CODE_DEADLINE_EXCEEDED,
    ERROR_CODE_FAILED_PRECONDITION,
    ERROR_CODE_INTERNAL,
    ERROR_CODE_INVALID_ARGUMENT,
    ERROR_CODE_NOT_FOUND,
    ERROR_CODE_PERMISSION_DENIED,
    ERROR_CODE_POLICY_DENIED,
    ERROR_CODE_RESOURCE_EXHAUSTED,
    ERROR_CODE_UNAUTHENTICATED,
    ERROR_CODE_UNAVAILABLE,
    ERROR_CODE_UNSUPPORTED,
    RETRY_CLASS_NEVER,
    RETRY_CLASS_SAFE,
)
from common.v1.error_detail_pb2 import (
    ErrorDetail as ErrorDetail,
)
from common.v1.resource_reference_pb2 import ResourceRef


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


_PROTO_ERROR_CODES = {
    ErrorCode.INVALID_ARGUMENT: ERROR_CODE_INVALID_ARGUMENT,
    ErrorCode.FAILED_PRECONDITION: ERROR_CODE_FAILED_PRECONDITION,
    ErrorCode.NOT_FOUND: ERROR_CODE_NOT_FOUND,
    ErrorCode.ALREADY_EXISTS: ERROR_CODE_ALREADY_EXISTS,
    ErrorCode.PERMISSION_DENIED: ERROR_CODE_PERMISSION_DENIED,
    ErrorCode.UNAUTHENTICATED: ERROR_CODE_UNAUTHENTICATED,
    ErrorCode.RESOURCE_EXHAUSTED: ERROR_CODE_RESOURCE_EXHAUSTED,
    ErrorCode.ABORTED: ERROR_CODE_ABORTED,
    ErrorCode.CONFLICT: ERROR_CODE_CONFLICT,
    ErrorCode.UNAVAILABLE: ERROR_CODE_UNAVAILABLE,
    ErrorCode.DEADLINE_EXCEEDED: ERROR_CODE_DEADLINE_EXCEEDED,
    ErrorCode.CANCELLED: ERROR_CODE_CANCELLED,
    ErrorCode.INTERNAL: ERROR_CODE_INTERNAL,
    ErrorCode.DATA_LOSS: ERROR_CODE_DATA_LOSS,
    ErrorCode.UNSUPPORTED: ERROR_CODE_UNSUPPORTED,
    ErrorCode.POLICY_DENIED: ERROR_CODE_POLICY_DENIED,
}
_ERROR_CODES_BY_PROTO = {value: key for key, value in _PROTO_ERROR_CODES.items()}


def to_error_detail(error: ContractError, *, subject: ResourceRef | None = None) -> ErrorDetail:
    """Project an in-process exception into the authoritative generated wire type."""
    detail = ErrorDetail(
        code=_PROTO_ERROR_CODES[error.code],
        message=error.message,
        retry_class=RETRY_CLASS_SAFE if error.retryable else RETRY_CLASS_NEVER,
    )
    if subject is not None:
        detail.subject.CopyFrom(subject)
    return detail


def from_error_detail(detail: ErrorDetail) -> ContractError:
    """Validate and map a generated wire error into the in-process exception type."""
    try:
        code = _ERROR_CODES_BY_PROTO[detail.code]
    except KeyError as error:
        raise ValueError("unknown error code") from error
    return ContractError(
        code=code,
        message=detail.message,
        retryable=detail.retry_class == RETRY_CLASS_SAFE,
    )
