from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import ClassVar, Protocol

from mindclade.common.v1.event_envelope_pb2 import (
    DATA_CLASSIFICATION_UNSPECIFIED,
    DataClassification,
    EventEnvelope,
)
from mindclade.common.v1.resource_reference_pb2 import ResourceRef
from mindclade.events.registry import (
    DETERMINISTIC_PROTOBUF_CONTENT_TYPE,
    require_event_registration,
)


class MessageDescriptor(Protocol):
    full_name: str


class SerializableMessage(Protocol):
    def SerializeToString(  # noqa: N802
        self, *, deterministic: bool = False
    ) -> bytes: ...


class ProtobufMessage(SerializableMessage, Protocol):
    DESCRIPTOR: ClassVar[MessageDescriptor]

    def ParseFromString(self, serialized: bytes) -> int: ...  # noqa: N802


def encode_deterministic(message: SerializableMessage) -> bytes:
    return message.SerializeToString(deterministic=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("event timestamps must be timezone-aware")
    return value.astimezone(UTC)


def make_event_envelope(
    payload: ProtobufMessage,
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
    classification: DataClassification = DATA_CLASSIFICATION_UNSPECIFIED,
    recorded_at: datetime | None = None,
) -> EventEnvelope:
    """Wrap one generated event payload in the authoritative transport envelope."""
    if not event_id or event_version < 1 or not tenant_id or not producer:
        raise ValueError("event identity, version, tenant, and producer are required")
    event_type = payload.DESCRIPTOR.full_name
    registration = require_event_registration(
        event_type,
        event_version,
        DETERMINISTIC_PROTOBUF_CONTENT_TYPE,
    )
    payload_bytes = encode_deterministic(payload)
    envelope = EventEnvelope(
        event_id=event_id,
        event_type=registration.full_name,
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
        payload_content_type=registration.content_type,
        classification=classification,
    )
    envelope.subject.CopyFrom(subject)
    envelope.occurred_at.FromDatetime(_utc(occurred_at))
    envelope.recorded_at.FromDatetime(_utc(recorded_at or occurred_at))
    return envelope


def parse_event_payload[MessageT: ProtobufMessage](
    envelope: EventEnvelope, message_type: type[MessageT]
) -> MessageT:
    """Verify and decode an envelope as the expected generated event message."""
    require_event_registration(
        envelope.event_type,
        envelope.event_version,
        envelope.payload_content_type,
    )
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
