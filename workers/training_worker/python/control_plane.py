"""Training-worker intake through the private SDK and immutable event contracts."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from pathlib import Path

from mindclade_internal_sdk import (
    ArtifactRef,
    AsyncClient,
    CallOptions,
    EventRejectedError,
    JobRequestedDelivery,
    MindcladeError,
    decode_job_requested_delivery,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_JOB_NAME = re.compile(r"jobs/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\Z")
_DEFAULT_ARTIFACT_LIMIT = 16 << 20


class AssignmentRejectedError(ValueError):
    """The immutable delivery does not satisfy the registered event contract."""


class AssignmentDeadlineError(TimeoutError):
    """The bounded worker intake deadline elapsed."""


@dataclass(frozen=True, slots=True)
class MaterializedAssignment:
    """Local execution inputs; this is deliberately not a wire or durable model."""

    event_id: str
    job_id: str
    configuration_path: Path
    input_path: Path | None


def decode_job_requested(
    serialized: bytes,
    *,
    tenant_id: str,
    project_id: str,
) -> JobRequestedDelivery:
    """Verify one exact-version deterministic event delivery before SDK I/O."""

    try:
        return decode_job_requested_delivery(
            serialized,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    except EventRejectedError as error:
        raise AssignmentRejectedError(str(error)) from error


class AssignmentMaterializer:
    """Resolve and verify worker input bytes exclusively through the private SDK."""

    def __init__(
        self,
        client: AsyncClient,
        *,
        rpc_timeout: float = 20.0,
        maximum_artifact_bytes: int = _DEFAULT_ARTIFACT_LIMIT,
    ) -> None:
        if rpc_timeout <= 0 or rpc_timeout > 300:
            raise ValueError("rpc_timeout must be in (0, 300] seconds")
        if maximum_artifact_bytes <= 0 or maximum_artifact_bytes > 1 << 30:
            raise ValueError("maximum_artifact_bytes must be in (0, 1 GiB]")
        self._client = client
        self._rpc_timeout = rpc_timeout
        self._maximum_artifact_bytes = maximum_artifact_bytes

    async def materialize(
        self,
        serialized_envelope: bytes,
        destination: Path,
        *,
        timeout: float = 60.0,
    ) -> MaterializedAssignment:
        if timeout <= 0 or timeout > 600:
            raise ValueError("worker intake timeout must be in (0, 600] seconds")
        decoded = decode_job_requested(
            serialized_envelope,
            tenant_id=self._client.config.tenant_id,
            project_id=self._client.config.project_id,
        )
        options = CallOptions(
            timeout=min(self._rpc_timeout, timeout),
            request_id=decoded.request_id,
            trace_id=decoded.trace_id,
        )
        try:
            async with asyncio.timeout(timeout):
                job = await self._client.jobs.get(decoded.job_id, options=options)
                if (
                    not job.HasField("configuration")
                    or job.configuration.digest != decoded.configuration_digest
                ):
                    raise AssignmentRejectedError(
                        "durable job configuration does not match its immutable event"
                    )
                root = destination.resolve() / _canonical_job_leaf(decoded.job_id)
                await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
                configuration_path = root / "configuration.artifact"
                await self._download(job.configuration, configuration_path, options)
                input_path: Path | None = None
                if job.HasField("input") and job.input.digest:
                    input_path = root / "input.artifact"
                    await self._download(job.input, input_path, options)
                return MaterializedAssignment(
                    event_id=decoded.event_id,
                    job_id=decoded.job_id,
                    configuration_path=configuration_path,
                    input_path=input_path,
                )
        except TimeoutError as error:
            raise AssignmentDeadlineError("training-worker intake deadline expired") from error

    async def _download(
        self,
        artifact: ArtifactRef,
        destination: Path,
        options: CallOptions,
    ) -> None:
        size_bytes = artifact.size_bytes
        digest = artifact.digest
        if (
            size_bytes < 0
            or size_bytes > self._maximum_artifact_bytes
            or _DIGEST.fullmatch(digest) is None
        ):
            raise AssignmentRejectedError("worker artifact exceeds the bounded intake policy")
        if destination.exists():
            existing_digest = await asyncio.to_thread(_file_digest, destination)
            if hmac.compare_digest(existing_digest, digest):
                return
            raise AssignmentRejectedError("existing worker artifact has a different digest")
        content = bytearray()
        try:
            async for chunk in self._client.artifacts.iter_download(artifact, options=options):
                if len(content) + len(chunk) > self._maximum_artifact_bytes:
                    raise AssignmentRejectedError("artifact stream exceeded the worker byte limit")
                content.extend(chunk)
        except MindcladeError:
            raise
        if len(content) != size_bytes:
            raise AssignmentRejectedError("artifact stream size changed after SDK verification")
        await asyncio.to_thread(_write_exclusive, destination, bytes(content))


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _canonical_job_leaf(job_id: str) -> str:
    match = _JOB_NAME.fullmatch(job_id)
    if match is None:
        raise AssignmentRejectedError("job identity is not a canonical resource name")
    return match.group(1)


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
