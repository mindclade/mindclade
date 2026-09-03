"""List operations through the SDK's auto-paginating page type."""

from __future__ import annotations

from mindclade_internal_sdk import CallOptions, Client, Page, PaginationLimits
from mindclade_internal_sdk.resources import Operation


def collect_operations(
    client: Client,
    *,
    max_items: int = 1000,
    page_size: int = 100,
    options: CallOptions | None = None,
) -> list[Operation]:
    """Collect every listed operation, crossing page boundaries inside the SDK.

    Iterating the returned page follows the server's opaque cursor for as long
    as the declared budgets allow, so this example threads no page token, writes
    no page loop, and cannot present a truncated list as a complete one: the SDK
    raises once either budget is spent instead of stopping quietly.
    """

    page = client.operations.list(
        options=options,
        limits=PaginationLimits(max_items=max_items, page_size=page_size),
    )
    return list(page)


def first_operation_page(
    client: Client,
    *,
    page_size: int = 100,
    options: CallOptions | None = None,
) -> Page[Operation]:
    """Return the first page itself, for a caller that checkpoints the cursor.

    One value serves both styles. ``items`` and ``next_page_token`` are the
    page-level view a caller persists before acknowledging work, ``response`` is
    the generated ``ListOperationsResponse`` exactly as the server sent it, and
    ``next_page()`` resumes under the same budget the first page was fetched
    with.
    """

    return client.operations.list(options=options, limits=PaginationLimits(page_size=page_size))
