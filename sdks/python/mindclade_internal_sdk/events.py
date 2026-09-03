"""Exact-version immutable event decoding for private SDK consumers."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from mindclade.common.v1 import event_envelope_pb2
from mindclade.events.registry import EVENT_REGISTRATIONS
from mindclade.job.v1 import job_requested_pb2

_EVENT_TYPE = "mindclade.events.job.v1.JobRequested"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_JOB_NAME = re.compile(r"jobs/[A-Za-z0-9_.-]{1,255}\Z")
_MAX_ENVELOPE_BYTES = 8 << 20
_MAX_EVENT_PAYLOAD_BYTES = 64 << 10


class EventRejectedError(ValueError):
    """An immutable event delivery failed its registered contract."""


@dataclass(frozen=True, slots=True)
class JobRequestedDelivery:
    """Verified JobRequested facts needed by SDK consumers, not a wire model."""

    event_id: str
    job_id: str
    configuration_digest: str
    request_id: str
    trace_id: str


def decode_job_requested_delivery(
    serialized: bytes,
    *,
    tenant_id: str,
    project_id: str,
) -> JobRequestedDelivery:
    """Validate the registered exact event version before any service call."""

    if not serialized or len(serialized) > _MAX_ENVELOPE_BYTES:
        raise EventRejectedError("event envelope size is outside policy")
    envelope = event_envelope_pb2.EventEnvelope()
    try:
        envelope.ParseFromString(serialized)
    except Exception as error:
        raise EventRejectedError("event envelope is not valid protobuf") from error
    registration = next(
        (
            registration
            for registration in EVENT_REGISTRATIONS
            if registration.full_name == _EVENT_TYPE
        ),
        None,
    )
    if registration is None:
        raise EventRejectedError("event type is not registered")
    if (
        registration.compatibility_policy != "exact-version"
        or envelope.event_type != registration.full_name
        or envelope.event_version != registration.version
        or envelope.payload_content_type != registration.content_type
        or envelope.tenant_id != tenant_id
        or envelope.project_id != project_id
        or not envelope.event_id
        or envelope.aggregate_sequence <= 0
        or not envelope.HasField("occurred_at")
        or not envelope.HasField("recorded_at")
        or not envelope.payload
        or len(envelope.payload) > _MAX_EVENT_PAYLOAD_BYTES
    ):
        raise EventRejectedError("event identity, version, scope, or timing is invalid")
    expected_payload_digest = "sha256:" + hashlib.sha256(envelope.payload).hexdigest()
    if not hmac.compare_digest(envelope.payload_digest, expected_payload_digest):
        raise EventRejectedError("event payload digest verification failed")
    event = job_requested_pb2.JobRequested()
    try:
        event.ParseFromString(envelope.payload)
    except Exception as error:
        raise EventRejectedError("payload is not a JobRequested protobuf") from error
    if event.SerializeToString(deterministic=True) != envelope.payload:
        raise EventRejectedError("JobRequested payload is not canonical")
    if (
        _JOB_NAME.fullmatch(event.job_id) is None
        or _DIGEST.fullmatch(event.configuration_digest) is None
        or envelope.job_id != event.job_id
    ):
        raise EventRejectedError("JobRequested identity or configuration digest is invalid")
    if envelope.HasField("subject") and (
        envelope.subject.resource_type not in ("", "job")
        or envelope.subject.resource_id not in ("", event.job_id.removeprefix("jobs/"))
    ):
        raise EventRejectedError("event subject does not identify the requested job")
    return JobRequestedDelivery(
        event_id=envelope.event_id,
        job_id=event.job_id,
        configuration_digest=event.configuration_digest,
        request_id=envelope.request_id or envelope.event_id,
        trace_id=envelope.trace_id or envelope.event_id,
    )
