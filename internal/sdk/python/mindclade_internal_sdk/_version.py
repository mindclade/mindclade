"""The single version source for this package.

Two consumers read this module and nothing else reads a version from anywhere
else: :mod:`mindclade_internal_sdk._platform`, which stamps the identity into
the ``x-mindclade-sdk`` request metadata, and ``pyproject.toml``, whose
``version`` field the packaging tests pin to :data:`__version__`.

The number is **not** a compatibility promise. This package is private and is
never published, so it carries no SemVer line: consumers pin a *source
revision* of this monorepo and build the facade from that revision's sources
together with that revision's generated contracts. ``CHANGELOG.md`` is keyed by
source revision for the same reason. The field exists because the packaging
tooling requires one and because a support report needs a stable name for the
build it came from.
"""

from __future__ import annotations

__version__ = "0.1.0"
"""The version stamped into ``x-mindclade-sdk`` and declared in ``pyproject.toml``."""

SDK_NAME = "mindclade-internal-python-sdk"
"""The product identity half of the SDK header, shared by all four languages' naming scheme."""

USER_AGENT = f"{SDK_NAME}/{__version__}"
"""The SDK identity with no platform detail attached."""

__all__ = ["SDK_NAME", "USER_AGENT", "__version__"]
