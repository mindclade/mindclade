"""Credential contracts for the private Mindclade SDK."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Protocol, cast, runtime_checkable

import requests

_REFRESH_SKEW = timedelta(seconds=30)
_MAX_TOKEN_LIFETIME = timedelta(minutes=65)


@dataclass(frozen=True, slots=True)
class AccessToken:
    """One short-lived bearer token whose value is deliberately not printable."""

    value: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not self.value
            or len(self.value) > 16 * 1024
            or any(not 0x21 <= ord(character) <= 0x7E for character in self.value)
        ):
            raise ValueError("access token must contain bounded visible ASCII")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("access token expiry must be timezone-aware")

    @property
    def expired(self) -> bool:
        return self.expires_at - datetime.now(UTC) <= _REFRESH_SKEW

    def authorization_header(self, *, now: datetime | None = None) -> str:
        """Return a safe bearer value only while this short-lived token is usable."""

        observed_at = now or datetime.now(UTC)
        remaining = self.expires_at - observed_at
        if remaining <= _REFRESH_SKEW:
            raise ValueError("workload-identity token is expired or inside its refresh window")
        if remaining > _MAX_TOKEN_LIFETIME:
            raise ValueError("workload-identity token exceeds the maximum lifetime")
        return f"Bearer {self.value}"


@runtime_checkable
class SyncTokenProvider(Protocol):
    """Concurrency-safe source of short-lived workload-identity tokens."""

    def get_token(self, *, timeout: float) -> AccessToken:
        """Return a token while honoring the caller's remaining seconds."""

        ...


@runtime_checkable
class AsyncTokenProvider(Protocol):
    """Non-blocking source of short-lived workload-identity tokens."""

    async def get_token(self, *, timeout: float) -> AccessToken:
        """Return a token while honoring the caller's remaining seconds."""

        ...


def _validate_audience(audience: str) -> str:
    normalized = audience.strip()
    if (
        not normalized
        or len(normalized) > 1024
        or normalized != audience
        or any(character.isspace() or ord(character) < 0x21 for character in normalized)
    ):
        raise ValueError("workload-identity audience is invalid")
    return normalized


_fetch_google_id_token = cast(
    Callable[[Callable[..., object], str], object],
    vars(import_module("google.oauth2.id_token"))["fetch_id_token"],
)
_decode_google_jwt = cast(
    Callable[[str, object | None, bool], Mapping[str, object]],
    vars(import_module("google.auth.jwt"))["decode"],
)
_google_auth_request = cast(
    Callable[..., object],
    vars(import_module("google.auth.transport.requests"))["Request"],
)


class _DeadlineRequest:
    """google-auth HTTP transport whose individual calls share one deadline."""

    def __init__(self, session: requests.Session, *, deadline: float) -> None:
        self._delegate = cast(Callable[..., object], _google_auth_request(session=session))
        self._deadline = deadline

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 120,
        **kwargs: object,
    ) -> object:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("credential acquisition deadline expired")
        return self._delegate(
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=min(float(timeout), remaining),
            **kwargs,
        )


class GoogleWorkloadIdentityProvider:
    """ADC-backed, audience-bound Google ID tokens with singleflight refresh.

    The provider never persists credentials. Every metadata, STS, or service
    account exchange performed by google-auth shares the SDK call's remaining
    deadline. Provider detail is intentionally normalized by the invoker.
    """

    def __init__(self, audience: str) -> None:
        self._audience = _validate_audience(audience)
        self._condition = threading.Condition()
        self._cached: AccessToken | None = None
        self._refreshing = False

    def get_token(self, *, timeout: float) -> AccessToken:
        if not math.isfinite(timeout) or timeout <= 0:
            raise TimeoutError("credential acquisition deadline expired")
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if self._cached is not None and not self._cached.expired:
                    return self._cached
                if not self._refreshing:
                    self._refreshing = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("credential acquisition deadline expired")
                self._condition.wait(timeout=remaining)

        try:
            token = self._fetch(deadline)
        except BaseException:
            with self._condition:
                self._refreshing = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._cached = token
            self._refreshing = False
            self._condition.notify_all()
            return token

    def _fetch(self, deadline: float) -> AccessToken:
        if deadline <= time.monotonic():
            raise TimeoutError("credential acquisition deadline expired")
        with requests.Session() as session:
            request = _DeadlineRequest(session, deadline=deadline)
            encoded = _fetch_google_id_token(request, self._audience)
        if not isinstance(encoded, str):
            raise ValueError("workload-identity provider returned an invalid token")
        claims = _decode_google_jwt(encoded, None, False)
        if claims.get("aud") != self._audience:
            raise ValueError("workload-identity token audience does not match")
        raw_expiry = claims.get("exp")
        if not isinstance(raw_expiry, (int, float)) or not math.isfinite(raw_expiry):
            raise ValueError("workload-identity token has no valid expiry")
        token = AccessToken(encoded, datetime.fromtimestamp(raw_expiry, tz=UTC))
        # Apply both refresh-skew and maximum-lifetime validation now so a bad
        # token is never admitted to the shared cache.
        token.authorization_header()
        return token


class AsyncGoogleWorkloadIdentityProvider:
    """Async adapter over the same bounded, concurrency-safe ADC provider."""

    def __init__(self, audience: str) -> None:
        self._provider = GoogleWorkloadIdentityProvider(audience)

    async def get_token(self, *, timeout: float) -> AccessToken:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._provider.get_token, timeout=timeout),
                timeout=timeout,
            )
        except TimeoutError:
            raise
