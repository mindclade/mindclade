"""Resolve and publish one artifact through the SDK's verified file helper."""

from __future__ import annotations

from pathlib import Path

from mindclade_internal_sdk import CallOptions, Client
from mindclade_internal_sdk.resources import ArtifactRef


def download_verified_artifact(
    client: Client,
    *,
    alias: str,
    destination: Path,
    parent: str | None = None,
    options: CallOptions | None = None,
) -> ArtifactRef:
    """Resolve an immutable alias and publish a verified, no-clobber file."""

    artifact = client.artifacts.resolve_alias(alias, parent=parent, options=options)
    client.artifacts.download_file(artifact, destination, options=options)
    return artifact
