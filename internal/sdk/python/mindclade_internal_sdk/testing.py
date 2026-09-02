"""Hermetic transports for repository-internal SDK tests and consumer fakes."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import event_envelope_pb2
from mindclade.internal.artifact.v1 import artifact_service_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import job_pb2, job_requested_pb2

from .transport import Metadata

SyncUnaryHandler = Callable[[Message, float, Metadata], Message]
SyncStreamHandler = Callable[[Message, float, Metadata], Iterable[Message]]
AsyncUnaryHandler = Callable[[Message, float, Metadata], Message]
AsyncStreamHandler = Callable[[Message, float, Metadata], AsyncIterator[Message]]


def get_job_request_name(request: Message) -> str:
    """Inspect a generated GetJob request without exposing its module to a consumer test."""

    if not isinstance(request, job_service_pb2.GetJobRequest):
        raise TypeError("expected the SDK's generated GetJob request")
    return request.name


def artifact_download_request_digest(request: Message) -> str:
    """Inspect a generated artifact download request behind the SDK fake seam."""

    if not isinstance(request, artifact_service_pb2.DownloadArtifactRequest):
        raise TypeError("expected the SDK's generated DownloadArtifact request")
    return request.digest


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """Payload-free call record safe to inspect in tests."""

    method: str
    timeout: float
    metadata_keys: tuple[str, ...]


class FakeSyncTransport:
    def __init__(self) -> None:
        self.unary_handlers: dict[str, SyncUnaryHandler] = {}
        self.response_metadata: dict[str, Metadata] = {}
        self.stream_handlers: dict[str, SyncStreamHandler] = {}
        self.calls: list[RecordedCall] = []
        self.closed = False

    def unary_unary(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Message:
        self.calls.append(RecordedCall(method, timeout, tuple(sorted(key for key, _ in metadata))))
        return self.unary_handlers[method](request, timeout, metadata)

    def unary_unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> tuple[Message, Metadata]:
        response = self.unary_unary(method, request, timeout=timeout, metadata=metadata)
        return response, self.response_metadata.get(method, ())

    def unary_stream(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Iterator[Message]:
        self.calls.append(RecordedCall(method, timeout, tuple(sorted(key for key, _ in metadata))))
        yield from self.stream_handlers[method](request, timeout, metadata)

    def close(self) -> None:
        self.closed = True


class FakeAsyncTransport:
    def __init__(self) -> None:
        self.unary_handlers: dict[str, AsyncUnaryHandler] = {}
        self.response_metadata: dict[str, Metadata] = {}
        self.stream_handlers: dict[str, AsyncStreamHandler] = {}
        self.calls: list[RecordedCall] = []
        self.closed = False

    async def unary_unary(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Message:
        self.calls.append(RecordedCall(method, timeout, tuple(sorted(key for key, _ in metadata))))
        return self.unary_handlers[method](request, timeout, metadata)

    async def unary_unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> tuple[Message, Metadata]:
        response = await self.unary_unary(method, request, timeout=timeout, metadata=metadata)
        return response, self.response_metadata.get(method, ())

    async def unary_stream(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> AsyncIterator[Message]:
        self.calls.append(RecordedCall(method, timeout, tuple(sorted(key for key, _ in metadata))))
        async for item in self.stream_handlers[method](request, timeout, metadata):
            yield item

    async def close(self) -> None:
        self.closed = True


def artifact_fixture(
    content: bytes, *, media_type: str = "application/json"
) -> artifact_reference_pb2.ArtifactRef:
    """Build a complete provider-neutral artifact identity for consumer tests."""

    return artifact_reference_pb2.ArtifactRef(
        digest="sha256:" + hashlib.sha256(content).hexdigest(),
        media_type=media_type,
        size_bytes=len(content),
    )


def job_response_fixture(
    configuration: artifact_reference_pb2.ArtifactRef,
    *,
    input_artifact: artifact_reference_pb2.ArtifactRef | None = None,
    tenant_id: str = "tenant-1",
    project_id: str = "project-1",
) -> job_service_pb2.GetJobResponse:
    """Build one valid durable job response behind the SDK fake boundary."""

    job = job_pb2.Job(
        job_id="jobs/job-1",
        operation_id="operations/op-1",
        tenant_id=tenant_id,
        project_id=project_id,
        state=job_pb2.JOB_STATE_RUNNING,
        resource_version=1,
        configuration=configuration,
        etag="job-etag-1",
    )
    if input_artifact is not None:
        job.input.CopyFrom(input_artifact)
    return job_service_pb2.GetJobResponse(job=job)


def artifact_download_fixture(
    artifact: artifact_reference_pb2.ArtifactRef,
    content: bytes,
    *,
    offset: int = 0,
    complete: bool = True,
) -> artifact_service_pb2.DownloadArtifactResponse:
    """Build one digest-bound download response for a consumer fake."""

    return artifact_service_pb2.DownloadArtifactResponse(
        artifact=artifact,
        offset=offset,
        data=content,
        chunk_digest="sha256:" + hashlib.sha256(content).hexdigest(),
        complete=complete,
    )


def job_requested_delivery_fixture(
    configuration_digest: str,
    *,
    tenant_id: str = "tenant-1",
    project_id: str = "project-1",
    event_version: int = 1,
    payload_digest: str | None = None,
) -> bytes:
    """Encode a deterministic immutable delivery for consumer tests."""

    event = job_requested_pb2.JobRequested(
        job_id="jobs/job-1",
        configuration_digest=configuration_digest,
    )
    payload = event.SerializeToString(deterministic=True)
    timestamp = Timestamp()
    timestamp.FromDatetime(datetime.now(UTC))
    envelope = event_envelope_pb2.EventEnvelope(
        event_id="events/event-1",
        event_type="mindclade.events.job.v1.JobRequested",
        event_version=event_version,
        occurred_at=timestamp,
        recorded_at=timestamp,
        tenant_id=tenant_id,
        project_id=project_id,
        aggregate_sequence=1,
        request_id="request-1",
        trace_id="trace-1",
        job_id=event.job_id,
        payload=payload,
        payload_digest=payload_digest or "sha256:" + hashlib.sha256(payload).hexdigest(),
        payload_content_type="application/x-protobuf; deterministic=true",
    )
    envelope.subject.resource_type = "job"
    envelope.subject.resource_id = "job-1"
    return envelope.SerializeToString(deterministic=True)
