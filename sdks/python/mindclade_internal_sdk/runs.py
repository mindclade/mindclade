"""Worker-safe RunService conveniences over generated protobuf/gRPC clients."""

from __future__ import annotations

import copy
import hashlib
import hmac
import re
import weakref
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Never, cast

import grpc
from google.protobuf.duration_pb2 import Duration
from google.protobuf.message import Message
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import attempt_pb2, lease_fencing_pb2, run_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._raw import AsyncWithRawResponse, WithRawResponse
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import ProtocolError
from .jobs import canonical_resource
from .pagination import (
    AsyncPage,
    Page,
    PaginationLimits,
    apply_default_page_size,
    async_page,
    next_request,
    sync_page,
)
from .transport import (
    ACQUIRE_ATTEMPT_LEASE,
    CANCEL_ATTEMPT,
    COMMIT_ATTEMPT,
    GET_ATTEMPT,
    GET_RUN,
    HEARTBEAT_ATTEMPT,
    LIST_ATTEMPTS,
    LIST_RUNS,
    RENEW_ATTEMPT_LEASE,
    Metadata,
)

_RESOURCE = re.compile(r"(?P<collection>[a-zA-Z][a-zA-Z0-9]*)/[A-Za-z0-9_.-]{1,255}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LEASE_HEADER = "x-mindclade-lease-token"
_MIN_LEASE = timedelta(seconds=5)
_MAX_LEASE = timedelta(minutes=15)
_MAX_PAGE_SIZE = 200
_CAPTURE = object()
_SECRETS: weakref.WeakKeyDictionary[object, str] = weakref.WeakKeyDictionary()


class LeaseCredential:
    """Opaque, redacting handle for one response-metadata lease capability."""

    __slots__ = ("__weakref__",)

    def __init__(self, token: str, *, _capture: object | None = None) -> None:
        if _capture is not _CAPTURE:
            raise TypeError("LeaseCredential values can only be issued by Runs.acquire_lease")
        _SECRETS[self] = token

    def __repr__(self) -> str:
        return "LeaseCredential(<redacted>)"

    __str__ = __repr__

    def __reduce__(self) -> Never:
        raise TypeError("LeaseCredential cannot be serialized")


class AttemptLease:
    """Clone-safe generated lease state plus its opaque transport credential."""

    __slots__ = ("_attempt", "_credential", "_fence")

    def __init__(
        self,
        attempt: attempt_pb2.Attempt,
        fence: lease_fencing_pb2.LeaseFence,
        credential: LeaseCredential,
    ) -> None:
        self._attempt = copy.deepcopy(attempt)
        self._fence = copy.deepcopy(fence)
        self._credential = credential

    @property
    def attempt(self) -> attempt_pb2.Attempt:
        return copy.deepcopy(self._attempt)

    @property
    def fence(self) -> lease_fencing_pb2.LeaseFence:
        return copy.deepcopy(self._fence)

    @property
    def credential(self) -> LeaseCredential:
        return self._credential


type _RunMutation = (
    job_service_pb2.AcquireAttemptLeaseRequest
    | job_service_pb2.RenewAttemptLeaseRequest
    | job_service_pb2.HeartbeatAttemptRequest
    | job_service_pb2.CancelAttemptRequest
    | job_service_pb2.CommitAttemptRequest
)
type _FencedMutation = (
    job_service_pb2.RenewAttemptLeaseRequest
    | job_service_pb2.HeartbeatAttemptRequest
    | job_service_pb2.CancelAttemptRequest
    | job_service_pb2.CommitAttemptRequest
)


def _is_resource(value: str, collection: str) -> bool:
    match = _RESOURCE.fullmatch(value)
    return match is not None and match.group("collection") == collection


def _duration(value: Duration) -> None:
    if not 0 <= value.nanos < 1_000_000_000:
        raise ValueError("lease duration has invalid nanoseconds")
    try:
        lifetime = value.ToTimedelta()
    except (OverflowError, ValueError) as error:
        raise ValueError("lease duration is invalid") from error
    if not _MIN_LEASE <= lifetime <= _MAX_LEASE:
        raise ValueError("lease duration must be between 5 seconds and 15 minutes")


def _mutation_options(
    key: str,
    options: CallOptions | None,
    credential: object | None,
) -> CallOptions | None:
    if options is not None and options.lease_token is not None:
        raise ValueError("raw lease tokens are not accepted; pass a LeaseCredential")
    selected = options
    if key and (selected is None or selected.idempotency_key is None):
        selected = (
            replace(selected, idempotency_key=key) if selected else CallOptions(idempotency_key=key)
        )
    if credential is not None:
        if not isinstance(credential, LeaseCredential):
            raise ValueError("a scheduler-issued LeaseCredential is required")
        token = _SECRETS.get(credential)
        if token is None:
            raise ValueError("lease credential is no longer valid")
        selected = (
            replace(selected, lease_token=token) if selected else CallOptions(lease_token=token)
        )
    return selected


def _prepare_mutation[RequestT: _RunMutation](
    invoker: SyncInvoker | AsyncInvoker,
    request: RequestT,
    options: CallOptions | None,
    *,
    credential: LeaseCredential | None = None,
) -> tuple[RequestT, PreparedCall]:
    materialized = copy.deepcopy(request)
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options, credential),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    materialized.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(materialized))
    )
    return materialized, call


