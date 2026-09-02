"""Resolve and atomically publish one digest-verified artifact download."""

from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
from pathlib import Path

from mindclade_internal_sdk import CallOptions, Client, ProtocolError
from mindclade_internal_sdk.resources import ArtifactRef


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def download_verified_artifact(
    client: Client,
    *,
    alias: str,
    destination: Path,
    parent: str | None = None,
    overwrite: bool = False,
    options: CallOptions | None = None,
) -> ArtifactRef:
    """Download to a sibling temporary file, verify it, then rename atomically."""

    target = destination.expanduser()
    target_parent = target.parent
    if not target_parent.is_dir():
        raise ValueError("artifact destination parent must already exist")
    if target.is_symlink():
        raise ValueError("artifact destination cannot be a symbolic link")
    if target.exists() and not overwrite:
        raise FileExistsError(target)

    artifact = client.artifacts.resolve_alias(alias, parent=parent, options=options)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target_parent,
        prefix=f".{target.name}.",
        suffix=".part",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w+b") as sink:
            client.artifacts.download(artifact, sink, options=options)
            sink.flush()
            os.fsync(sink.fileno())
        observed = _digest_file(temporary)
        if not hmac.compare_digest(observed, artifact.digest):
            raise ProtocolError(
                "downloaded artifact digest differs from its authoritative identity"
            )
        if target.exists() and not overwrite:
            raise FileExistsError(target)
        temporary.replace(target)
        _fsync_directory(target_parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return artifact
