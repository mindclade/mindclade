"""Per-call behavior and safe observation contracts."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from .errors import PaginationLimitError, ProtocolError

_DEFAULT_MAX_PAGES = 100
_DEFAULT_MAX_ITEMS = 10_000
_HARD_MAX_PAGES = 1_000
_HARD_MAX_ITEMS = 1_000_000


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
    lease_token: str | None = field(default=None, repr=False)

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


@dataclass(frozen=True, slots=True)
class PaginationLimits:
    """Hard bounds for automatic traversal of opaque-token list pages."""

    max_pages: int = _DEFAULT_MAX_PAGES
    max_items: int = _DEFAULT_MAX_ITEMS

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("max_pages", self.max_pages, _HARD_MAX_PAGES),
            ("max_items", self.max_items, _HARD_MAX_ITEMS),
        ):
            if type(value) is not int or value <= 0 or value > maximum:
                raise ValueError(f"{label} must be an integer in [1, {maximum}]")


def _checked_next_token(next_page_token: object, seen: set[str]) -> str:
    if not isinstance(next_page_token, str):
        raise ProtocolError("list response returned a non-text page token")
    if next_page_token and next_page_token in seen:
        raise ProtocolError("list response repeated an opaque page token")
    if next_page_token:
        seen.add(next_page_token)
    return next_page_token


def paginate[T](
    fetch_page: Callable[[str], tuple[Iterable[T], str]],
    *,
    initial_page_token: str = "",
    limits: PaginationLimits | None = None,
) -> Iterator[T]:
    """Lazily traverse facade list calls under explicit item and page bounds.

    ``fetch_page`` receives an opaque token exactly as returned by the prior
    page and returns ``(items, next_page_token)``. It should call an ergonomic
    facade so the normal identity, deadline, retry, and response checks remain
    active. Repeated tokens and budget exhaustion raise typed SDK errors rather
    than silently returning a partial collection.
    """

    policy = limits or PaginationLimits()
    token = initial_page_token
    seen: set[str] = {token} if token else set()
    page_count = 0
    item_count = 0
    while True:
        if page_count >= policy.max_pages:
            raise PaginationLimitError("automatic pagination exceeded its page budget")
        if item_count >= policy.max_items:
            raise PaginationLimitError("automatic pagination exceeded its item budget")
        items, raw_next_token = fetch_page(token)
        page_count += 1
        next_token = _checked_next_token(raw_next_token, seen)
        for item in items:
            if item_count >= policy.max_items:
                raise PaginationLimitError("automatic pagination exceeded its item budget")
            item_count += 1
            yield item
        if not next_token:
            return
        token = next_token


async def apaginate[T](
    fetch_page: Callable[[str], Awaitable[tuple[Iterable[T], str]]],
    *,
    initial_page_token: str = "",
    limits: PaginationLimits | None = None,
) -> AsyncIterator[T]:
    """Asynchronous counterpart to :func:`paginate` with identical bounds."""

    policy = limits or PaginationLimits()
    token = initial_page_token
    seen: set[str] = {token} if token else set()
    page_count = 0
    item_count = 0
    while True:
        if page_count >= policy.max_pages:
            raise PaginationLimitError("automatic pagination exceeded its page budget")
        if item_count >= policy.max_items:
            raise PaginationLimitError("automatic pagination exceeded its item budget")
        items, raw_next_token = await fetch_page(token)
        page_count += 1
        next_token = _checked_next_token(raw_next_token, seen)
        for item in items:
            if item_count >= policy.max_items:
                raise PaginationLimitError("automatic pagination exceeded its item budget")
            item_count += 1
            yield item
        if not next_token:
            return
        token = next_token


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
