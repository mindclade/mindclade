from __future__ import annotations

from dataclasses import dataclass

from common.v1.error_detail_pb2 import (
    ERROR_CODE_UNSPECIFIED,
    RETRY_CLASS_NEVER,
    RETRY_CLASS_SAFE,
)
from common.v1.error_detail_pb2 import (
    ErrorCode as ErrorCode,
)
from common.v1.error_detail_pb2 import (
    ErrorDetail as ErrorDetail,
)
from common.v1.resource_reference_pb2 import ResourceRef


@dataclass(frozen=True)
class ContractError(Exception):
    code: ErrorCode
    message: str
    retryable: bool = False


def map_exception(error: Exception) -> ContractError:
    return (
        error
        if isinstance(error, ContractError)
        else ContractError(ErrorCode.ERROR_CODE_INTERNAL, "internal error")
    )


def to_error_detail(error: ContractError, *, subject: ResourceRef | None = None) -> ErrorDetail:
    """Project an in-process exception into the authoritative generated wire type."""
    if error.code == ERROR_CODE_UNSPECIFIED or error.code not in ErrorCode.values():
        raise ValueError("unknown error code")
    detail = ErrorDetail(
        code=error.code,
        message=error.message,
        retry_class=RETRY_CLASS_SAFE if error.retryable else RETRY_CLASS_NEVER,
    )
    if subject is not None:
        detail.subject.CopyFrom(subject)
    return detail


def from_error_detail(detail: ErrorDetail) -> ContractError:
    """Validate and map a generated wire error into the in-process exception type."""
    if detail.code == ERROR_CODE_UNSPECIFIED or detail.code not in ErrorCode.values():
        raise ValueError("unknown error code")
    return ContractError(
        code=detail.code,
        message=detail.message,
        retryable=detail.retry_class == RETRY_CLASS_SAFE,
    )
