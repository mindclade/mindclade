from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "invalid_argument"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


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
