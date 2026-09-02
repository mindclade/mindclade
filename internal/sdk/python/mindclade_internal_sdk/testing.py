"""Hermetic transports for repository-internal SDK tests and consumer fakes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass

from google.protobuf.message import Message

from .transport import Metadata

SyncUnaryHandler = Callable[[Message, float, Metadata], Message]
SyncStreamHandler = Callable[[Message, float, Metadata], Iterable[Message]]
AsyncUnaryHandler = Callable[[Message, float, Metadata], Message]
AsyncStreamHandler = Callable[[Message, float, Metadata], AsyncIterator[Message]]


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """Payload-free call record safe to inspect in tests."""

    method: str
    timeout: float
    metadata_keys: tuple[str, ...]


class FakeSyncTransport:
    def __init__(self) -> None:
        self.unary_handlers: dict[str, SyncUnaryHandler] = {}
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