def _normalize_fence(
    invoker: SyncInvoker | AsyncInvoker, fence: lease_fencing_pb2.LeaseFence
) -> None:
    if (
        not _is_resource(fence.job_id, "jobs")
        or not _is_resource(fence.run_id, "runs")
        or not _is_resource(fence.attempt_id, "attempts")
        or fence.lease_epoch <= 0
        or not fence.HasField("deadline")
        or _DIGEST.fullmatch(fence.lease_token_digest) is None
    ):
        raise ValueError("current complete lease fence is required")
    try:
        deadline = fence.deadline.ToDatetime(tzinfo=UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError("lease deadline is invalid") from error
    if deadline <= datetime.now(UTC):
        raise ValueError("lease fence has expired")
    config = invoker.config
    if fence.tenant_id not in ("", config.tenant_id) or fence.project_id not in (
        "",
        config.project_id,
    ):
        raise ValueError("lease fence conflicts with configured scope")
    fence.tenant_id = config.tenant_id
    fence.project_id = config.project_id


def _valid_run(invoker: SyncInvoker | AsyncInvoker, value: run_pb2.Run) -> bool:
    config = invoker.config
    return (
        value.tenant_id == config.tenant_id
        and value.project_id == config.project_id
        and _is_resource(value.run_id, "runs")
        and _is_resource(value.job_id, "jobs")
        and value.resource_version > 0
        and value.state != run_pb2.RUN_STATE_UNSPECIFIED
    )


def _valid_attempt(invoker: SyncInvoker | AsyncInvoker, value: attempt_pb2.Attempt) -> bool:
    config = invoker.config
    return (
        value.tenant_id == config.tenant_id
        and value.project_id == config.project_id
        and _is_resource(value.attempt_id, "attempts")
        and _is_resource(value.run_id, "runs")
        and _is_resource(value.job_id, "jobs")
        and value.resource_version > 0
        and value.lease_epoch > 0
        and value.state != attempt_pb2.ATTEMPT_STATE_UNSPECIFIED
    )


def _valid_lease(
    invoker: SyncInvoker | AsyncInvoker,
    attempt: attempt_pb2.Attempt,
    fence: lease_fencing_pb2.LeaseFence,
    *,
    credential: LeaseCredential | None = None,
) -> bool:
    config = invoker.config
    valid = (
        _valid_attempt(invoker, attempt)
        and fence.tenant_id == config.tenant_id
        and fence.project_id == config.project_id
        and attempt.job_id == fence.job_id
        and attempt.run_id == fence.run_id
        and attempt.attempt_id == fence.attempt_id
        and attempt.lease_epoch == fence.lease_epoch
        and fence.HasField("deadline")
        and _DIGEST.fullmatch(fence.lease_token_digest) is not None
    )
    if valid:
        try:
            valid = fence.deadline.ToDatetime(tzinfo=UTC) > datetime.now(UTC)
        except (OverflowError, ValueError):
            valid = False
    if not valid or credential is None:
        return valid
    token = _SECRETS.get(credential)
    if token is None:
        return False
    digest = "sha256:" + hashlib.sha256(token.encode("ascii")).hexdigest()
    return hmac.compare_digest(digest, fence.lease_token_digest)


def _lease_token(metadata: Metadata) -> LeaseCredential:
    values: list[str] = []
    for key, raw in metadata:
        if key.lower() != _LEASE_HEADER:
            continue
        try:
            values.append(raw.decode("ascii") if isinstance(raw, bytes) else raw)
        except UnicodeDecodeError as error:
            raise ProtocolError(
                "lease credential response metadata was invalid",
                status=grpc.StatusCode.DATA_LOSS,
            ) from error
    if len(values) != 1:
        raise ProtocolError(
            "lease acquisition omitted its confidential credential",
            status=grpc.StatusCode.DATA_LOSS,
        )
    token = values[0]
    if (
        not 32 <= len(token) <= 4096
        or token != token.strip()
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in token)
    ):
        raise ProtocolError(
            "lease credential response metadata was invalid",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return LeaseCredential(token, _capture=_CAPTURE)


def _require_response[ResponseT: Message](
    raw: Message, expected: type[ResponseT], label: str
) -> ResponseT:
    if not isinstance(raw, expected):
        raise ProtocolError(
            f"{label} response violated its generated contract",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return copy.deepcopy(raw)


def _list_runs_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: job_service_pb2.ListRunsRequest,
) -> job_service_pb2.ListRunsRequest:
    value = copy.deepcopy(request)
    value.parent = canonical_resource(invoker, value.parent, "jobs")
    if value.page.page_size > _MAX_PAGE_SIZE or value.filter.strip():
        raise ValueError("run page exceeds 200 or has an unsupported filter")
    return value


def _list_attempts_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: job_service_pb2.ListAttemptsRequest,
) -> job_service_pb2.ListAttemptsRequest:
    value = copy.deepcopy(request)
    value.parent = canonical_resource(invoker, value.parent, "runs")
    if value.page.page_size > _MAX_PAGE_SIZE:
        raise ValueError("attempt page size cannot exceed 200")
    return value


