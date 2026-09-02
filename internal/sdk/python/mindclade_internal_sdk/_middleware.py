"""The interceptor seam, with credential injection kept outside its reach.

``ClientConfig(middleware=[...])`` accepts ordinary gRPC client interceptors so
a caller can add tracing, mirroring, or fault injection without forking the
SDK. Every caller-supplied interceptor is wrapped in a :class:`CredentialShield`
first, which enforces two rules that are not negotiable:

* an interceptor never *sees* a credential — authorization headers, lease
  tokens, and cookies are removed from the call details handed to it; and
* an interceptor never *removes or forges* one — whatever it returns has its
  credential-bearing keys stripped, and the SDK's own entries are restored
  verbatim immediately before the call goes out.

Credential injection therefore stays inside ``_invocation._authorized_metadata``
where it can be reasoned about, and middleware operates on everything else.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, cast

import grpc

from ._metadata import is_credential_metadata_key

MetadataEntries = tuple[tuple[str, Any], ...]

MAX_MIDDLEWARE = 8

_INTERCEPTOR_METHODS = ("intercept_unary_unary", "intercept_unary_stream")


def is_interceptor(candidate: object) -> bool:
    """Return whether an object implements at least one gRPC client interceptor hook."""

    return any(callable(getattr(candidate, name, None)) for name in _INTERCEPTOR_METHODS)


def _entries(metadata: object) -> MetadataEntries:
    if metadata is None:
        return ()
    return tuple((str(key), value) for key, value in cast(Iterable[Any], metadata))


def _credentials(metadata: MetadataEntries) -> MetadataEntries:
    return tuple(entry for entry in metadata if is_credential_metadata_key(entry[0]))


def _without_credentials(metadata: MetadataEntries) -> MetadataEntries:
    return tuple(entry for entry in metadata if not is_credential_metadata_key(entry[0]))


class _ShieldedCallDetails(grpc.ClientCallDetails):
    """A gRPC call description with substituted metadata and nothing else changed."""

    __slots__ = ("compression", "credentials", "metadata", "method", "timeout", "wait_for_ready")

    def __init__(self, source: grpc.ClientCallDetails, metadata: MetadataEntries) -> None:
        self.method = cast(Any, getattr(source, "method", None))
        self.timeout = cast(Any, getattr(source, "timeout", None))
        self.metadata = cast(Any, metadata)
        self.credentials = cast(Any, getattr(source, "credentials", None))
        self.wait_for_ready = cast(Any, getattr(source, "wait_for_ready", None))
        self.compression = cast(Any, getattr(source, "compression", None))


def _rebuilt(source: object, metadata: MetadataEntries) -> Any:
    """Return ``source`` with ``metadata`` substituted, preserving its own type when possible."""

    replace = getattr(source, "_replace", None)
    if callable(replace):
        # ``grpc`` and ``grpc.aio`` both model call details as named tuples in
        # their own helpers; honouring that keeps interceptor chains composable.
        return cast(Any, replace(metadata=metadata))
    return _ShieldedCallDetails(cast(grpc.ClientCallDetails, source), metadata)


class _Shield:
    """Shared credential discipline for the synchronous and asyncio shields."""

    __slots__ = ("_interceptor",)

    def __init__(self, interceptor: object) -> None:
        if not is_interceptor(interceptor):
            raise TypeError("middleware entries must be gRPC client interceptors")
        self._interceptor = interceptor

    def _prepare(
        self,
        details: object,
    ) -> tuple[Any, MetadataEntries, Callable[[Any], Any]]:
        """Hide SDK credentials from the interceptor and restore them afterwards."""

        original = _entries(getattr(details, "metadata", None))
        credentials = _credentials(original)
        visible = _rebuilt(details, _without_credentials(original))

        def restore(inner: Any) -> Any:
            merged = _without_credentials(_entries(getattr(inner, "metadata", None)))
            return _rebuilt(inner, merged + credentials)

        return visible, credentials, restore

    def _hook(self, name: str) -> Callable[..., Any] | None:
        hook = getattr(self._interceptor, name, None)
        return cast(Callable[..., Any], hook) if callable(hook) else None


class CredentialShield(
    _Shield,
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
):
    """Synchronous shield around one caller-supplied interceptor."""

    __slots__ = ()

    def _intercept(
        self,
        name: str,
        continuation: Callable[[Any, Any], Any],
        client_call_details: Any,
        request: Any,
    ) -> Any:
        hook = self._hook(name)
        if hook is None:
            return continuation(client_call_details, request)
        visible, _, restore = self._prepare(client_call_details)

        def guarded(inner_details: Any, inner_request: Any) -> Any:
            return continuation(restore(inner_details), inner_request)

        return hook(guarded, visible, request)

    def intercept_unary_unary(
        self,
        continuation: Callable[[Any, Any], Any],
        client_call_details: Any,
        request: Any,
    ) -> Any:
        return self._intercept("intercept_unary_unary", continuation, client_call_details, request)

    def intercept_unary_stream(
        self,
        continuation: Callable[[Any, Any], Any],
        client_call_details: Any,
        request: Any,
    ) -> Any:
        return self._intercept("intercept_unary_stream", continuation, client_call_details, request)


class AsyncCredentialShield(
    _Shield,
    grpc.aio.UnaryUnaryClientInterceptor,
    grpc.aio.UnaryStreamClientInterceptor,
):
    """Asyncio shield around one caller-supplied interceptor."""

    __slots__ = ()

    async def _intercept(
        self,
        name: str,
        continuation: Callable[[Any, Any], Any],
        client_call_details: Any,
        request: Any,
    ) -> Any:
        hook = self._hook(name)
        if hook is None:
            return await continuation(client_call_details, request)
        visible, _, restore = self._prepare(client_call_details)

        async def guarded(inner_details: Any, inner_request: Any) -> Any:
            return await continuation(restore(inner_details), inner_request)

        return await hook(guarded, visible, request)

    async def intercept_unary_unary(
        self,
        continuation: Callable[[Any, Any], Any],
        client_call_details: Any,
        request: Any,
    ) -> Any:
        return await self._intercept(
            "intercept_unary_unary", continuation, client_call_details, request
        )

    async def intercept_unary_stream(
        self,
        continuation: Callable[[Any, Any], Any],
        client_call_details: Any,
        request: Any,
    ) -> Any:
        return await self._intercept(
            "intercept_unary_stream", continuation, client_call_details, request
        )


def shielded(middleware: Sequence[object]) -> tuple[CredentialShield, ...]:
    """Wrap synchronous middleware so credentials stay inside the SDK."""

    return tuple(CredentialShield(entry) for entry in middleware)


def async_shielded(middleware: Sequence[object]) -> tuple[AsyncCredentialShield, ...]:
    """Wrap asyncio middleware so credentials stay inside the SDK."""

    return tuple(AsyncCredentialShield(entry) for entry in middleware)
