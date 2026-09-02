"""Structured, bounded platform facts stamped into ``x-mindclade-sdk``.

The header is a support signal, not telemetry: it names the SDK, its version,
and the runtime it is executing on so a control-plane operator can correlate a
report with a build. Every component is drawn from a closed allowlist and
matched against a conservative token pattern, so an exotic platform string can
never widen the header, inject a separator, or smuggle host detail off the
machine. Callers who consider even that too much set
``ClientConfig(omit_platform_metadata=True)`` and emit the bare name/version.
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass

SDK_LANGUAGE = "python"
SDK_NAME = "mindclade-internal-python-sdk"
SDK_VERSION = "0.1"

# A gRPC metadata value is cheap but not free, and an unbounded header is a
# fingerprint. 256 characters is the same ceiling the raw-response allowlist
# applies to values it will surface.
MAX_USER_AGENT_LENGTH = 256

UNKNOWN = "unknown"

_TOKEN_PATTERN = re.compile(r"\A[a-z0-9._+-]{1,32}\Z")

# Closed allowlists. Anything outside them reports ``unknown`` rather than
# echoing whatever the host happened to say about itself.
_OPERATING_SYSTEMS = frozenset({"linux", "darwin", "windows"})
_ARCHITECTURES = frozenset({"x86_64", "amd64", "aarch64", "arm64"})
_RUNTIMES = frozenset({"cpython", "pypy", "graalpy", "ironpython", "jython"})


def _token(value: str, allowed: frozenset[str] | None = None) -> str:
    normalized = value.strip().lower()
    if _TOKEN_PATTERN.match(normalized) is None:
        return UNKNOWN
    if allowed is not None and normalized not in allowed:
        return UNKNOWN
    return normalized


def base_user_agent() -> str:
    """Return the SDK identity with no platform detail attached."""

    return f"{SDK_NAME}/{SDK_VERSION}"


@dataclass(frozen=True, slots=True)
class PlatformMetadata:
    """The six structured fields ``x-mindclade-sdk`` may carry."""

    language: str = SDK_LANGUAGE
    version: str = SDK_VERSION
    os: str = UNKNOWN
    arch: str = UNKNOWN
    runtime: str = UNKNOWN
    runtime_version: str = UNKNOWN

    @classmethod
    def detect(cls) -> PlatformMetadata:
        """Read the host platform through the allowlists above."""

        return cls(
            language=SDK_LANGUAGE,
            version=_token(SDK_VERSION),
            os=_token(platform.system(), _OPERATING_SYSTEMS),
            arch=_token(platform.machine(), _ARCHITECTURES),
            runtime=_token(platform.python_implementation(), _RUNTIMES),
            runtime_version=_token(platform.python_version()),
        )

    def encode(self) -> str:
        """Render the header value, falling back to the bare identity if oversized."""

        value = " ".join(
            (
                f"{SDK_NAME}/{self.version}",
                f"lang={self.language}",
                f"os={self.os}",
                f"arch={self.arch}",
                f"runtime={self.runtime}",
                f"runtime_version={self.runtime_version}",
            )
        )
        if len(value) > MAX_USER_AGENT_LENGTH:
            return base_user_agent()
        return value


def platform_user_agent(*, omit_platform_metadata: bool = False) -> str:
    """Return the default ``x-mindclade-sdk`` value for this process."""

    if omit_platform_metadata:
        return base_user_agent()
    return PlatformMetadata.detect().encode()
