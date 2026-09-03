"""Artifact catalog and transfer conveniences over generated internal RPCs."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import tempfile
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Protocol, cast

import grpc
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_commands_pb2, artifact_reference_pb2
from mindclade.common.v1 import resource_reference_pb2
from mindclade.internal.artifact.v1 import artifact_service_pb2
from mindclade.job.v1 import operation_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._validation import artifact_ref, required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import ConflictError, NotFoundError, ProtocolError
from .transport import (
    ABORT_ARTIFACT_UPLOAD,
    ACQUIRE_ARTIFACT_LEASE,
    BEGIN_ARTIFACT_UPLOAD,
    COMMIT_ARTIFACT,
    DOWNLOAD_ARTIFACT,
    FINALIZE_ARTIFACT_UPLOAD,
    GET_ARTIFACT,
    GET_ARTIFACT_UPLOAD,
    LIST_ARTIFACTS,
    QUARANTINE_ARTIFACT,
    QUARANTINE_ARTIFACT_UPLOAD,
    RELEASE_ARTIFACT_LEASE,
    RESOLVE_ARTIFACT_ALIAS,
    UPLOAD_ARTIFACT_CHUNK,
)

_CANONICAL_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_UPLOAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DEFAULT_CHUNK_BYTES = 1 << 20
_MAX_CHUNK_BYTES = 4 << 20
_DEFAULT_SESSION_TTL = timedelta(hours=2)
_MAX_SESSION_TTL = timedelta(hours=24)
_DEFAULT_RECEIPT_TTL = timedelta(hours=24)
_MAX_RECEIPT_TTL = timedelta(days=7)
_MAX_LEASE_TTL = timedelta(days=30)
_MAX_ARTIFACT_PAGE_SIZE = 100
_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")


class BinaryReader(Protocol):
    """The bounded portion of a binary file API required by upload."""

    def read(self, size: int | None = -1, /) -> bytes: ...


class BinaryWriter(Protocol):
    """The bounded portion of a binary file API required by download."""

    def write(self, data: bytes, /) -> int: ...


class _Digest(Protocol):
    def update(self, data: bytes, /) -> None: ...


def _atomic_destination(destination: str | os.PathLike[str]) -> tuple[Path, Path]:
    raw = os.fspath(destination)
    if not raw or "\x00" in raw:
        raise ValueError("artifact destination must be a non-empty text path")
    if raw.endswith(os.sep) or (os.altsep is not None and raw.endswith(os.altsep)):
        raise ValueError("artifact destination must name a file")
    target = Path(raw).absolute()
    return target, target.parent


def _new_staging_file(directory: Path) -> tuple[BinaryIO, Path]:
    descriptor, path = tempfile.mkstemp(prefix=".mindclade-download-", dir=directory)
    return os.fdopen(descriptor, "wb"), Path(path)


def _sync_file(destination: BinaryIO) -> None:
    destination.flush()
    os.fsync(destination.fileno())


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_staging_file(staging: Path, destination: Path, directory: Path) -> None:
    # A same-directory hard link is an atomic, no-clobber publication. Keep the
    # staging name until the destination exists so failure cleanup is possible.
    # Successful link creation is the commit point: after it, cleanup and
    # directory-sync failures are best effort so this helper never reports a
    # failed download while leaving a valid destination behind.
    try:
        os.link(staging, destination)
    except FileExistsError as error:
        raise ConflictError(
            "artifact destination already exists",
            status=grpc.StatusCode.ALREADY_EXISTS,
        ) from error
    with suppress(OSError):
        _sync_directory(directory)
    with suppress(OSError):
        staging.unlink()
    with suppress(OSError):
        _sync_directory(directory)


async def _run_file_operation[**P, R](
    operation: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> R:
    """Finish an in-flight filesystem operation before cancellation cleanup."""

    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A thread cannot be cancelled safely. Waiting prevents cleanup from
        # racing a write that still owns the staging file.
        with suppress(BaseException):
            await task
        raise


async def _commit_staging_file(staging: Path, destination: Path, directory: Path) -> None:
    """Make publication the cancellation linearization point.

    Cancellation before this helper leaves no destination. Once publication
    begins, the filesystem result wins so callers never observe cancellation
    for a file that was actually committed.
    """

    task = asyncio.create_task(
        asyncio.to_thread(_publish_staging_file, staging, destination, directory)
    )
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task


type _MutationRequest = (
    artifact_service_pb2.QuarantineArtifactRequest
    | artifact_service_pb2.AcquireArtifactLeaseRequest
    | artifact_service_pb2.ReleaseArtifactLeaseRequest
    | artifact_service_pb2.BeginArtifactUploadRequest
    | artifact_service_pb2.UploadArtifactChunkRequest
    | artifact_service_pb2.FinalizeArtifactUploadRequest
    | artifact_service_pb2.AbortArtifactUploadRequest
    | artifact_service_pb2.QuarantineArtifactUploadRequest
)


def _artifact_name_digest(parent: str, name: str) -> str:
    prefix = f"{parent}/artifacts/"
    if not name.startswith(prefix):
        raise ValueError("artifact name must be in the configured project")
    digest = name.removeprefix(prefix)
    if _CANONICAL_DIGEST.fullmatch(digest) is None:
        raise ValueError("artifact name must end in a canonical sha256 digest")
    return digest


def _validate_lease(
    *,
    tenant_id: str,
    project_id: str,
    parent: str,
    lease: resource_reference_pb2.ResourceRef,
) -> resource_reference_pb2.ResourceRef:
    result = _clone(lease, resource_reference_pb2.ResourceRef)
    expected_name = f"{parent}/artifactLeases/{result.resource_id}"
    if (
        result.resource_type != "artifact_lease"
        or not result.resource_id
        or result.tenant_id != tenant_id
        or result.project_id != project_id
        or result.name != expected_name
        or result.resource_version <= 0
        or not result.etag
    ):
        raise ProtocolError(
            "artifact lease resource is invalid or outside the configured project",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return result


def _operation(
    response: Message,
    *,
    label: str,
    tenant_id: str,
    project_id: str,
) -> operation_pb2.Operation:
    value = required_response_message(response, "operation", operation_pb2.Operation, label=label)
    required_text("operation id", value.operation_id)
    if (
        value.tenant_id != tenant_id
        or value.project_id != project_id
        or value.state == operation_pb2.OPERATION_STATE_UNSPECIFIED
    ):
        raise ProtocolError(
            f"{label} returned invalid or cross-project operation state",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return value


def _clone[MessageT: Message](value: MessageT, expected: type[MessageT]) -> MessageT:
    if not isinstance(value, expected):
        raise TypeError(f"value must be the generated {expected.__name__}")
    result = expected()
    result.CopyFrom(value)
    return result


def _timestamp_after(lifetime: timedelta) -> Timestamp:
    value = Timestamp()
    value.FromDatetime(datetime.now(UTC) + lifetime)
    return value


def _receipt_expiry(
    upload: artifact_service_pb2.ArtifactUploadSession, lifetime: timedelta
) -> Timestamp:
    base = datetime.now(UTC)
    if upload.HasField("create_time") and upload.create_time.seconds > 0:
        base = upload.create_time.ToDatetime(tzinfo=UTC)
    value = Timestamp()
    value.FromDatetime(base + lifetime)
    return value


def _bounded_lifetime(label: str, value: timedelta, maximum: timedelta) -> timedelta:
    if value <= timedelta(0) or value > maximum:
        raise ValueError(f"{label} must be positive and no greater than {maximum}")
    return value


def _upload_id(value: str | None) -> str:
    result = value.strip() if value is not None else uuid.uuid4().hex
    if _UPLOAD_ID.fullmatch(result) is None:
        raise ValueError("artifact upload id is invalid")
    return result


def _chunk_size(value: int) -> int:
    result = value or _DEFAULT_CHUNK_BYTES
    if not 1 <= result <= _MAX_CHUNK_BYTES:
        raise ValueError("artifact chunk size must be between 1 byte and 4 MiB")
    return result


def _phase_options(options: CallOptions | None, identity: str, phase: str) -> CallOptions:
    base = options or CallOptions()
    seed = f"{base.idempotency_key or identity}\x00{phase}".encode()
    key = "artifact-transfer:" + hashlib.sha256(seed).hexdigest()
    return CallOptions(
        timeout=base.timeout,
        request_id=base.request_id,
        trace_id=base.trace_id,
        idempotency_key=key,
    )


def _prepared(
    invoker: SyncInvoker | AsyncInvoker,
    options: CallOptions | None,
    identity: str,
    phase: str,
) -> PreparedCall:
    return prepare_call(
        _phase_options(options, identity, phase),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )


def _attach_context(
    request: _MutationRequest,
    invoker: SyncInvoker | AsyncInvoker,
    call: PreparedCall,
) -> None:
    request.ClearField("context")
    context = command_context(
        invoker.config,
        call,
        request_digest=canonical_digest(request),
    )
    request.context.CopyFrom(context)


def _validate_transfer_artifact(
    value: artifact_reference_pb2.ArtifactRef,
) -> artifact_reference_pb2.ArtifactRef:
    result = _clone(value, artifact_reference_pb2.ArtifactRef)
    artifact_ref("artifact", result)
    if result.uri:
        raise ValueError("artifact.uri is private transport metadata and must be empty")
    if result.integrity_digest and not hmac.compare_digest(result.integrity_digest, result.digest):
        raise ValueError("artifact.integrity_digest must equal artifact.digest when present")
    if bool(result.schema_id) is not bool(result.schema_version):
        raise ValueError("artifact schema id and version must be supplied together")
    return result


def _response_artifact(
    value: artifact_reference_pb2.ArtifactRef,
    *,
    label: str,
) -> artifact_reference_pb2.ArtifactRef:
    try:
        return _validate_transfer_artifact(value)
    except (TypeError, ValueError) as error:
        raise ProtocolError(
            f"{label} returned invalid immutable metadata",
            status=grpc.StatusCode.DATA_LOSS,
        ) from error


def _validate_upload(
    upload: artifact_service_pb2.ArtifactUploadSession,
    *,
    expected_artifact: artifact_reference_pb2.ArtifactRef | None = None,
) -> artifact_service_pb2.ArtifactUploadSession:
    required_text("artifact upload name", upload.name)
    artifact = required_response_message(
        upload,
        "artifact",
        artifact_reference_pb2.ArtifactRef,
        label="artifact upload",
    )
    _validate_transfer_artifact(artifact)
    if expected_artifact is not None and artifact != expected_artifact:
        raise ProtocolError(
            "artifact upload returned a different content identity",
            status=grpc.StatusCode.DATA_LOSS,
        )
    if upload.state == artifact_service_pb2.ARTIFACT_UPLOAD_STATE_UNSPECIFIED:
        raise ProtocolError(
            "artifact upload returned an unspecified state",
            status=grpc.StatusCode.DATA_LOSS,
        )
    if upload.committed_offset < 0 or upload.committed_offset > artifact.size_bytes:
        raise ProtocolError(
            "artifact upload returned an invalid committed offset",
            status=grpc.StatusCode.DATA_LOSS,
        )
    if upload.next_chunk_index < 0 or upload.revision <= 0:
        raise ProtocolError(
            "artifact upload returned invalid progress metadata",
            status=grpc.StatusCode.DATA_LOSS,
        )
    required_text("artifact upload etag", upload.etag)
    return upload


def _upload_from_response(
    response: Message,
    *,
    label: str,
    expected_artifact: artifact_reference_pb2.ArtifactRef | None = None,
) -> artifact_service_pb2.ArtifactUploadSession:
    upload = required_response_message(
        response,
        "upload",
        artifact_service_pb2.ArtifactUploadSession,
        label=label,
    )
    return _validate_upload(upload, expected_artifact=expected_artifact)


def _validate_receipt(
    receipt: artifact_service_pb2.ArtifactStagingReceipt,
    *,
    expected_artifact: artifact_reference_pb2.ArtifactRef | None = None,
) -> artifact_service_pb2.ArtifactStagingReceipt:
    result = _clone(receipt, artifact_service_pb2.ArtifactStagingReceipt)
    if _CANONICAL_DIGEST.fullmatch(result.receipt_digest) is None:
        raise ProtocolError(
            "artifact staging receipt digest is invalid",
            status=grpc.StatusCode.DATA_LOSS,
        )
    artifact = required_response_message(
        result,
        "artifact",
        artifact_reference_pb2.ArtifactRef,
        label="artifact staging receipt",
    )
    _validate_transfer_artifact(artifact)
    if expected_artifact is not None and artifact != expected_artifact:
        raise ProtocolError(
            "artifact staging receipt returned a different content identity",
            status=grpc.StatusCode.DATA_LOSS,
        )
    if not result.HasField("verified_at") or not result.HasField("expire_time"):
        raise ProtocolError(
            "artifact staging receipt omitted its validity interval",
            status=grpc.StatusCode.DATA_LOSS,
        )
    if result.expire_time.ToDatetime(tzinfo=UTC) <= result.verified_at.ToDatetime(tzinfo=UTC):
        raise ProtocolError(
            "artifact staging receipt has an invalid validity interval",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return result


def _read_exact(source: BinaryReader, size: int) -> bytes:
    parts: list[bytes] = []
    remaining = size
    while remaining:
        value = source.read(remaining)
        if not value:
            break
        if len(value) > remaining:
            raise ValueError("artifact upload source returned more bytes than requested")
        parts.append(value)
        remaining -= len(value)
    return b"".join(parts)


def _discard_exact(source: BinaryReader, size: int, digest: _Digest) -> None:
    remaining = size
    while remaining:
        value = _read_exact(source, min(remaining, _DEFAULT_CHUNK_BYTES))
        if not value:
            raise ValueError("artifact upload source is shorter than its durable resume offset")
        digest.update(value)
        remaining -= len(value)


class _AsyncSourceReader:
    def __init__(self, source: AsyncIterable[bytes]) -> None:
        self._source = source.__aiter__()
        self._buffer = bytearray()
        self._done = False

    async def read(self, size: int) -> bytes:
        while len(self._buffer) < size and not self._done:
            try:
                value = await anext(self._source)
            except StopAsyncIteration:
                self._done = True
                break
            if len(value) > _MAX_CHUNK_BYTES:
                raise ValueError("async artifact upload source chunks cannot exceed 4 MiB")
            self._buffer.extend(value)
        count = min(size, len(self._buffer))
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result


async def _async_discard_exact(source: _AsyncSourceReader, size: int, digest: _Digest) -> None:
    remaining = size
    while remaining:
        value = await source.read(min(remaining, _DEFAULT_CHUNK_BYTES))
        if not value:
            raise ValueError("artifact upload source is shorter than its durable resume offset")
        digest.update(value)
        remaining -= len(value)


def _verify_download_response(
    response: artifact_service_pb2.DownloadArtifactResponse,
    artifact: artifact_reference_pb2.ArtifactRef,
    offset: int,
) -> bytes:
    streamed_artifact = required_response_message(
        response,
        "artifact",
        artifact_reference_pb2.ArtifactRef,
        label="artifact download",
    )
    if streamed_artifact != artifact or response.offset != offset:
        raise ProtocolError(
            "artifact download stream changed identity or offset",
            status=grpc.StatusCode.DATA_LOSS,
        )
    digest = "sha256:" + hashlib.sha256(response.data).hexdigest()
    if not hmac.compare_digest(response.chunk_digest, digest):
        raise ProtocolError(
            "artifact download chunk digest verification failed",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return bytes(response.data)


class Artifacts:
    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def get(
        self,
        request: artifact_service_pb2.GetArtifactRequest,
        *,
        options: CallOptions | None = None,
    ) -> artifact_reference_pb2.ArtifactRef:
        value = _clone(request, artifact_service_pb2.GetArtifactRequest)
        if bool(value.name) == bool(value.digest):
            raise ValueError("artifact get requires exactly one canonical name or digest")
        expected = (
            _artifact_name_digest(self._invoker.config.project_parent, value.name)
            if value.name
            else value.digest
        )
        if _CANONICAL_DIGEST.fullmatch(expected) is None:
            raise ValueError("artifact digest must be canonical sha256")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            artifact_service_pb2.GetArtifactResponse,
            self._invoker.unary(GET_ARTIFACT, value, call=call, retry_safe=True),
        )
        result = required_response_message(
            response,
            "artifact",
            artifact_reference_pb2.ArtifactRef,
            label="artifact get",
        )
        result = _response_artifact(result, label="GetArtifact")
        if not hmac.compare_digest(result.digest, expected):
            raise ProtocolError(
                "GetArtifact returned a different immutable identity",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return result

    def list(
        self,
        request: artifact_service_pb2.ListArtifactsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ListArtifactsResponse:
        value = (
            artifact_service_pb2.ListArtifactsRequest()
            if request is None
            else _clone(request, artifact_service_pb2.ListArtifactsRequest)
        )
        parent = self._invoker.config.project_parent
        if value.parent and value.parent != parent:
            raise ValueError("artifact list parent must match the configured project")
        if value.page.page_size > _MAX_ARTIFACT_PAGE_SIZE:
            raise ValueError("artifact page size cannot exceed 100")
        value.parent = parent
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        raw = self._invoker.unary(LIST_ARTIFACTS, value, call=call, retry_safe=True)
        if not isinstance(raw, artifact_service_pb2.ListArtifactsResponse):
            raise ProtocolError(
                "ListArtifacts response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )
        result = _clone(raw, artifact_service_pb2.ListArtifactsResponse)
        for item in result.artifacts:
            _response_artifact(item, label="ListArtifacts")
        return result

    def quarantine(
        self,
        request: artifact_service_pb2.QuarantineArtifactRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = _clone(request, artifact_service_pb2.QuarantineArtifactRequest)
        artifact = _validate_transfer_artifact(value.artifact)
        if _REASON_CODE.fullmatch(value.reason_code) is None or len(value.evidence) > 100:
            raise ValueError("artifact quarantine reason or evidence count is invalid")
        for evidence in value.evidence:
            if (
                _CANONICAL_DIGEST.fullmatch(evidence.digest) is None
                or not hmac.compare_digest(evidence.subject_digest, artifact.digest)
                or not evidence.evidence_kind
                or len(evidence.evidence_kind) > 128
                or (
                    evidence.policy_digest
                    and _CANONICAL_DIGEST.fullmatch(evidence.policy_digest) is None
                )
            ):
                raise ValueError("artifact quarantine evidence is invalid")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        _attach_context(value, self._invoker, call)
        response = self._invoker.unary(QUARANTINE_ARTIFACT, value, call=call, retry_safe=True)
        return _operation(
            response,
            label="artifact quarantine",
            tenant_id=self._invoker.config.tenant_id,
            project_id=self._invoker.config.project_id,
        )

    def acquire_lease(
        self,
        request: artifact_service_pb2.AcquireArtifactLeaseRequest,
        *,
        options: CallOptions | None = None,
    ) -> resource_reference_pb2.ResourceRef:
        value = _clone(request, artifact_service_pb2.AcquireArtifactLeaseRequest)
        _validate_transfer_artifact(value.artifact)
        if not value.HasField("expire_time"):
            raise ValueError("artifact lease expiration is required")
        now = datetime.now(UTC)
        expiration = value.expire_time.ToDatetime(tzinfo=UTC)
        if expiration <= now or expiration > now + _MAX_LEASE_TTL:
            raise ValueError("artifact lease expiration must be within 30 days")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        _attach_context(value, self._invoker, call)
        response = self._invoker.unary(ACQUIRE_ARTIFACT_LEASE, value, call=call, retry_safe=True)
        lease = required_response_message(
            response,
            "lease",
            resource_reference_pb2.ResourceRef,
            label="artifact lease acquisition",
        )
        return _validate_lease(
            tenant_id=self._invoker.config.tenant_id,
            project_id=self._invoker.config.project_id,
            parent=self._invoker.config.project_parent,
            lease=lease,
        )

    def release_lease(
        self,
        request: artifact_service_pb2.ReleaseArtifactLeaseRequest,
        *,
        options: CallOptions | None = None,
    ) -> None:
        value = _clone(request, artifact_service_pb2.ReleaseArtifactLeaseRequest)
        try:
            lease = _validate_lease(
                tenant_id=self._invoker.config.tenant_id,
                project_id=self._invoker.config.project_id,
                parent=self._invoker.config.project_parent,
                lease=value.lease,
            )
        except ProtocolError as error:
            raise ValueError("artifact lease release resource is invalid") from error
        required_text("artifact lease etag", value.etag, maximum=256)
        if lease.etag and not hmac.compare_digest(lease.etag, value.etag):
            raise ValueError("artifact lease and release ETags differ")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        _attach_context(value, self._invoker, call)
        response = self._invoker.unary(RELEASE_ARTIFACT_LEASE, value, call=call, retry_safe=True)
        if not isinstance(response, artifact_service_pb2.ReleaseArtifactLeaseResponse):
            raise ProtocolError(
                "ReleaseArtifactLease response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )

    def resolve_alias(
        self,
        alias: str,
        *,
        parent: str | None = None,
        options: CallOptions | None = None,
    ) -> artifact_reference_pb2.ArtifactRef:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            artifact_service_pb2.ResolveArtifactAliasResponse,
            self._invoker.unary(
                RESOLVE_ARTIFACT_ALIAS,
                artifact_service_pb2.ResolveArtifactAliasRequest(
                    parent=required_text(
                        "artifact parent", parent or self._invoker.config.project_parent
                    ),
                    alias=required_text("artifact alias", alias, maximum=256),
                ),
                call=call,
                retry_safe=True,
            ),
        )
        result = required_response_message(
            response,
            "artifact",
            artifact_reference_pb2.ArtifactRef,
            label="artifact resolution",
        )
        artifact_ref("artifact", result)
        return result

    def get_upload(
        self,
        name: str,
        *,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = self._invoker.unary(
            GET_ARTIFACT_UPLOAD,
            artifact_service_pb2.GetArtifactUploadRequest(
                name=required_text("artifact upload name", name)
            ),
            call=call,
            retry_safe=True,
        )
        return _upload_from_response(response, label="artifact upload status")

    def upload(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        source: BinaryReader,
        *,
        upload_id: str | None = None,
        chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        session_ttl: timedelta = _DEFAULT_SESSION_TTL,
        receipt_ttl: timedelta = _DEFAULT_RECEIPT_TTL,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactStagingReceipt:
        expected = _validate_transfer_artifact(artifact)
        identity = _upload_id(upload_id)
        chunk_bytes = _chunk_size(chunk_bytes)
        session_ttl = _bounded_lifetime(
            "artifact upload session lifetime", session_ttl, _MAX_SESSION_TTL
        )
        receipt_ttl = _bounded_lifetime(
            "artifact staging receipt lifetime", receipt_ttl, _MAX_RECEIPT_TTL
        )
        upload_name = f"{self._invoker.config.project_parent}/artifactUploads/{identity}"
        upload: artifact_service_pb2.ArtifactUploadSession | None = None
        if upload_id is not None:
            with suppress(NotFoundError):
                upload = self.get_upload(upload_name, options=options)
        if upload is None:
            begin_call = _prepared(self._invoker, options, identity, "begin")
            begin = artifact_service_pb2.BeginArtifactUploadRequest(
                parent=self._invoker.config.project_parent,
                artifact=expected,
                upload_id=identity,
                expire_time=_timestamp_after(session_ttl),
            )
            _attach_context(begin, self._invoker, begin_call)
            try:
                upload = _upload_from_response(
                    self._invoker.unary(
                        BEGIN_ARTIFACT_UPLOAD,
                        begin,
                        call=begin_call,
                        retry_safe=True,
                    ),
                    label="artifact upload begin",
                    expected_artifact=expected,
                )
            except ConflictError:
                upload = self.get_upload(upload_name, options=options)
        upload = _validate_upload(upload, expected_artifact=expected)
        if upload.state == artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED:
            receipt = required_response_message(
                upload,
                "staging_receipt",
                artifact_service_pb2.ArtifactStagingReceipt,
                label="finalized artifact upload",
            )
            return _validate_receipt(receipt, expected_artifact=expected)
        if upload.state != artifact_service_pb2.ARTIFACT_UPLOAD_STATE_OPEN:
            raise ValueError("artifact upload session cannot be resumed")
        full_digest = hashlib.sha256()
        _discard_exact(source, upload.committed_offset, full_digest)
        offset = upload.committed_offset
        while offset < expected.size_bytes:
            size = min(chunk_bytes, expected.size_bytes - offset)
            data = _read_exact(source, size)
            if len(data) != size:
                raise ValueError("artifact upload source ended before its declared size")
            full_digest.update(data)
            chunk_digest = "sha256:" + hashlib.sha256(data).hexdigest()
            phase = f"chunk:{upload.next_chunk_index}:{chunk_digest}"
            chunk_call = _prepared(self._invoker, options, identity, phase)
            request = artifact_service_pb2.UploadArtifactChunkRequest(
                name=upload.name,
                chunk_index=upload.next_chunk_index,
                offset=offset,
                data=data,
                chunk_digest=chunk_digest,
                etag=upload.etag,
            )
            _attach_context(request, self._invoker, chunk_call)
            expected_index = upload.next_chunk_index + 1
            expected_offset = offset + len(data)
            upload = _upload_from_response(
                self._invoker.unary(
                    UPLOAD_ARTIFACT_CHUNK,
                    request,
                    call=chunk_call,
                    retry_safe=True,
                ),
                label="artifact chunk upload",
                expected_artifact=expected,
            )
            if (
                upload.committed_offset != expected_offset
                or upload.next_chunk_index != expected_index
                or upload.state != artifact_service_pb2.ARTIFACT_UPLOAD_STATE_OPEN
            ):
                raise ProtocolError(
                    "artifact upload progress did not advance contiguously",
                    status=grpc.StatusCode.DATA_LOSS,
                )
            offset = upload.committed_offset
        extra = source.read(1)
        if extra:
            raise ValueError("artifact upload source exceeds its declared size")
        if not hmac.compare_digest("sha256:" + full_digest.hexdigest(), expected.digest):
            raise ValueError("artifact upload source digest differs from ArtifactRef")
        finalize_call = _prepared(self._invoker, options, identity, "finalize")
        finalize = artifact_service_pb2.FinalizeArtifactUploadRequest(
            name=upload.name,
            etag=upload.etag,
            receipt_expire_time=_receipt_expiry(upload, receipt_ttl),
        )
        _attach_context(finalize, self._invoker, finalize_call)
        response = cast(
            artifact_service_pb2.FinalizeArtifactUploadResponse,
            self._invoker.unary(
                FINALIZE_ARTIFACT_UPLOAD,
                finalize,
                call=finalize_call,
                retry_safe=True,
            ),
        )
        finalized = _upload_from_response(
            response,
            label="artifact upload finalize",
            expected_artifact=expected,
        )
        if finalized.state != artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED:
            raise ProtocolError(
                "artifact finalize did not return a finalized session",
                status=grpc.StatusCode.DATA_LOSS,
            )
        receipt = required_response_message(
            response,
            "staging_receipt",
            artifact_service_pb2.ArtifactStagingReceipt,
            label="artifact upload finalize",
        )
        return _validate_receipt(receipt, expected_artifact=expected)

    def abort_upload(
        self,
        name: str,
        etag: str,
        *,
        reason_code: str,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        return self._transition_upload(
            ABORT_ARTIFACT_UPLOAD,
            artifact_service_pb2.AbortArtifactUploadRequest,
            name,
            etag,
            reason_code,
            artifact_service_pb2.ARTIFACT_UPLOAD_STATE_ABORTED,
            options,
        )

    def quarantine_upload(
        self,
        name: str,
        etag: str,
        *,
        reason_code: str,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        return self._transition_upload(
            QUARANTINE_ARTIFACT_UPLOAD,
            artifact_service_pb2.QuarantineArtifactUploadRequest,
            name,
            etag,
            reason_code,
            artifact_service_pb2.ARTIFACT_UPLOAD_STATE_QUARANTINED,
            options,
        )

    def _transition_upload(
        self,
        method: str,
        request_type: type[
            artifact_service_pb2.AbortArtifactUploadRequest
            | artifact_service_pb2.QuarantineArtifactUploadRequest
        ],
        name: str,
        etag: str,
        reason_code: str,
        expected_state: int,
        options: CallOptions | None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        upload_name = required_text("artifact upload name", name)
        transition = method.rsplit("/", 1)[-1]
        call = _prepared(self._invoker, options, upload_name, transition)
        request = request_type(
            name=upload_name,
            etag=required_text("artifact upload etag", etag),
            reason_code=required_text("artifact upload reason code", reason_code, maximum=128),
        )
        _attach_context(request, self._invoker, call)
        upload = _upload_from_response(
            self._invoker.unary(method, request, call=call, retry_safe=True),
            label="artifact upload transition",
        )
        if upload.state != expected_state:
            raise ProtocolError(
                "artifact upload transition returned an unexpected state",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return upload

    def commit(
        self,
        receipt: artifact_service_pb2.ArtifactStagingReceipt,
        *,
        options: CallOptions | None = None,
    ) -> artifact_reference_pb2.ArtifactRef:
        validated = _validate_receipt(receipt)
        call = _prepared(self._invoker, options, validated.receipt_digest, "commit")
        command = artifact_commands_pb2.CommitArtifactCommand(
            artifact=validated.artifact,
            staging_receipt_digest=validated.receipt_digest,
        )
        command.context.CopyFrom(
            command_context(
                self._invoker.config,
                call,
                request_digest=canonical_digest(command),
            )
        )
        response = cast(
            artifact_service_pb2.CommitArtifactResponse,
            self._invoker.unary(
                COMMIT_ARTIFACT,
                artifact_service_pb2.CommitArtifactRequest(command=command),
                call=call,
                retry_safe=True,
            ),
        )
        committed = required_response_message(
            response,
            "artifact",
            artifact_reference_pb2.ArtifactRef,
            label="artifact commit",
        )
        _validate_transfer_artifact(committed)
        if committed != validated.artifact:
            raise ProtocolError(
                "artifact commit returned a different content identity",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return committed

    def iter_download(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        *,
        offset: int = 0,
        max_chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        options: CallOptions | None = None,
    ) -> Iterator[bytes]:
        expected = _validate_transfer_artifact(artifact)
        if offset < 0 or offset > expected.size_bytes:
            raise ValueError("artifact download offset is outside the artifact")
        max_chunk_bytes = _chunk_size(max_chunk_bytes)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        cursor = offset
        digest = hashlib.sha256() if offset == 0 else None
        complete = False
        for raw_response in self._invoker.stream(
            DOWNLOAD_ARTIFACT,
            artifact_service_pb2.DownloadArtifactRequest(
                digest=expected.digest,
                offset=offset,
                max_chunk_bytes=max_chunk_bytes,
            ),
            call=call,
        ):
            response = cast(artifact_service_pb2.DownloadArtifactResponse, raw_response)
            data = _verify_download_response(response, expected, cursor)
            if complete:
                raise ProtocolError(
                    "artifact download yielded data after its terminal response",
                    status=grpc.StatusCode.DATA_LOSS,
                )
            cursor += len(data)
            if digest is not None:
                digest.update(data)
            complete = response.complete
            if data:
                yield data
            if complete:
                break
        if not complete or cursor != expected.size_bytes:
            raise ProtocolError(
                "artifact download stream ended before the declared size",
                status=grpc.StatusCode.DATA_LOSS,
            )
        if digest is not None and not hmac.compare_digest(
            "sha256:" + digest.hexdigest(), expected.digest
        ):
            raise ProtocolError(
                "artifact download digest verification failed",
                status=grpc.StatusCode.DATA_LOSS,
            )

    def download(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        destination: BinaryWriter,
        *,
        offset: int = 0,
        max_chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        options: CallOptions | None = None,
    ) -> int:
        written = 0
        for data in self.iter_download(
            artifact,
            offset=offset,
            max_chunk_bytes=max_chunk_bytes,
            options=options,
        ):
            count = destination.write(data)
            if count != len(data):
                raise ProtocolError(
                    "artifact download destination accepted a short write",
                    status=grpc.StatusCode.DATA_LOSS,
                )
            written += count
        return written

    def download_file(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        destination: str | os.PathLike[str],
        *,
        max_chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        options: CallOptions | None = None,
    ) -> int:
        """Download, verify, and atomically publish a new mode-0600 file.

        The destination is never overwritten. A digest mismatch, short write,
        deadline, or other failure removes the same-directory staging file and
        leaves the destination absent or unchanged. Successful no-clobber link
        creation is the commit point; later best-effort staging cleanup cannot
        change a successful result into an ambiguous failure.
        """

        target, directory = _atomic_destination(destination)
        temporary, staging = _new_staging_file(directory)
        try:
            written = self.download(
                artifact,
                temporary,
                max_chunk_bytes=max_chunk_bytes,
                options=options,
            )
            _sync_file(temporary)
            temporary.close()
            _publish_staging_file(staging, target, directory)
            return written
        finally:
            if not temporary.closed:
                temporary.close()
            with suppress(OSError):
                staging.unlink()


class AsyncArtifacts:
    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def get(
        self,
        request: artifact_service_pb2.GetArtifactRequest,
        *,
        options: CallOptions | None = None,
    ) -> artifact_reference_pb2.ArtifactRef:
        value = _clone(request, artifact_service_pb2.GetArtifactRequest)
        if bool(value.name) == bool(value.digest):
            raise ValueError("artifact get requires exactly one canonical name or digest")
        expected = (
            _artifact_name_digest(self._invoker.config.project_parent, value.name)
            if value.name
            else value.digest
        )
        if _CANONICAL_DIGEST.fullmatch(expected) is None:
            raise ValueError("artifact digest must be canonical sha256")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            artifact_service_pb2.GetArtifactResponse,
            await self._invoker.unary(GET_ARTIFACT, value, call=call, retry_safe=True),
        )
        result = required_response_message(
            response,
            "artifact",
            artifact_reference_pb2.ArtifactRef,
            label="artifact get",
        )
        result = _response_artifact(result, label="GetArtifact")
        if not hmac.compare_digest(result.digest, expected):
            raise ProtocolError(
                "GetArtifact returned a different immutable identity",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return result

    async def list(
        self,
        request: artifact_service_pb2.ListArtifactsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ListArtifactsResponse:
        value = (
            artifact_service_pb2.ListArtifactsRequest()
            if request is None
            else _clone(request, artifact_service_pb2.ListArtifactsRequest)
        )
        parent = self._invoker.config.project_parent
        if value.parent and value.parent != parent:
            raise ValueError("artifact list parent must match the configured project")
        if value.page.page_size > _MAX_ARTIFACT_PAGE_SIZE:
            raise ValueError("artifact page size cannot exceed 100")
        value.parent = parent
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        raw = await self._invoker.unary(LIST_ARTIFACTS, value, call=call, retry_safe=True)
        if not isinstance(raw, artifact_service_pb2.ListArtifactsResponse):
            raise ProtocolError(
                "ListArtifacts response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )
        result = _clone(raw, artifact_service_pb2.ListArtifactsResponse)
        for item in result.artifacts:
            _response_artifact(item, label="ListArtifacts")
        return result

    async def quarantine(
        self,
        request: artifact_service_pb2.QuarantineArtifactRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = _clone(request, artifact_service_pb2.QuarantineArtifactRequest)
        artifact = _validate_transfer_artifact(value.artifact)
        if _REASON_CODE.fullmatch(value.reason_code) is None or len(value.evidence) > 100:
            raise ValueError("artifact quarantine reason or evidence count is invalid")
        for evidence in value.evidence:
            if (
                _CANONICAL_DIGEST.fullmatch(evidence.digest) is None
                or not hmac.compare_digest(evidence.subject_digest, artifact.digest)
                or not evidence.evidence_kind
                or len(evidence.evidence_kind) > 128
                or (
                    evidence.policy_digest
                    and _CANONICAL_DIGEST.fullmatch(evidence.policy_digest) is None
                )
            ):
                raise ValueError("artifact quarantine evidence is invalid")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        _attach_context(value, self._invoker, call)
        response = await self._invoker.unary(QUARANTINE_ARTIFACT, value, call=call, retry_safe=True)
        return _operation(
            response,
            label="artifact quarantine",
            tenant_id=self._invoker.config.tenant_id,
            project_id=self._invoker.config.project_id,
        )

    async def acquire_lease(
        self,
        request: artifact_service_pb2.AcquireArtifactLeaseRequest,
        *,
        options: CallOptions | None = None,
    ) -> resource_reference_pb2.ResourceRef:
        value = _clone(request, artifact_service_pb2.AcquireArtifactLeaseRequest)
        _validate_transfer_artifact(value.artifact)
        if not value.HasField("expire_time"):
            raise ValueError("artifact lease expiration is required")
        now = datetime.now(UTC)
        expiration = value.expire_time.ToDatetime(tzinfo=UTC)
        if expiration <= now or expiration > now + _MAX_LEASE_TTL:
            raise ValueError("artifact lease expiration must be within 30 days")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        _attach_context(value, self._invoker, call)
        response = await self._invoker.unary(
            ACQUIRE_ARTIFACT_LEASE, value, call=call, retry_safe=True
        )
        lease = required_response_message(
            response,
            "lease",
            resource_reference_pb2.ResourceRef,
            label="artifact lease acquisition",
        )
        return _validate_lease(
            tenant_id=self._invoker.config.tenant_id,
            project_id=self._invoker.config.project_id,
            parent=self._invoker.config.project_parent,
            lease=lease,
        )

    async def release_lease(
        self,
        request: artifact_service_pb2.ReleaseArtifactLeaseRequest,
        *,
        options: CallOptions | None = None,
    ) -> None:
        value = _clone(request, artifact_service_pb2.ReleaseArtifactLeaseRequest)
        try:
            lease = _validate_lease(
                tenant_id=self._invoker.config.tenant_id,
                project_id=self._invoker.config.project_id,
                parent=self._invoker.config.project_parent,
                lease=value.lease,
            )
        except ProtocolError as error:
            raise ValueError("artifact lease release resource is invalid") from error
        required_text("artifact lease etag", value.etag, maximum=256)
        if lease.etag and not hmac.compare_digest(lease.etag, value.etag):
            raise ValueError("artifact lease and release ETags differ")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=True,
        )
        _attach_context(value, self._invoker, call)
        response = await self._invoker.unary(
            RELEASE_ARTIFACT_LEASE, value, call=call, retry_safe=True
        )
        if not isinstance(response, artifact_service_pb2.ReleaseArtifactLeaseResponse):
            raise ProtocolError(
                "ReleaseArtifactLease response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )

    async def resolve_alias(
        self,
        alias: str,
        *,
        parent: str | None = None,
        options: CallOptions | None = None,
    ) -> artifact_reference_pb2.ArtifactRef:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            artifact_service_pb2.ResolveArtifactAliasResponse,
            await self._invoker.unary(
                RESOLVE_ARTIFACT_ALIAS,
                artifact_service_pb2.ResolveArtifactAliasRequest(
                    parent=required_text(
                        "artifact parent", parent or self._invoker.config.project_parent
                    ),
                    alias=required_text("artifact alias", alias, maximum=256),
                ),
                call=call,
                retry_safe=True,
            ),
        )
        result = required_response_message(
            response,
            "artifact",
            artifact_reference_pb2.ArtifactRef,
            label="artifact resolution",
        )
        artifact_ref("artifact", result)
        return result

    async def get_upload(
        self,
        name: str,
        *,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = await self._invoker.unary(
            GET_ARTIFACT_UPLOAD,
            artifact_service_pb2.GetArtifactUploadRequest(
                name=required_text("artifact upload name", name)
            ),
            call=call,
            retry_safe=True,
        )
        return _upload_from_response(response, label="artifact upload status")

    async def upload(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        source: AsyncIterable[bytes],
        *,
        upload_id: str | None = None,
        chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        session_ttl: timedelta = _DEFAULT_SESSION_TTL,
        receipt_ttl: timedelta = _DEFAULT_RECEIPT_TTL,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactStagingReceipt:
        expected = _validate_transfer_artifact(artifact)
        identity = _upload_id(upload_id)
        chunk_bytes = _chunk_size(chunk_bytes)
        session_ttl = _bounded_lifetime(
            "artifact upload session lifetime", session_ttl, _MAX_SESSION_TTL
        )
        receipt_ttl = _bounded_lifetime(
            "artifact staging receipt lifetime", receipt_ttl, _MAX_RECEIPT_TTL
        )
        upload_name = f"{self._invoker.config.project_parent}/artifactUploads/{identity}"
        upload: artifact_service_pb2.ArtifactUploadSession | None = None
        if upload_id is not None:
            with suppress(NotFoundError):
                upload = await self.get_upload(upload_name, options=options)
        if upload is None:
            begin_call = _prepared(self._invoker, options, identity, "begin")
            begin = artifact_service_pb2.BeginArtifactUploadRequest(
                parent=self._invoker.config.project_parent,
                artifact=expected,
                upload_id=identity,
                expire_time=_timestamp_after(session_ttl),
            )
            _attach_context(begin, self._invoker, begin_call)
            try:
                upload = _upload_from_response(
                    await self._invoker.unary(
                        BEGIN_ARTIFACT_UPLOAD,
                        begin,
                        call=begin_call,
                        retry_safe=True,
                    ),
                    label="artifact upload begin",
                    expected_artifact=expected,
                )
            except ConflictError:
                upload = await self.get_upload(upload_name, options=options)
        upload = _validate_upload(upload, expected_artifact=expected)
        if upload.state == artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED:
            receipt = required_response_message(
                upload,
                "staging_receipt",
                artifact_service_pb2.ArtifactStagingReceipt,
                label="finalized artifact upload",
            )
            return _validate_receipt(receipt, expected_artifact=expected)
        if upload.state != artifact_service_pb2.ARTIFACT_UPLOAD_STATE_OPEN:
            raise ValueError("artifact upload session cannot be resumed")
        reader = _AsyncSourceReader(source)
        full_digest = hashlib.sha256()
        await _async_discard_exact(reader, upload.committed_offset, full_digest)
        offset = upload.committed_offset
        while offset < expected.size_bytes:
            size = min(chunk_bytes, expected.size_bytes - offset)
            data = await reader.read(size)
            if len(data) != size:
                raise ValueError("artifact upload source ended before its declared size")
            full_digest.update(data)
            chunk_digest = "sha256:" + hashlib.sha256(data).hexdigest()
            phase = f"chunk:{upload.next_chunk_index}:{chunk_digest}"
            chunk_call = _prepared(self._invoker, options, identity, phase)
            request = artifact_service_pb2.UploadArtifactChunkRequest(
                name=upload.name,
                chunk_index=upload.next_chunk_index,
                offset=offset,
                data=data,
                chunk_digest=chunk_digest,
                etag=upload.etag,
            )
            _attach_context(request, self._invoker, chunk_call)
            expected_index = upload.next_chunk_index + 1
            expected_offset = offset + len(data)
            upload = _upload_from_response(
                await self._invoker.unary(
                    UPLOAD_ARTIFACT_CHUNK,
                    request,
                    call=chunk_call,
                    retry_safe=True,
                ),
                label="artifact chunk upload",
                expected_artifact=expected,
            )
            if (
                upload.committed_offset != expected_offset
                or upload.next_chunk_index != expected_index
                or upload.state != artifact_service_pb2.ARTIFACT_UPLOAD_STATE_OPEN
            ):
                raise ProtocolError(
                    "artifact upload progress did not advance contiguously",
                    status=grpc.StatusCode.DATA_LOSS,
                )
            offset = upload.committed_offset
        if await reader.read(1):
            raise ValueError("artifact upload source exceeds its declared size")
        if not hmac.compare_digest("sha256:" + full_digest.hexdigest(), expected.digest):
            raise ValueError("artifact upload source digest differs from ArtifactRef")
        finalize_call = _prepared(self._invoker, options, identity, "finalize")
        finalize = artifact_service_pb2.FinalizeArtifactUploadRequest(
            name=upload.name,
            etag=upload.etag,
            receipt_expire_time=_receipt_expiry(upload, receipt_ttl),
        )
        _attach_context(finalize, self._invoker, finalize_call)
        response = cast(
            artifact_service_pb2.FinalizeArtifactUploadResponse,
            await self._invoker.unary(
                FINALIZE_ARTIFACT_UPLOAD,
                finalize,
                call=finalize_call,
                retry_safe=True,
            ),
        )
        finalized = _upload_from_response(
            response,
            label="artifact upload finalize",
            expected_artifact=expected,
        )
        if finalized.state != artifact_service_pb2.ARTIFACT_UPLOAD_STATE_FINALIZED:
            raise ProtocolError(
                "artifact finalize did not return a finalized session",
                status=grpc.StatusCode.DATA_LOSS,
            )
        receipt = required_response_message(
            response,
            "staging_receipt",
            artifact_service_pb2.ArtifactStagingReceipt,
            label="artifact upload finalize",
        )
        return _validate_receipt(receipt, expected_artifact=expected)

    async def abort_upload(
        self,
        name: str,
        etag: str,
        *,
        reason_code: str,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        return await self._transition_upload(
            ABORT_ARTIFACT_UPLOAD,
            artifact_service_pb2.AbortArtifactUploadRequest,
            name,
            etag,
            reason_code,
            artifact_service_pb2.ARTIFACT_UPLOAD_STATE_ABORTED,
            options,
        )

    async def quarantine_upload(
        self,
        name: str,
        etag: str,
        *,
        reason_code: str,
        options: CallOptions | None = None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        return await self._transition_upload(
            QUARANTINE_ARTIFACT_UPLOAD,
            artifact_service_pb2.QuarantineArtifactUploadRequest,
            name,
            etag,
            reason_code,
            artifact_service_pb2.ARTIFACT_UPLOAD_STATE_QUARANTINED,
            options,
        )

    async def _transition_upload(
        self,
        method: str,
        request_type: type[
            artifact_service_pb2.AbortArtifactUploadRequest
            | artifact_service_pb2.QuarantineArtifactUploadRequest
        ],
        name: str,
        etag: str,
        reason_code: str,
        expected_state: int,
        options: CallOptions | None,
    ) -> artifact_service_pb2.ArtifactUploadSession:
        upload_name = required_text("artifact upload name", name)
        transition = method.rsplit("/", 1)[-1]
        call = _prepared(self._invoker, options, upload_name, transition)
        request = request_type(
            name=upload_name,
            etag=required_text("artifact upload etag", etag),
            reason_code=required_text("artifact upload reason code", reason_code, maximum=128),
        )
        _attach_context(request, self._invoker, call)
        upload = _upload_from_response(
            await self._invoker.unary(method, request, call=call, retry_safe=True),
            label="artifact upload transition",
        )
        if upload.state != expected_state:
            raise ProtocolError(
                "artifact upload transition returned an unexpected state",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return upload

    async def commit(
        self,
        receipt: artifact_service_pb2.ArtifactStagingReceipt,
        *,
        options: CallOptions | None = None,
    ) -> artifact_reference_pb2.ArtifactRef:
        validated = _validate_receipt(receipt)
        call = _prepared(self._invoker, options, validated.receipt_digest, "commit")
        command = artifact_commands_pb2.CommitArtifactCommand(
            artifact=validated.artifact,
            staging_receipt_digest=validated.receipt_digest,
        )
        command.context.CopyFrom(
            command_context(
                self._invoker.config,
                call,
                request_digest=canonical_digest(command),
            )
        )
        response = cast(
            artifact_service_pb2.CommitArtifactResponse,
            await self._invoker.unary(
                COMMIT_ARTIFACT,
                artifact_service_pb2.CommitArtifactRequest(command=command),
                call=call,
                retry_safe=True,
            ),
        )
        committed = required_response_message(
            response,
            "artifact",
            artifact_reference_pb2.ArtifactRef,
            label="artifact commit",
        )
        _validate_transfer_artifact(committed)
        if committed != validated.artifact:
            raise ProtocolError(
                "artifact commit returned a different content identity",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return committed

    async def iter_download(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        *,
        offset: int = 0,
        max_chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        options: CallOptions | None = None,
    ) -> AsyncIterator[bytes]:
        expected = _validate_transfer_artifact(artifact)
        if offset < 0 or offset > expected.size_bytes:
            raise ValueError("artifact download offset is outside the artifact")
        max_chunk_bytes = _chunk_size(max_chunk_bytes)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        cursor = offset
        digest = hashlib.sha256() if offset == 0 else None
        complete = False
        async for raw_response in self._invoker.stream(
            DOWNLOAD_ARTIFACT,
            artifact_service_pb2.DownloadArtifactRequest(
                digest=expected.digest,
                offset=offset,
                max_chunk_bytes=max_chunk_bytes,
            ),
            call=call,
        ):
            response = cast(artifact_service_pb2.DownloadArtifactResponse, raw_response)
            data = _verify_download_response(response, expected, cursor)
            if complete:
                raise ProtocolError(
                    "artifact download yielded data after its terminal response",
                    status=grpc.StatusCode.DATA_LOSS,
                )
            cursor += len(data)
            if digest is not None:
                digest.update(data)
            complete = response.complete
            if data:
                yield data
            if complete:
                break
        if not complete or cursor != expected.size_bytes:
            raise ProtocolError(
                "artifact download stream ended before the declared size",
                status=grpc.StatusCode.DATA_LOSS,
            )
        if digest is not None and not hmac.compare_digest(
            "sha256:" + digest.hexdigest(), expected.digest
        ):
            raise ProtocolError(
                "artifact download digest verification failed",
                status=grpc.StatusCode.DATA_LOSS,
            )

    async def download(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        destination: BinaryWriter,
        *,
        offset: int = 0,
        max_chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        options: CallOptions | None = None,
    ) -> int:
        """Stream a verified artifact into a synchronous binary writer.

        Blocking writes run outside the event loop. Cancellation waits for an
        in-flight write to finish before returning, so the writer is never
        concurrently mutated after this method exits.
        """

        written = 0
        async for data in self.iter_download(
            artifact,
            offset=offset,
            max_chunk_bytes=max_chunk_bytes,
            options=options,
        ):
            count = await _run_file_operation(destination.write, data)
            if count != len(data):
                raise ProtocolError(
                    "artifact download destination accepted a short write",
                    status=grpc.StatusCode.DATA_LOSS,
                )
            written += count
        return written

    async def download_file(
        self,
        artifact: artifact_reference_pb2.ArtifactRef,
        destination: str | os.PathLike[str],
        *,
        max_chunk_bytes: int = _DEFAULT_CHUNK_BYTES,
        options: CallOptions | None = None,
    ) -> int:
        """Asynchronously download and atomically publish a verified new file."""

        target, directory = _atomic_destination(destination)
        temporary, staging = await _run_file_operation(_new_staging_file, directory)
        try:
            written = await self.download(
                artifact,
                temporary,
                max_chunk_bytes=max_chunk_bytes,
                options=options,
            )
            await _run_file_operation(_sync_file, temporary)
            temporary.close()
            # Deliver any already-pending cancellation before the atomic
            # commit. Publication itself is the linearization point.
            await asyncio.sleep(0)
            await _commit_staging_file(staging, target, directory)
            return written
        finally:
            if not temporary.closed:
                temporary.close()
            with suppress(OSError):
                staging.unlink()
