"""Act on failures through the SDK error hierarchy, never on raw status codes."""

from __future__ import annotations

from dataclasses import dataclass

from mindclade_internal_sdk import CallOptions, Client, MindcladeError, NotFoundError
from mindclade_internal_sdk.resources import Operation


@dataclass(frozen=True, slots=True)
class FailureReport:
    """Operator-facing projection of one SDK error.

    This is a presentation view built from the error the SDK raised, not a
    second error taxonomy: every field below is copied from that error, and a
    caller that needs the full detail keeps the error itself.
    """

    code: str
    retryable: bool
    retry_after_seconds: float | None
    request_id: str | None
    trace_id: str | None
    invalid_fields: tuple[str, ...]


def operation_if_present(
    client: Client,
    operation_name: str,
    *,
    options: CallOptions | None = None,
) -> Operation | None:
    """Return the operation, or ``None`` when the control plane has no such name.

    Exactly one typed class is caught, because absence is the only failure this
    caller can turn into a value. Authentication, authorization, conflict, quota
    and service failures keep the class the SDK gave them and reach the caller
    unchanged. Nothing here inspects a gRPC status, and nothing retries: the SDK
    already retried whatever was safe to retry before raising.
    """

    try:
        return client.operations.get(operation_name, options=options)
    except NotFoundError:
        return None


def failure_report(error: MindcladeError) -> FailureReport:
    """Reduce any SDK error to the bounded facts an operator acts on.

    Every value is read from the error itself: the stable code, the SDK's own
    retryability decision, the server's retry-after budget, the correlation
    identifiers that a successful call also reports, and the validated field
    violations. The error hierarchy is shared by all four language SDKs, so this
    projection keeps the same shape wherever it is written.
    """

    return FailureReport(
        code=error.code,
        retryable=error.retryable,
        retry_after_seconds=error.retry_after,
        request_id=error.request_id,
        trace_id=error.trace_id,
        invalid_fields=tuple(violation.field for violation in error.field_violations),
    )
