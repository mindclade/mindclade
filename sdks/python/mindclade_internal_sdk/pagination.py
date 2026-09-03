"""Transparent auto-pagination over opaque list cursors under explicit budgets.

Every ergonomic list method returns a :class:`Page` (or :class:`AsyncPage`).
A page iterates its service's items transparently across page boundaries while
still exposing page-level access — ``has_next_page``, ``next_page()``,
``pages()`` — and the generated ``List*Response`` it was built from. Unknown
attribute reads delegate to that response, so the generated message stays the
only wire model and existing call sites keep working unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from google.protobuf.message import Message

from .errors import PaginationLimitError, ProtocolError

_DEFAULT_MAX_PAGES = 100
_DEFAULT_MAX_ITEMS = 10_000
_DEFAULT_PAGE_SIZE = 100
_HARD_MAX_PAGES = 1_000
_HARD_MAX_ITEMS = 1_000_000
_HARD_MAX_PAGE_SIZE = 1_000


@dataclass(frozen=True, slots=True)
class PaginationLimits:
    """Hard bounds for automatic traversal of opaque-token list pages."""

    max_pages: int = _DEFAULT_MAX_PAGES
    max_items: int = _DEFAULT_MAX_ITEMS
    page_size: int = _DEFAULT_PAGE_SIZE
    """Page size applied when a caller's list request leaves one unset."""

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("max_pages", self.max_pages, _HARD_MAX_PAGES),
            ("max_items", self.max_items, _HARD_MAX_ITEMS),
            ("page_size", self.page_size, _HARD_MAX_PAGE_SIZE),
        ):
            if type(value) is not int or value <= 0 or value > maximum:
                raise ValueError(f"{label} must be an integer in [1, {maximum}]")


@dataclass(frozen=True, slots=True)
class PageBudget:
    """Running page and item accounting shared by one traversal."""

    limits: PaginationLimits
    pages_read: int = 1
    """1-based index of the page carrying this budget."""
    items_read: int = 0
    """Items materialized by the pages *before* the one carrying this budget."""

    def advanced(self, items: int) -> PageBudget:
        """Account for ``items`` on the current page and move to the next one."""

        return PageBudget(
            limits=self.limits,
            pages_read=self.pages_read + 1,
            items_read=self.items_read + items,
        )

    def check(self) -> None:
        """Fail closed once a traversal passes either declared budget."""

        if self.pages_read > self.limits.max_pages:
            raise PaginationLimitError("automatic pagination exceeded its page budget")
        if self.items_read > self.limits.max_items:
            raise PaginationLimitError("automatic pagination exceeded its item budget")


def checked_next_token(next_page_token: object, seen: Iterable[str]) -> str:
    """Reject a cursor that is not opaque text or that the traversal already followed."""

    if not isinstance(next_page_token, str):
        raise ProtocolError("list response returned a non-text page token")
    if next_page_token and next_page_token in seen:
        raise ProtocolError("list response repeated an opaque page token")
    return next_page_token


def _response_next_token(response: Message) -> object:
    dynamic = cast(Any, response)
    if not response.HasField("page"):
        return ""
    return cast(object, dynamic.page.next_page_token)


def _items(response: Message, items_field: str) -> tuple[Any, ...]:
    return tuple(cast(Sequence[Any], getattr(response, items_field)))


def next_request[RequestT: Message](request: RequestT, page_token: str) -> RequestT:
    """Copy a validated list request and move it onto the server's next cursor.

    The token is forwarded verbatim; this SDK never parses, rewrites, or infers
    structure from an opaque cursor.
    """

    follow = type(request)()
    follow.CopyFrom(request)
    cast(Any, follow).page.page_token = page_token
    return follow


def apply_default_page_size(request: Message, limits: PaginationLimits | None) -> None:
    """Give a list request without an explicit page size the SDK's default.

    Service-specific maxima are validated by each facade before this runs, so
    this only fills the unset case and never widens a caller's request.
    """

    dynamic = cast(Any, request)
    if cast(int, dynamic.page.page_size) == 0:
        dynamic.page.page_size = (limits or PaginationLimits()).page_size


def _seeded(token: str) -> frozenset[str]:
    """Seed a traversal's cursor history with the first page's own token."""

    return frozenset({token}) if token else frozenset[str]()


def _extended(seen: frozenset[str], following_token: str) -> frozenset[str]:
    """Validate the server's next cursor against every cursor already followed."""

    checked = checked_next_token(following_token, seen)
    return (seen | frozenset({checked})) if checked else seen