def _fenced[RequestT: _FencedMutation](
    invoker: SyncInvoker | AsyncInvoker,
    request: Message,
    expected: type[RequestT],
    credential: LeaseCredential,
    options: CallOptions | None,
    *,
    duration_required: bool,
) -> tuple[RequestT, PreparedCall]:
    if not isinstance(request, expected):
        raise TypeError(f"request must be the generated {expected.__name__}")
    value = copy.deepcopy(request)
    if value.expected_resource_version <= 0 or not value.HasField("fence"):
        raise ValueError("fenced mutation requires a current revision and fence")
    _normalize_fence(invoker, value.fence)
    if duration_required:
        if not isinstance(
            value,
            (
                job_service_pb2.RenewAttemptLeaseRequest,
                job_service_pb2.HeartbeatAttemptRequest,
            ),
        ) or not value.HasField("lease_duration"):
            raise ValueError("fenced renewal requires lease_duration")
        _duration(value.lease_duration)
    return _prepare_mutation(invoker, value, options, credential=credential)


class Runs(WithRawResponse):
    """Synchronous generated Run and fenced Attempt lifecycle API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def get_run(self, name: str, *, options: CallOptions | None = None) -> run_pb2.Run:
        canonical = canonical_resource(self._invoker, name, "runs")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            job_service_pb2.GetRunResponse,
            self._invoker.unary(
                GET_RUN,
                job_service_pb2.GetRunRequest(name=canonical),
                call=call,
                retry_safe=True,
            ),
        )
        value = _require_response(response, job_service_pb2.GetRunResponse, "run get")
        if (
            not value.HasField("run")
            or value.run.run_id != canonical
            or not _valid_run(self._invoker, value.run)
        ):
            raise ProtocolError(
                "run response violated durable identity", status=grpc.StatusCode.DATA_LOSS
            )
        return copy.deepcopy(value.run)

    def list_runs(
        self,
        request: job_service_pb2.ListRunsRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[run_pb2.Run]:
        materialized = _list_runs_request(self._invoker, request)
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = _require_response(
            self._invoker.unary(LIST_RUNS, materialized, call=call, retry_safe=True),
            job_service_pb2.ListRunsResponse,
            "run list",
        )
        if any(
            not _valid_run(self._invoker, value) or value.job_id != materialized.parent
            for value in response.runs
        ):
            raise ProtocolError(
                "run list escaped requested scope", status=grpc.StatusCode.DATA_LOSS
            )

        def follow(page_token: str) -> Page[run_pb2.Run]:
            return self.list_runs(
                next_request(materialized, page_token), options=options, limits=limits
            )

        return sync_page(response, items_field="runs", fetch=follow, limits=limits)

    def get_attempt(self, name: str, *, options: CallOptions | None = None) -> attempt_pb2.Attempt:
        canonical = canonical_resource(self._invoker, name, "attempts")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = _require_response(
            self._invoker.unary(
                GET_ATTEMPT,
                job_service_pb2.GetAttemptRequest(name=canonical),
                call=call,
                retry_safe=True,
            ),
            job_service_pb2.GetAttemptResponse,
            "attempt get",
        )
        if (
            not response.HasField("attempt")
            or response.attempt.attempt_id != canonical
            or not _valid_attempt(self._invoker, response.attempt)
        ):
            raise ProtocolError(
                "attempt response violated durable identity", status=grpc.StatusCode.DATA_LOSS
            )
        return copy.deepcopy(response.attempt)

    def list_attempts(
        self,
        request: job_service_pb2.ListAttemptsRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[attempt_pb2.Attempt]:
        materialized = _list_attempts_request(self._invoker, request)
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = _require_response(
            self._invoker.unary(LIST_ATTEMPTS, materialized, call=call, retry_safe=True),
            job_service_pb2.ListAttemptsResponse,
            "attempt list",
        )
        if any(
            not _valid_attempt(self._invoker, value) or value.run_id != materialized.parent
            for value in response.attempts
        ):
            raise ProtocolError(
                "attempt list escaped requested scope", status=grpc.StatusCode.DATA_LOSS
            )

        def follow(page_token: str) -> Page[attempt_pb2.Attempt]:
            return self.list_attempts(
                next_request(materialized, page_token), options=options, limits=limits
            )

        return sync_page(response, items_field="attempts", fetch=follow, limits=limits)

    def acquire_lease(
        self,
        request: job_service_pb2.AcquireAttemptLeaseRequest,
        *,
        options: CallOptions | None = None,
    ) -> AttemptLease:
        value = copy.deepcopy(request)
        value.run_name = canonical_resource(self._invoker, value.run_name, "runs")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", value.attempt_id):
            raise ValueError("attempt ID is invalid")
        if not value.HasField("lease_duration"):
            raise ValueError("lease_duration is required")
        _duration(value.lease_duration)
        materialized, call = _prepare_mutation(self._invoker, value, options)
        raw, metadata = self._invoker.unary_with_metadata(
            ACQUIRE_ATTEMPT_LEASE, materialized, call=call, retry_safe=True
        )
        response = _require_response(
            raw, job_service_pb2.AcquireAttemptLeaseResponse, "lease acquisition"
        )
        credential = _lease_token(metadata)
        if (
            not response.HasField("attempt")
            or not response.HasField("fence")
            or not _valid_lease(
                self._invoker, response.attempt, response.fence, credential=credential
            )
        ):
            raise ProtocolError(
                "lease acquisition returned inconsistent authority",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return AttemptLease(response.attempt, response.fence, credential)

    def renew_lease(
        self,
        request: job_service_pb2.RenewAttemptLeaseRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> AttemptLease:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.RenewAttemptLeaseRequest,
            credential,
            options,
            duration_required=True,
        )
        response = _require_response(
            self._invoker.unary(RENEW_ATTEMPT_LEASE, materialized, call=call, retry_safe=True),
            job_service_pb2.RenewAttemptLeaseResponse,
            "lease renewal",
        )
        if (
            not response.HasField("attempt")
            or not response.HasField("fence")
            or not _valid_lease(
                self._invoker, response.attempt, response.fence, credential=credential
            )
        ):
            raise ProtocolError(
                "lease renewal returned inconsistent authority", status=grpc.StatusCode.DATA_LOSS
            )
        return AttemptLease(response.attempt, response.fence, credential)

    def heartbeat(
        self,
        request: job_service_pb2.HeartbeatAttemptRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.HeartbeatAttemptResponse:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.HeartbeatAttemptRequest,
            credential,
            options,
            duration_required=True,
        )
        response = _require_response(
            self._invoker.unary(HEARTBEAT_ATTEMPT, materialized, call=call, retry_safe=True),
            job_service_pb2.HeartbeatAttemptResponse,
            "attempt heartbeat",
        )
        if (
            not response.HasField("observed_at")
            or not response.HasField("attempt")
            or not response.HasField("fence")
            or not _valid_lease(
                self._invoker, response.attempt, response.fence, credential=credential
            )
        ):
            raise ProtocolError(
                "attempt heartbeat returned inconsistent authority",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return response

    def cancel_attempt(
        self,
        request: job_service_pb2.CancelAttemptRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.CancelAttemptResponse:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.CancelAttemptRequest,
            credential,
            options,
            duration_required=False,
        )
        if len(materialized.reason) > 1024 or "\x00" in materialized.reason:
            raise ValueError("attempt cancellation reason is invalid")
        response = _require_response(
            self._invoker.unary(CANCEL_ATTEMPT, materialized, call=call, retry_safe=True),
            job_service_pb2.CancelAttemptResponse,
            "attempt cancellation",
        )
        if (
            not response.HasField("attempt")
            or not response.HasField("run")
            or not _valid_attempt(self._invoker, response.attempt)
            or not _valid_run(self._invoker, response.run)
            or response.attempt.run_id != response.run.run_id
            or response.attempt.job_id != response.run.job_id
        ):
            raise ProtocolError(
                "attempt cancellation returned inconsistent state", status=grpc.StatusCode.DATA_LOSS
            )
        return response

    def commit_attempt(
        self,
        request: job_service_pb2.CommitAttemptRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.CommitAttemptResponse:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.CommitAttemptRequest,
            credential,
            options,
            duration_required=False,
        )
        _validate_commit(self._invoker, materialized)
        response = _require_response(
            self._invoker.unary(COMMIT_ATTEMPT, materialized, call=call, retry_safe=True),
            job_service_pb2.CommitAttemptResponse,
            "attempt commit",
        )
        if (
            not response.HasField("attempt")
            or not response.HasField("run")
            or not _valid_attempt(self._invoker, response.attempt)
            or not _valid_run(self._invoker, response.run)
            or response.attempt.run_id != response.run.run_id
            or response.attempt.job_id != response.run.job_id
        ):
            raise ProtocolError(
                "attempt commit returned inconsistent state", status=grpc.StatusCode.DATA_LOSS
            )
        return response


class AsyncRuns(AsyncWithRawResponse):
    """Asyncio-native generated Run and fenced Attempt lifecycle API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def get_run(self, name: str, *, options: CallOptions | None = None) -> run_pb2.Run:
        canonical = canonical_resource(self._invoker, name, "runs")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = _require_response(
            await self._invoker.unary(
                GET_RUN, job_service_pb2.GetRunRequest(name=canonical), call=call, retry_safe=True
            ),
            job_service_pb2.GetRunResponse,
            "run get",
        )
        if (
            not response.HasField("run")
            or response.run.run_id != canonical
            or not _valid_run(self._invoker, response.run)
        ):
            raise ProtocolError(
                "run response violated durable identity", status=grpc.StatusCode.DATA_LOSS
            )
        return copy.deepcopy(response.run)

    async def list_runs(
        self,
        request: job_service_pb2.ListRunsRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[run_pb2.Run]:
        materialized = _list_runs_request(self._invoker, request)
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = _require_response(
            await self._invoker.unary(LIST_RUNS, materialized, call=call, retry_safe=True),
            job_service_pb2.ListRunsResponse,
            "run list",
        )
        if any(
            not _valid_run(self._invoker, value) or value.job_id != materialized.parent
            for value in response.runs
        ):
            raise ProtocolError(
                "run list escaped requested scope", status=grpc.StatusCode.DATA_LOSS
            )

        async def follow(page_token: str) -> AsyncPage[run_pb2.Run]:
            return await self.list_runs(
                next_request(materialized, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="runs", fetch=follow, limits=limits)

    async def get_attempt(
        self, name: str, *, options: CallOptions | None = None
    ) -> attempt_pb2.Attempt:
        canonical = canonical_resource(self._invoker, name, "attempts")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = _require_response(
            await self._invoker.unary(
                GET_ATTEMPT,
                job_service_pb2.GetAttemptRequest(name=canonical),
                call=call,
                retry_safe=True,
            ),
            job_service_pb2.GetAttemptResponse,
            "attempt get",
        )
        if (
            not response.HasField("attempt")
            or response.attempt.attempt_id != canonical
            or not _valid_attempt(self._invoker, response.attempt)
        ):
            raise ProtocolError(
                "attempt response violated durable identity", status=grpc.StatusCode.DATA_LOSS
            )
        return copy.deepcopy(response.attempt)

    async def list_attempts(
        self,
        request: job_service_pb2.ListAttemptsRequest,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[attempt_pb2.Attempt]:
        materialized = _list_attempts_request(self._invoker, request)
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = _require_response(
            await self._invoker.unary(LIST_ATTEMPTS, materialized, call=call, retry_safe=True),
            job_service_pb2.ListAttemptsResponse,
            "attempt list",
        )
        if any(
            not _valid_attempt(self._invoker, value) or value.run_id != materialized.parent
            for value in response.attempts
        ):
            raise ProtocolError(
                "attempt list escaped requested scope", status=grpc.StatusCode.DATA_LOSS
            )

        async def follow(page_token: str) -> AsyncPage[attempt_pb2.Attempt]:
            return await self.list_attempts(
                next_request(materialized, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="attempts", fetch=follow, limits=limits)

    async def acquire_lease(
        self,
        request: job_service_pb2.AcquireAttemptLeaseRequest,
        *,
        options: CallOptions | None = None,
    ) -> AttemptLease:
        value = copy.deepcopy(request)
        value.run_name = canonical_resource(self._invoker, value.run_name, "runs")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", value.attempt_id):
            raise ValueError("attempt ID is invalid")
        if not value.HasField("lease_duration"):
            raise ValueError("lease_duration is required")
        _duration(value.lease_duration)
        materialized, call = _prepare_mutation(self._invoker, value, options)
        raw, metadata = await self._invoker.unary_with_metadata(
            ACQUIRE_ATTEMPT_LEASE, materialized, call=call, retry_safe=True
        )
        response = _require_response(
            raw, job_service_pb2.AcquireAttemptLeaseResponse, "lease acquisition"
        )
        credential = _lease_token(metadata)
        if (
            not response.HasField("attempt")
            or not response.HasField("fence")
            or not _valid_lease(
                self._invoker, response.attempt, response.fence, credential=credential
            )
        ):
            raise ProtocolError(
                "lease acquisition returned inconsistent authority",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return AttemptLease(response.attempt, response.fence, credential)

    async def renew_lease(
        self,
        request: job_service_pb2.RenewAttemptLeaseRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> AttemptLease:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.RenewAttemptLeaseRequest,
            credential,
            options,
            duration_required=True,
        )
        response = _require_response(
            await self._invoker.unary(
                RENEW_ATTEMPT_LEASE, materialized, call=call, retry_safe=True
            ),
            job_service_pb2.RenewAttemptLeaseResponse,
            "lease renewal",
        )
        if (
            not response.HasField("attempt")
            or not response.HasField("fence")
            or not _valid_lease(
                self._invoker, response.attempt, response.fence, credential=credential
            )
        ):
            raise ProtocolError(
                "lease renewal returned inconsistent authority", status=grpc.StatusCode.DATA_LOSS
            )
        return AttemptLease(response.attempt, response.fence, credential)

    async def heartbeat(
        self,
        request: job_service_pb2.HeartbeatAttemptRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.HeartbeatAttemptResponse:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.HeartbeatAttemptRequest,
            credential,
            options,
            duration_required=True,
        )
        response = _require_response(
            await self._invoker.unary(HEARTBEAT_ATTEMPT, materialized, call=call, retry_safe=True),
            job_service_pb2.HeartbeatAttemptResponse,
            "attempt heartbeat",
        )
        if (
            not response.HasField("observed_at")
            or not response.HasField("attempt")
            or not response.HasField("fence")
            or not _valid_lease(
                self._invoker, response.attempt, response.fence, credential=credential
            )
        ):
            raise ProtocolError(
                "attempt heartbeat returned inconsistent authority",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return response

    async def cancel_attempt(
        self,
        request: job_service_pb2.CancelAttemptRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.CancelAttemptResponse:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.CancelAttemptRequest,
            credential,
            options,
            duration_required=False,
        )
        if len(materialized.reason) > 1024 or "\x00" in materialized.reason:
            raise ValueError("attempt cancellation reason is invalid")
        response = _require_response(
            await self._invoker.unary(CANCEL_ATTEMPT, materialized, call=call, retry_safe=True),
            job_service_pb2.CancelAttemptResponse,
            "attempt cancellation",
        )
        if (
            not response.HasField("attempt")
            or not response.HasField("run")
            or not _valid_attempt(self._invoker, response.attempt)
            or not _valid_run(self._invoker, response.run)
            or response.attempt.run_id != response.run.run_id
            or response.attempt.job_id != response.run.job_id
        ):
            raise ProtocolError(
                "attempt cancellation returned inconsistent state", status=grpc.StatusCode.DATA_LOSS
            )
        return response

    async def commit_attempt(
        self,
        request: job_service_pb2.CommitAttemptRequest,
        credential: LeaseCredential,
        *,
        options: CallOptions | None = None,
    ) -> job_service_pb2.CommitAttemptResponse:
        materialized, call = _fenced(
            self._invoker,
            request,
            job_service_pb2.CommitAttemptRequest,
            credential,
            options,
            duration_required=False,
        )
        _validate_commit(self._invoker, materialized)
        response = _require_response(
            await self._invoker.unary(COMMIT_ATTEMPT, materialized, call=call, retry_safe=True),
            job_service_pb2.CommitAttemptResponse,
            "attempt commit",
        )
        if (
            not response.HasField("attempt")
            or not response.HasField("run")
            or not _valid_attempt(self._invoker, response.attempt)
            or not _valid_run(self._invoker, response.run)
            or response.attempt.run_id != response.run.run_id
            or response.attempt.job_id != response.run.job_id
        ):
            raise ProtocolError(
                "attempt commit returned inconsistent state", status=grpc.StatusCode.DATA_LOSS
            )
        return response


def _validate_commit(
    invoker: SyncInvoker | AsyncInvoker,
    request: job_service_pb2.CommitAttemptRequest,
) -> None:
    if not request.HasField("attempt") or not _valid_attempt(invoker, request.attempt):
        raise ValueError("attempt commit requires scoped generated attempt state")
    if not request.HasField("update_mask"):
        raise ValueError("attempt commit requires an update mask")
    paths = tuple(request.update_mask.paths)
    if (
        not paths
        or len(paths) > 3
        or len(set(paths)) != len(paths)
        or "state" not in paths
        or any(path not in {"state", "outputs", "error"} for path in paths)
    ):
        raise ValueError("attempt update mask must include state and only terminal fields")
    fence = request.fence
    attempt = request.attempt
    if (
        attempt.attempt_id != fence.attempt_id
        or attempt.run_id != fence.run_id
        or attempt.job_id != fence.job_id
        or attempt.lease_epoch != fence.lease_epoch
    ):
        raise ValueError("attempt commit identity does not match current fence")
