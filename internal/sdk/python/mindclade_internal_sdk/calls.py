"""Per-call behavior and safe observation contracts."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol


def _identifier(label: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 256 or re.search(r"[\r\n\x00]", normalized):
        raise ValueError(f"{label} is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class CallOptions:
    """Behavioral metadata; this is not a duplicate request/wire model."""

    timeout: float | None = None
    request_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    lease_token: str | None = None

    def __post_init__(self) -> None:
        if self.timeout is not None and not 0 < self.timeout <= 300:
            raise ValueError("call timeout must be in (0, 300] seconds")
        for label in ("request_id", "trace_id", "idempotency_key"):
            object.__setattr__(self, label, _identifier(label, getattr(self, label)))
        if self.lease_token is not None:
            token = self.lease_token.strip()
            if not token or len(token) > 4096 or any(character.isspace() for character in token):
                raise ValueError("lease_token is invalid")
            object.__setattr__(self, "lease_token", token)


@dataclass(frozen=True, slots=True)
class PreparedCall:
    timeout: float
    request_id: str
    trace_id: str
    idempotency_key: str | None
    lease_token: str | None = None


@dataclass(frozen=True, slots=True)
class RpcObservation:
    """Bounded telemetry event that deliberately excludes payloads and metadata values."""

    method: str
    attempt: int
    elapsed_seconds: float
    status: str
    request_id: str


class Observer(Protocol):
    def observe(self, event: RpcObservation) -> None: ...


class NullObserver:
    def observe(self, event: RpcObservation) -> None:
        del event


def prepare_call(
    options: CallOptions | None,
    *,
    default_timeout: float,
    require_idempotency: bool,
) -> PreparedCall:
    source = options or CallOptions()
    request_id = source.request_id or str(uuid.uuid4())
    trace_id = source.trace_id or uuid.uuid4().hex
    idempotency_key = source.idempotency_key
    if require_idempotency and idempotency_key is None:
        idempotency_key = str(uuid.uuid4())
    return PreparedCall(
        timeout=source.timeout or default_timeout,
        request_id=request_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        lease_token=source.lease_token,
    )