@dataclass(frozen=True, slots=True)
class Page[ItemT]:
    """One list page that also iterates every following page transparently."""

    items: tuple[ItemT, ...]
    next_page_token: str
    response: Message
    """The generated ``List*Response`` exactly as the server returned it."""
    fetch: Callable[[str], Page[ItemT]] = field(repr=False, compare=False)
    budget: PageBudget = field(repr=False, compare=False)
    seen: frozenset[str] = field(repr=False, compare=False, default=frozenset())

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown reads to the generated response message."""

        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "response"), name)

    def __len__(self) -> int:
        """Return the item count of this page, not of the whole traversal."""

        return len(self.items)

    @property
    def has_next_page(self) -> bool:
        return bool(self.next_page_token)

    def next_page(self) -> Page[ItemT]:
        """Fetch the following page through the same validated facade method."""

        if not self.next_page_token:
            raise ValueError("list page has no next page")
        budget = self.budget.advanced(len(self.items))
        budget.check()
        following = self.fetch(self.next_page_token)
        seen = _extended(self.seen, following.next_page_token)
        return replace(following, budget=budget, seen=seen)

    def pages(self) -> Iterator[Page[ItemT]]:
        """Walk this page and every following page under the page budget."""

        page = self
        while True:
            yield page
            if not page.has_next_page:
                return
            page = page.next_page()

    def __iter__(self) -> Iterator[ItemT]:
        """Iterate items across page boundaries under the item budget."""

        for page in self.pages():
            consumed = page.budget.items_read
            limit = page.budget.limits.max_items
            for item in page.items:
                consumed += 1
                if consumed > limit:
                    raise PaginationLimitError("automatic pagination exceeded its item budget")
                yield item


@dataclass(frozen=True, slots=True)
class AsyncPage[ItemT]:
    """Asyncio counterpart to :class:`Page` with identical bounds."""

    items: tuple[ItemT, ...]
    next_page_token: str
    response: Message
    """The generated ``List*Response`` exactly as the server returned it."""
    fetch: Callable[[str], Awaitable[AsyncPage[ItemT]]] = field(repr=False, compare=False)
    budget: PageBudget = field(repr=False, compare=False)
    seen: frozenset[str] = field(repr=False, compare=False, default=frozenset())

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown reads to the generated response message."""

        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "response"), name)

    def __len__(self) -> int:
        """Return the item count of this page, not of the whole traversal."""

        return len(self.items)

    @property
    def has_next_page(self) -> bool:
        return bool(self.next_page_token)

    async def next_page(self) -> AsyncPage[ItemT]:
        """Fetch the following page through the same validated facade method."""

        if not self.next_page_token:
            raise ValueError("list page has no next page")
        budget = self.budget.advanced(len(self.items))
        budget.check()
        following = await self.fetch(self.next_page_token)
        seen = _extended(self.seen, following.next_page_token)
        return replace(following, budget=budget, seen=seen)

    async def pages(self) -> AsyncIterator[AsyncPage[ItemT]]:
        """Walk this page and every following page under the page budget."""

        page = self
        while True:
            yield page
            if not page.has_next_page:
                return
            page = await page.next_page()

    async def __aiter__(self) -> AsyncIterator[ItemT]:
        """Iterate items across page boundaries under the item budget."""

        async for page in self.pages():
            consumed = page.budget.items_read
            limit = page.budget.limits.max_items
            for item in page.items:
                consumed += 1
                if consumed > limit:
                    raise PaginationLimitError("automatic pagination exceeded its item budget")
                yield item


def sync_page[ItemT](
    response: Message,
    *,
    items_field: str,
    fetch: Callable[[str], Page[ItemT]],
    limits: PaginationLimits | None = None,
) -> Page[ItemT]:
    """Wrap a validated list response as an auto-paginating page."""

    budget = PageBudget(limits=limits or PaginationLimits())
    budget.check()
    token = checked_next_token(_response_next_token(response), frozenset())
    return Page(
        items=cast(tuple[ItemT, ...], _items(response, items_field)),
        next_page_token=token,
        response=response,
        fetch=fetch,
        budget=budget,
        seen=_seeded(token),
    )


def async_page[ItemT](
    response: Message,
    *,
    items_field: str,
    fetch: Callable[[str], Awaitable[AsyncPage[ItemT]]],
    limits: PaginationLimits | None = None,
) -> AsyncPage[ItemT]:
    """Wrap a validated list response as an awaitable auto-paginating page."""

    budget = PageBudget(limits=limits or PaginationLimits())
    budget.check()
    token = checked_next_token(_response_next_token(response), frozenset())
    return AsyncPage(
        items=cast(tuple[ItemT, ...], _items(response, items_field)),
        next_page_token=token,
        response=response,
        fetch=fetch,
        budget=budget,
        seen=_seeded(token),
    )


def paginate[T](
    fetch_page: Callable[[str], tuple[Iterable[T], str]],
    *,
    initial_page_token: str = "",
    limits: PaginationLimits | None = None,
) -> Iterator[T]:
    """Lazily traverse a caller-supplied page fetcher under explicit bounds.

    Ergonomic list methods already return :class:`Page`; this remains for a
    caller driving ``client.generated`` or a hand-rolled fetch loop. Repeated
    tokens and budget exhaustion raise typed SDK errors rather than silently
    returning a partial collection.
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
        next_token = checked_next_token(raw_next_token, seen)
        if next_token:
            seen.add(next_token)
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
        next_token = checked_next_token(raw_next_token, seen)
        if next_token:
            seen.add(next_token)
        for item in items:
            if item_count >= policy.max_items:
                raise PaginationLimitError("automatic pagination exceeded its item budget")
            item_count += 1
            yield item
        if not next_token:
            return
        token = next_token
