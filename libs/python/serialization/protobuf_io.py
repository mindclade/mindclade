from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Protocol, TypeVar

from common.v1.event_envelope_pb2 import EventEnvelope
from common.v1.resource_reference_pb2 import ResourceRef
from google.protobuf.message import Message


class SerializableMessage(Protocol):
    def SerializeToString(  # noqa: N802
        self, *, deterministic: bool = False
    ) -> bytes: ...


def encode_deterministic(message: SerializableMessage) -> bytes:
    return message.SerializeToString(deterministic=True)


MessageT = TypeVar("MessageT", bound=Message)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("event timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def make_event_envelope(
    payload: Message,
    *,
    event_id: str,
    event_version: int,
    tenant_id: str,
    producer: str,
    occurred_at: datetime,
    subject: ResourceRef,
    project_id: str = "",
    trace_id: str = "",
    request_id: str = "",
    correlation_id: str = "",
    causation_id: str = "",
    job_id: str = "",
    run_id: str = "",
    aggregate_sequence: int = 0,
    deduplication_key: str = "",
    classification: int = 0,
    recorded_at: datetime | None = None,
) -> EventEnvelope:
    """Wrap one generated event payload in the authoritative transport envelope."""
    if not event_id or event_version < 1 or not tenant_id or not producer:
        raise ValueError("event identity, version, tenant, and producer are required")
    payload_bytes = encode_deterministic(payload)
    envelope = EventEnvelope(
        event_id=event_id,
        event_type=payload.DESCRIPTOR.full_name,
        event_version=event_version,
        tenant_id=tenant_id,
        project_id=project_id,
        trace_id=trace_id,
        payload_digest="sha256:" + hashlib.sha256(payload_bytes).hexdigest(),
        payload=payload_bytes,
        producer=producer,
        aggregate_sequence=aggregate_sequence,
        request_id=request_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        job_id=job_id,
        run_id=run_id,
        deduplication_key=deduplication_key or event_id,
        payload_content_type="application/x-protobuf; deterministic=true",
        classification=classification,
    )
    envelope.subject.CopyFrom(subject)
    envelope.occurred_at.FromDatetime(_utc(occurred_at))
    envelope.recorded_at.FromDatetime(_utc(recorded_at or occurred_at))
    return envelope


def parse_event_payload(envelope: EventEnvelope, message_type: type[MessageT]) -> MessageT:
    """Verify and decode an envelope as the expected generated event message."""
    expected_type = message_type.DESCRIPTOR.full_name
    if envelope.event_type != expected_type:
        raise ValueError(
            f"event type mismatch: expected {expected_type}, got {envelope.event_type}"
        )
    actual_digest = "sha256:" + hashlib.sha256(envelope.payload).hexdigest()
    if envelope.payload_digest != actual_digest:
        raise ValueError("event payload digest mismatch")
    value = message_type()
    value.ParseFromString(envelope.payload)
    if encode_deterministic(value) != envelope.payload:
        raise ValueError("event payload is not canonical deterministic protobuf")
    return value
