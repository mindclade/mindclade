"""Validated private-SDK configuration with TLS secure by default."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from ._metadata import is_credential_metadata_key
from ._middleware import MAX_MIDDLEWARE, is_interceptor
from ._platform import platform_user_agent
from ._retry import JitterSource
from .auth import AsyncTokenProvider, SyncTokenProvider


class ConfigurationError(ValueError):
    """Raised before any network activity when SDK configuration is unsafe."""


class Environment(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


ENVIRONMENT_ENDPOINTS = MappingProxyType(
    {
        Environment.LOCAL: "127.0.0.1:9443",
        Environment.DEVELOPMENT: "control-plane.development.mindclade.internal:443",
        Environment.STAGING: "control-plane.staging.mindclade.internal:443",
        Environment.PRODUCTION: "control-plane.production.mindclade.internal:443",
    }
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy used only for safe/idempotent calls.

    ``max_delay`` is the contract's ``max_backoff``: it caps both the
    exponential window and any server ``retry-after-ms`` hint. ``jitter`` is an
    injectable randomness seam; leaving it ``None`` uses the SDK's
    cryptographically seeded default.
    """

    max_attempts: int = 4
    base_delay: float = 0.1
    max_delay: float = 2.0
    jitter: JitterSource | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 8:
            raise ConfigurationError("max_attempts must be between 1 and 8")
        if self.base_delay <= 0 or self.max_delay < self.base_delay:
            raise ConfigurationError("retry delays must be positive and monotonically bounded")
        if self.max_delay > 30:
            raise ConfigurationError("retry max_delay cannot exceed 30 seconds")
        if self.jitter is not None and not callable(getattr(self.jitter, "uniform", None)):
            raise ConfigurationError("retry jitter must expose a uniform(upper_bound) method")


def _validated_endpoint(endpoint: str) -> tuple[str, int]:
    if endpoint != endpoint.strip() or any(value in endpoint for value in "\r\n\x00"):
        raise ConfigurationError("endpoint contains whitespace or control characters")
    parsed = urlsplit(f"//{endpoint}")
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("endpoint must be a host:port authority")
    try:
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError("endpoint port is invalid") from error
    if port is None or not 1 <= port <= 65535:
        raise ConfigurationError("endpoint must include a valid port")
    return parsed.hostname, port


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _canonical_https_origin(host: str, port: int) -> str:
    """Return the workload-identity audience derived from a validated endpoint."""

    canonical_host = host.lower()
    try:
        parsed = ipaddress.ip_address(canonical_host)
    except ValueError:
        pass
    else:
        canonical_host = parsed.compressed
    if ":" in canonical_host:
        canonical_host = f"[{canonical_host}]"
    if port == 443:
        return f"https://{canonical_host}"
    return f"https://{canonical_host}:{port}"


def _validate_audience(value: str) -> str:
    if (
        not value
        or len(value) > 1024
        or value != value.strip()
        or any(not 0x21 <= ord(character) <= 0x7E for character in value)
    ):
        raise ConfigurationError("workload-identity audience is invalid")
    return value


_MAX_CUSTOM_METADATA_ENTRIES = 16
_MAX_CUSTOM_METADATA_VALUE_LENGTH = 256
_CUSTOM_METADATA_KEY = re.compile(r"\A[a-z0-9][a-z0-9-]{0,63}\Z")

# Keys the SDK owns. Caller metadata may never shadow one of these, because a
# server reads them as the SDK's own assertions about tenancy and identity.
_RESERVED_METADATA_KEYS = frozenset(
    {
        "idempotency-key",
        "x-request-id",
        "x-trace-id",
        "grpc-timeout",
        "te",
        "user-agent",
    }
)
_RESERVED_METADATA_PREFIX = "x-mindclade-"

_NO_CUSTOM_METADATA: Mapping[str, str] = MappingProxyType({})


def _validated_custom_metadata(values: Mapping[Any, Any]) -> Mapping[str, str]:
    """Validate caller metadata, rejecting anything reserved or credential-bearing."""

    if len(values) > _MAX_CUSTOM_METADATA_ENTRIES:
        raise ConfigurationError(
            f"custom_metadata cannot exceed {_MAX_CUSTOM_METADATA_ENTRIES} entries"
        )
    validated: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            raise ConfigurationError("custom_metadata keys and values must be strings")
        key = raw_key.strip().lower()
        if _CUSTOM_METADATA_KEY.match(key) is None:
            raise ConfigurationError(f"custom_metadata key is invalid: {raw_key!r}")
        if key.endswith("-bin"):
            raise ConfigurationError("custom_metadata cannot carry binary (-bin) keys")
        if key in _RESERVED_METADATA_KEYS or key.startswith(_RESERVED_METADATA_PREFIX):
            raise ConfigurationError(f"custom_metadata cannot shadow the SDK key {key!r}")
        if is_credential_metadata_key(key):
            raise ConfigurationError(f"custom_metadata cannot carry the credential key {key!r}")
        if len(raw_value) > _MAX_CUSTOM_METADATA_VALUE_LENGTH or any(
            not 0x20 <= ord(character) <= 0x7E for character in raw_value
        ):
            # The value is never echoed: a rejected header must not leak itself
            # into a log line or a traceback.
            raise ConfigurationError(f"custom_metadata value for {key!r} is invalid")
        validated[key] = raw_value
    return MappingProxyType(validated)


