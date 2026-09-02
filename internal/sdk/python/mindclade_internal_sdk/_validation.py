"""Small validation helpers for SDK behavior; wire validation remains server-owned."""

from __future__ import annotations

import re

import grpc
from google.protobuf.message import Message
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import resource_reference_pb2

from .errors import ProtocolError

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_RESOURCE_ID = re.compile(r"[a-z][a-z0-9-]{0,62}")


def required_text(label: str, value: str, *, maximum: int = 1024) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(c in normalized for c in "\r\n\x00"):
        raise ValueError(f"{label} is invalid")
    return normalized


def resource_id(label: str, value: str) -> str:
    normalized = required_text(label, value, maximum=63)
    if _RESOURCE_ID.fullmatch(normalized) is None:
        raise ValueError(f"{label} must match {_RESOURCE_ID.pattern!r}")
    return normalized


def artifact_ref(label: str, value: Message) -> None:
    if not isinstance(value, artifact_reference_pb2.ArtifactRef):
        raise TypeError(f"{label} must be the generated ArtifactRef")
    if _DIGEST.fullmatch(value.digest) is None:
        raise ValueError(f"{label}.digest must be a canonical sha256 digest")
    required_text(f"{label}.media_type", value.media_type, maximum=256)
    if value.size_bytes < 0:
        raise ValueError(f"{label}.size_bytes cannot be negative")


def resource_ref(label: str, value: Message) -> None:
    if not isinstance(value, resource_reference_pb2.ResourceRef):
        raise TypeError(f"{label} must be the generated ResourceRef")
    required_text(f"{label}.name", value.name)


def required_response_message[MessageT: Message](
    response: Message,
    field_name: str,
    expected_type: type[MessageT],
    *,
    label: str,
) -> MessageT:
    """Return a present generated submessage or fail as protocol data loss."""

    try:
        present = response.HasField(field_name)
        value = getattr(response, field_name)
    except (ValueError, AttributeError) as error:
        raise ProtocolError(
            f"{label} response violated its generated contract",
            status=grpc.StatusCode.DATA_LOSS,
        ) from error
    if not present or not isinstance(value, expected_type):
        raise ProtocolError(
            f"{label} response omitted its required resource",
            status=grpc.StatusCode.DATA_LOSS,
        )
    clone = expected_type()
    clone.CopyFrom(value)
    return clone
