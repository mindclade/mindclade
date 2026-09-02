"""The one gRPC metadata allowlist and credential denylist for this SDK.

Both lists are normative and identical across the Go, Python, Rust, and
TypeScript internal SDKs. The allowlist decides what a raw response may expose;
the denylist decides what caller-supplied metadata and interceptors may never
carry. Nothing credential-bearing may appear in either direction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

# Response metadata a raw response may expose. Keys not listed here are dropped
# rather than sanitized, so a new server header can never leak by default.
SAFE_RESPONSE_METADATA_KEYS = frozenset(
    {
        "x-request-id",
        "x-trace-id",
        "x-mindclade-sdk",
        "x-mindclade-retry-count",
        "x-mindclade-timeout-ms",
        "x-mindclade-should-retry",
        "retry-after-ms",
        "content-type",
        "grpc-status",
        "grpc-message",
        "date",
    }
)

# Exact credential-bearing metadata keys. These are never read by callers,
# never accepted from callers, and never observable by an interceptor.
CREDENTIAL_METADATA_KEYS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-mindclade-lease-token",
        "cookie",
        "set-cookie",
    }
)

# Substrings that mark a key as credential-bearing even when it is not listed
# above. The patterns are deliberately broad: a false positive costs a rejected
# custom header, a false negative costs a leaked secret.
CREDENTIAL_KEY_PATTERNS = (
    "token",
    "secret",
    "key",
    "credential",
    "password",
    "auth",
    "cookie",
)

_MAX_METADATA_VALUE_LENGTH = 256
_UNSAFE_VALUE_CHARACTERS = ("\r", "\n", "\x00")


def is_credential_metadata_key(key: str) -> bool:
    """Return whether a metadata key may carry a credential."""

    normalized = key.strip().lower()
    if not normalized:
        return False
    if normalized in CREDENTIAL_METADATA_KEYS:
        return True
    return any(pattern in normalized for pattern in CREDENTIAL_KEY_PATTERNS)


def _decoded(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="ignore")
    if isinstance(value, str):
        return value
    return None


def safe_metadata(metadata: Iterable[tuple[str, str | bytes]]) -> Mapping[str, str]:
    """Project response metadata onto the allowlist, dropping everything else.

    Allowlisting runs first and the credential denylist runs second, so a
    future edit to :data:`SAFE_RESPONSE_METADATA_KEYS` still cannot expose a
    credential. Binary (``-bin``) keys, oversized values, and values carrying
    CR, LF, or NUL are dropped rather than truncated.
    """

    safe: dict[str, str] = {}
    for raw_key, raw_value in metadata:
        key = str(raw_key).strip().lower()
        if key not in SAFE_RESPONSE_METADATA_KEYS or key.endswith("-bin"):
            continue
        if is_credential_metadata_key(key):
            continue
        value = _decoded(raw_value)
        if value is None or len(value) > _MAX_METADATA_VALUE_LENGTH:
            continue
        if any(character in value for character in _UNSAFE_VALUE_CHARACTERS):
            continue
        safe.setdefault(key, value)
    return MappingProxyType(safe)
