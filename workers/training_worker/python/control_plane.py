"""Training-worker intake through the private SDK and immutable event contracts."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mindclade_internal_sdk import (
    AccessToken,
    ArtifactRef,
    AsyncClient,
    AsyncGoogleWorkloadIdentityProvider,
    CallOptions,
    ConflictError,
    DeadlineExceededError,
    Environment,
    EventRejectedError,
    JobRequestedDelivery,
    config_from_env,
    decode_job_requested_delivery,
)

_JOB_NAME = re.compile(r"jobs/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\Z")
_DEFAULT_ARTIFACT_LIMIT = 16 << 20
_USER_AGENT = "mindclade-training-worker/0.1"


class _ConfigurationProbe:
    """Placeholder provider that exists only so the SDK can resolve configuration.

    ``config_from_env`` refuses to build a secure configuration without a token
    provider, yet the real workload-identity provider has to be bound to the
    very audience that same configuration resolves. This probe closes that
    ordering gap without the worker reading one environment variable itself,
    and it can never mint a credential.
    """

    async def get_token(self, *, timeout: float) -> AccessToken:
        del timeout
        raise RuntimeError("the training-worker configuration probe never mints a credential")


def client_options() -> dict[str, Any]:
    """Resolve this worker's ``from_env`` overrides without reading the environment.

    Every ``MINDCLADE_*`` variable is read by the SDK's own environment reader,
    which owns their names, defaults and failure messages. The worker adds only
    what no environment variable may ever supply: its user agent and the
    workload-identity provider bound to the audience the SDK resolved.
    """

    probe = config_from_env(token_provider=_ConfigurationProbe(), user_agent=_USER_AGENT)
    if probe.environment is Environment.LOCAL:
        # Loopback development: the SDK forbids credentials over insecure transport.
        return {"user_agent": _USER_AGENT, "insecure_for_testing": True}
    audience = probe.audience
    if audience is None:
        # ClientConfig derives the audience from the endpoint whenever it is not
        # supplied, so this is unreachable; the field stays optional for callers
        # that construct a configuration directly.
        raise RuntimeError("the SDK resolved a configuration without a workload-identity audience")
    return {
        "user_agent": _USER_AGENT,
        "audience": audience,
        "token_provider": AsyncGoogleWorkloadIdentityProvider(audience),
    }


class AssignmentRejectedError(ValueError):
    """The immutable delivery does not satisfy the registered event contract."""


class AssignmentDeadlineError(TimeoutError):
    """The bounded worker intake deadline elapsed.

    Both deadline surfaces end here: the SDK's own per-call
    :class:`~mindclade_internal_sdk.DeadlineExceededError` and the single
    worker budget that spans the whole multi-call intake.
    """


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
        # Per-call deadlines, retries, idempotency and correlation metadata are
        # the SDK's job; the worker states its per-call budget once and owns
        # only the single budget that spans this multi-call intake.
        options = CallOptions(
            timeout=self._rpc_timeout,
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
        except (DeadlineExceededError, TimeoutError) as error:
            raise AssignmentDeadlineError("training-worker intake deadline expired") from error

    async def _download(
        self,
        artifact: ArtifactRef,
        destination: Path,
        options: CallOptions,
    ) -> None:
        # Digest shape and stream integrity are verified by the SDK download
        # path. The only policy the SDK cannot know is this worker's intake
        # ceiling on how many bytes a single assignment may materialize.
        if artifact.size_bytes > self._maximum_artifact_bytes:
            raise AssignmentRejectedError("worker artifact exceeds the bounded intake policy")
        if await self._already_materialized(destination, artifact.digest):
            return
        try:
            # The SDK downloads, verifies and atomically publishes a create-only
            # mode-0600 file; it never overwrites an existing destination.
            await self._client.artifacts.download_file(artifact, destination, options=options)
        except ConflictError:
            # A concurrent delivery may have published this destination while
            # the download was in flight, which is idempotent exactly when the
            # bytes now on disk carry the same immutable digest. Any other
            # conflict stays an SDK error and is reported as one.
            if not await self._already_materialized(destination, artifact.digest):
                raise

    async def _already_materialized(self, destination: Path, digest: str) -> bool:
        """Report whether a verified local copy already satisfies this artifact."""

        if not destination.exists():
            return False
        existing_digest = await asyncio.to_thread(_file_digest, destination)
        if not hmac.compare_digest(existing_digest, digest):
            raise AssignmentRejectedError("existing worker artifact has a different digest")
        return True


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
