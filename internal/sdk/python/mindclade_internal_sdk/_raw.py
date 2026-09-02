"""Raw responses: the parsed value beside its bounded transport facts.

``client.<namespace>.with_raw_response.<method>(...)`` runs the *same* ergonomic
method — every identity, digest, fence, and protocol check still executes — and
returns a :class:`RawResponse` pairing the method's ordinary return value with
the RPC's status, request id, trace id, and an allowlisted metadata subset.

The capture is a :class:`~contextvars.ContextVar` armed around the call rather
than a per-method wrapper, so there is exactly one implementation of every
method and no validation can drift between the plain and raw surfaces.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Self, cast

import grpc

from ._metadata import safe_metadata

_STREAMING_REJECTION = (
    "streaming methods have no raw response; read the stream's request id from "
    "the call options you supplied"
)
_UNOBSERVED_REJECTION = "method completed without a unary response to report"


@dataclass(frozen=True, slots=True)
class RawResponse[ValueT]:
    """One successful RPC's parsed value beside its bounded transport facts."""

    data: ValueT
    status: grpc.StatusCode
    request_id: str
    trace_id: str
    metadata: Mapping[str, str]
    """Allowlisted response metadata; never credential-bearing."""

    def parse(self) -> ValueT:
        """Return the validated value the ergonomic method produced."""

        return self.data


class _RawCapture:
    """Records the first unary result observed while a raw call is armed."""

    __slots__ = ("_recorded",)

    def __init__(self) -> None:
        self._recorded: tuple[grpc.StatusCode, Mapping[str, str], str, str] | None = None

    def record(
        self,
        status: grpc.StatusCode,
        metadata: Iterable[tuple[str, str | bytes]],
        request_id: str,
        trace_id: str,
    ) -> None:
        if self._recorded is not None:
            return
        safe = safe_metadata(metadata)
        self._recorded = (
            status,
            safe,
            safe.get("x-request-id") or request_id,
            safe.get("x-trace-id") or trace_id,
        )

    def finish[ValueT](self, value: ValueT) -> RawResponse[ValueT]:
        if self._recorded is None:
            raise ValueError(_UNOBSERVED_REJECTION)
        status, metadata, request_id, trace_id = self._recorded
        return RawResponse(
            data=value,
            status=status,
            request_id=request_id,
            trace_id=trace_id,
            metadata=metadata,
        )


_CAPTURE: ContextVar[_RawCapture | None] = ContextVar("mindclade_raw_capture", default=None)


def active_capture() -> _RawCapture | None:
    """Return the capture armed for the call in flight, if any."""

    return _CAPTURE.get()


_STREAMING_MARKER = "__mindclade_streaming__"


def streaming_method[FunctionT: Callable[..., Any]](function: FunctionT) -> FunctionT:
    """Mark a method that returns a live stream rather than a single response.

    A watcher builds its stream eagerly and hands back an iterator, so it is not
    a generator function and cannot be recognised by inspection. The marker
    keeps ``with_raw_response`` rejecting it: a stream has many responses and no
    single set of transport facts to report.
    """

    setattr(function, _STREAMING_MARKER, True)
    return function


def _bound(namespace: object, name: str) -> Callable[..., Any]:
    if name.startswith("_"):
        raise AttributeError(name)
    method = getattr(namespace, name, None)
    if method is None or not callable(method):
        raise AttributeError(name)
    if (
        inspect.isgeneratorfunction(method)
        or inspect.isasyncgenfunction(method)
        or getattr(method, _STREAMING_MARKER, False)
    ):
        raise ValueError(_STREAMING_REJECTION)
    return cast(Callable[..., Any], method)


class RawResponseProxy[NamespaceT]:
    """``with_raw_response`` view over one synchronous resource namespace."""

    __slots__ = ("_namespace",)

    def __init__(self, namespace: NamespaceT) -> None:
        self._namespace = namespace

    def __getattr__(self, name: str) -> Callable[..., RawResponse[Any]]:
        method = _bound(self._namespace, name)

        def invoke(*args: object, **kwargs: object) -> RawResponse[Any]:
            capture = _RawCapture()
            token = _CAPTURE.set(capture)
            try:
                value = cast(object, method(*args, **kwargs))
            finally:
                _CAPTURE.reset(token)
            return capture.finish(value)

        invoke.__name__ = name
        invoke.__doc__ = f"Call {name} and return its value beside safe transport facts."
        return invoke

    def __dir__(self) -> list[str]:
        return [name for name in dir(self._namespace) if not name.startswith("_")]


class AsyncRawResponseProxy[NamespaceT]:
    """``with_raw_response`` view over one asyncio resource namespace."""

    __slots__ = ("_namespace",)

    def __init__(self, namespace: NamespaceT) -> None:
        self._namespace = namespace

    def __getattr__(self, name: str) -> Callable[..., Any]:
        method = _bound(self._namespace, name)

        async def invoke(*args: object, **kwargs: object) -> RawResponse[Any]:
            capture = _RawCapture()
            token = _CAPTURE.set(capture)
            try:
                result = cast(object, method(*args, **kwargs))
                value = await result if inspect.isawaitable(result) else result
            finally:
                _CAPTURE.reset(token)
            return capture.finish(value)

        invoke.__name__ = name
        invoke.__doc__ = f"Await {name} and return its value beside safe transport facts."
        return invoke

    def __dir__(self) -> list[str]:
        return [name for name in dir(self._namespace) if not name.startswith("_")]


class WithRawResponse:
    """Mixin giving a synchronous resource namespace ``with_raw_response``."""

    __slots__ = ()

    @property
    def with_raw_response(self) -> RawResponseProxy[Self]:
        """Return this namespace's raw-response view over the same methods."""

        return RawResponseProxy(self)


class AsyncWithRawResponse:
    """Mixin giving an asyncio resource namespace ``with_raw_response``."""

    __slots__ = ()

    @property
    def with_raw_response(self) -> AsyncRawResponseProxy[Self]:
        """Return this namespace's raw-response view over the same methods."""

        return AsyncRawResponseProxy(self)