def _validated_middleware(values: Sequence[object]) -> tuple[object, ...]:
    middleware = tuple(values)
    if len(middleware) > MAX_MIDDLEWARE:
        raise ConfigurationError(f"middleware cannot exceed {MAX_MIDDLEWARE} interceptors")
    for entry in middleware:
        if not is_interceptor(entry):
            raise ConfigurationError(
                "middleware entries must implement intercept_unary_unary or intercept_unary_stream"
            )
    return middleware


def _validate_identity(label: str, value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 256:
        raise ConfigurationError(f"{label} must be between 1 and 256 characters")
    if any(character in normalized for character in "\r\n\x00"):
        raise ConfigurationError(f"{label} contains control characters")
    return normalized


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Configuration shared by synchronous and asynchronous SDK clients."""

    tenant_id: str
    project_id: str
    principal_id: str
    token_provider: SyncTokenProvider | AsyncTokenProvider | None = field(default=None, repr=False)
    environment: Environment = Environment.DEVELOPMENT
    endpoint: str | None = None
    default_timeout: float = 20.0
    poll_interval: float = 0.5
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    tls_server_name: str | None = None
    root_certificates: bytes | None = field(default=None, repr=False)
    user_agent: str = ""
    """``x-mindclade-sdk``. Empty means "derive it from the running platform"."""
    insecure_for_testing: bool = False
    audience: str | None = None
    custom_metadata: Mapping[str, str] = _NO_CUSTOM_METADATA
    """Caller metadata added to every request; never credential-bearing."""
    omit_platform_metadata: bool = False
    """Emit only the SDK name and version in ``x-mindclade-sdk``."""
    middleware: Sequence[object] = ()
    """gRPC client interceptors. Credential injection is not interceptable."""

    def __post_init__(self) -> None:
        try:
            environment = Environment(self.environment)
        except ValueError as error:
            raise ConfigurationError(f"unknown environment: {self.environment!r}") from error
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "tenant_id", _validate_identity("tenant_id", self.tenant_id))
        object.__setattr__(self, "project_id", _validate_identity("project_id", self.project_id))
        object.__setattr__(
            self, "principal_id", _validate_identity("principal_id", self.principal_id)
        )
        endpoint = self.endpoint or ENVIRONMENT_ENDPOINTS[environment]
        host, port = _validated_endpoint(endpoint)
        object.__setattr__(self, "endpoint", endpoint)
        audience = _canonical_https_origin(host, port) if self.audience is None else self.audience
        audience = _validate_audience(audience)
        object.__setattr__(self, "audience", audience)
        provider_audience = getattr(self.token_provider, "audience", None)
        if provider_audience is not None:
            if not isinstance(provider_audience, str):
                raise ConfigurationError("token-provider audience must be a string")
            if _validate_audience(provider_audience) != audience:
                raise ConfigurationError(
                    "token-provider audience does not match the client audience"
                )
        if not 0 < self.default_timeout <= 300:
            raise ConfigurationError("default_timeout must be in (0, 300] seconds")
        if not 0 < self.poll_interval <= 60:
            raise ConfigurationError("poll_interval must be in (0, 60] seconds")
        if not self.user_agent:
            object.__setattr__(
                self,
                "user_agent",
                platform_user_agent(omit_platform_metadata=self.omit_platform_metadata),
            )
        if not self.user_agent.strip() or re.search(r"[\r\n\x00]", self.user_agent):
            raise ConfigurationError("user_agent is empty or contains control characters")
        object.__setattr__(
            self, "custom_metadata", _validated_custom_metadata(self.custom_metadata)
        )
        object.__setattr__(self, "middleware", _validated_middleware(self.middleware))
        if self.tls_server_name is not None:
            server_name = self.tls_server_name.strip().lower()
            if not server_name or re.fullmatch(r"[a-z0-9.-]+", server_name) is None:
                raise ConfigurationError("tls_server_name must be a DNS name")
            object.__setattr__(self, "tls_server_name", server_name)
        if self.root_certificates is not None and not self.root_certificates:
            raise ConfigurationError("root_certificates cannot be empty")
        if self.insecure_for_testing:
            if environment is not Environment.LOCAL or not _is_loopback(host):
                raise ConfigurationError(
                    "insecure transport is restricted to the local loopback environment"
                )
            if self.token_provider is not None:
                raise ConfigurationError("credentials cannot be sent over insecure transport")
        elif self.token_provider is None:
            raise ConfigurationError("secure clients require a workload-identity token provider")

    @property
    def project_parent(self) -> str:
        tenant = (
            self.tenant_id if self.tenant_id.startswith("tenants/") else f"tenants/{self.tenant_id}"
        )
        if self.project_id.startswith("tenants/"):
            return self.project_id
        if self.project_id.startswith("projects/"):
            return f"{tenant}/{self.project_id}"
        return f"{tenant}/projects/{self.project_id}"

    @property
    def resolved_endpoint(self) -> str:
        assert self.endpoint is not None
        return self.endpoint
