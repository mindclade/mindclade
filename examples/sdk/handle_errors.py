"""Act on failures through the SDK error hierarchy, never on raw status codes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mindclade_internal_sdk import CallOptions, Client, MindcladeError, NotFoundError
from mindclade_internal_sdk.resources import ArtifactRef


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


def download_artifact_if_present(
    client: Client,
    *,
    alias: str,
    destination: Path,
    parent: str | None = None,
    options: CallOptions | None = None,
) -> ArtifactRef | None:
    """Publish the aliased artifact, or return ``None`` when it does not exist.

    Exactly one typed class is caught, because a missing alias is the only
    failure this caller can act on. Authentication, authorization, conflict,
    quota and service failures keep the class the SDK gave them and reach the
    caller unchanged. Nothing here inspects a gRPC status, and nothing retries:
    the SDK already retried whatever was safe to retry before raising.
    """

    try:
        artifact = client.artifacts.resolve_alias(alias, parent=parent, options=options)
    except NotFoundError:
        return None
    client.artifacts.download_file(artifact, destination, options=options)
    return artifact


def failure_report(error: MindcladeError) -> FailureReport:
    """Reduce any SDK error to the bounded facts an operator acts on.

    Every value is read from the error itself: the stable code, the SDK's own
    retryability decision, the server's retry-after budget, the correlation
    identifiers that also appear on a successful call, and the validated field
    violations. The error hierarchy is shared by all four language SDKs, so this
    projection stays the same shape wherever it is written.
    """

    return FailureReport(
        code=error.code,
        retryable=error.retryable,
        retry_after_seconds=error.retry_after,
        request_id=error.request_id,
        trace_id=error.trace_id,
        invalid_fields=tuple(violation.field for violation in error.field_violations),
    )
