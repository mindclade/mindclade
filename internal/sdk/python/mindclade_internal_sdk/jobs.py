"""Durable job conveniences over authoritative generated JobService RPCs."""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import cast

import grpc
from google.protobuf.message import Message
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.job.v1 import job_commands_pb2, job_pb2, operation_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._raw import AsyncWithRawResponse, WithRawResponse
from ._validation import artifact_ref, required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import ProtocolError
from .pagination import (
    AsyncPage,
    Page,
    PaginationLimits,
    apply_default_page_size,
    async_page,
    next_request,
    sync_page,
)
from .transport import CANCEL_JOB, GET_JOB, LIST_JOBS, REQUEST_JOB

_LEAF = re.compile(r"[A-Za-z0-9_.-]{1,255}\Z")
_RESOURCE = re.compile(r"(?P<collection>[A-Za-z][A-Za-z0-9]*)/[A-Za-z0-9_.-]{1,255}\Z")
_MAX_PAGE_SIZE = 200


def _leaf(label: str, value: str) -> str:
    normalized = required_text(label, value, maximum=255)
    if _LEAF.fullmatch(normalized) is None:
        raise ValueError(f"{label} must be a resource-name leaf")
    return normalized


def canonical_resource(invoker: SyncInvoker | AsyncInvoker, value: str, collection: str) -> str:
    name = required_text(f"{collection} name", value, maximum=2048)
    prefix = f"{invoker.config.project_parent}/{collection}/"
    if name.startswith(prefix):
        return f"{collection}/{_leaf(f'{collection} ID', name.removeprefix(prefix))}"
    parts = name.split("/", maxsplit=1)
    if len(parts) == 1:
        return f"{collection}/{_leaf(f'{collection} ID', parts[0])}"
    if parts[0] == collection:
        return f"{collection}/{_leaf(f'{collection} ID', parts[1])}"
    raise ValueError(f"{collection} name is outside the configured project")


def _artifact(label: str, value: artifact_reference_pb2.ArtifactRef) -> None:
    artifact_ref(label, value)


def _is_resource(value: str, collection: str) -> bool:
    match = _RESOURCE.fullmatch(value)
    return match is not None and match.group("collection") == collection


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _prepare_command(
    invoker: SyncInvoker | AsyncInvoker,
    command: job_commands_pb2.RequestJobCommand,
    options: CallOptions | None,
) -> tuple[job_service_pb2.RequestJobRequest, PreparedCall]:
    materialized = copy.deepcopy(command)
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    _leaf("job kind", materialized.job_kind)
    if materialized.requested_job_id:
        _leaf("requested job ID", materialized.requested_job_id)
    if materialized.HasField("input"):
        _artifact("job input", materialized.input)
    if not materialized.HasField("configuration"):
        raise ValueError("job configuration is required")
    _artifact("job configuration", materialized.configuration)
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    materialized.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(materialized))
    )
    return job_service_pb2.RequestJobRequest(command=materialized), call


def _prepare_mutation(
    invoker: SyncInvoker | AsyncInvoker,
    request: job_service_pb2.CancelJobRequest,
    options: CallOptions | None,
) -> tuple[job_service_pb2.CancelJobRequest, PreparedCall]:
    materialized = copy.deepcopy(request)
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    materialized.name = canonical_resource(invoker, materialized.name, "jobs")
    required_text("job ETag", materialized.etag, maximum=512)
    if len(materialized.reason) > 4096 or "\x00" in materialized.reason:
        raise ValueError("job cancellation reason is invalid")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    materialized.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(materialized))
    )
    return materialized, call


def _job(
    invoker: SyncInvoker | AsyncInvoker,
    response: Message,
    *,
    label: str,
    expected_name: str | None = None,
) -> job_pb2.Job:
    value = required_response_message(response, "job", job_pb2.Job, label=label)
    config = invoker.config
    if (
        value.tenant_id != config.tenant_id
        or value.project_id != config.project_id
        or value.resource_version <= 0
        or value.state == job_pb2.JOB_STATE_UNSPECIFIED
        or not _is_resource(value.job_id, "jobs")
        or not _is_resource(value.operation_id, "operations")
        or (expected_name is not None and value.job_id != expected_name)
    ):
        raise ProtocolError(
            f"{label} returned invalid or cross-project job state",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return value


def _operation(
    invoker: SyncInvoker | AsyncInvoker,
    response: Message,
    *,
    label: str,
) -> operation_pb2.Operation:
    value = required_response_message(response, "operation", operation_pb2.Operation, label=label)
    config = invoker.config
    if (
        value.tenant_id != config.tenant_id
        or value.project_id != config.project_id
        or value.resource_version <= 0
        or value.state == operation_pb2.OPERATION_STATE_UNSPECIFIED
        or not _is_resource(value.operation_id, "operations")
    ):
        raise ProtocolError(
            f"{label} returned invalid or cross-project operation state",
            status=grpc.StatusCode.DATA_LOSS,
        )
    return value


def _list_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: job_service_pb2.ListJobsRequest | None,
) -> job_service_pb2.ListJobsRequest:
    value = job_service_pb2.ListJobsRequest()
    if request is not None:
        value.CopyFrom(request)
    parent = invoker.config.project_parent
    if value.parent not in ("", parent):
        raise ValueError("job list parent conflicts with configured project")
    if value.page.page_size > _MAX_PAGE_SIZE:
        raise ValueError("job page size cannot exceed 200")
    if value.filter.strip() or value.order_by not in ("", "job_id"):
        raise ValueError("unsupported job filter or ordering")
    value.parent = parent
    return value


class Jobs(WithRawResponse):
    """Synchronous durable-job API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def request(
        self,
        command: job_commands_pb2.RequestJobCommand,
        *,
        options: CallOptions | None = None,
    ) -> tuple[job_pb2.Job, operation_pb2.Operation]:
        request, call = _prepare_command(self._invoker, command, options)
        response = cast(
            job_service_pb2.RequestJobResponse,
            self._invoker.unary(REQUEST_JOB, request, call=call, retry_safe=True),
        )
        job = _job(self._invoker, response, label="job request")
        operation = _operation(self._invoker, response, label="job request")
        if job.operation_id != operation.operation_id or operation.job_id != job.job_id:
            raise ProtocolError(
                "job request returned inconsistent durable identities",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return job, operation

    def get(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> job_pb2.Job:
        canonical = canonical_resource(self._invoker, name, "jobs")
        if len(if_none_match) > 512 or any(c in if_none_match for c in "\r\n\x00"):
            raise ValueError("job cache validator is invalid")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = self._invoker.unary(
            GET_JOB,
            job_service_pb2.GetJobRequest(name=canonical, if_none_match=if_none_match),
            call=call,
            retry_safe=True,
        )
        return _job(self._invoker, response, label="job get", expected_name=canonical)

    def list(
        self,
        request: job_service_pb2.ListJobsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[job_pb2.Job]:
        materialized = _list_request(self._invoker, request)
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        raw = self._invoker.unary(LIST_JOBS, materialized, call=call, retry_safe=True)
        if not isinstance(raw, job_service_pb2.ListJobsResponse):
            raise ProtocolError(
                "job list response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )
        response = copy.deepcopy(raw)
        for value in response.jobs:
            envelope = job_service_pb2.GetJobResponse(job=value)
            _job(self._invoker, envelope, label="job list")

        def follow(page_token: str) -> Page[job_pb2.Job]:
            return self.list(next_request(materialized, page_token), options=options, limits=limits)

        return sync_page(response, items_field="jobs", fetch=follow, limits=limits)

    def cancel(
        self,
        request: job_service_pb2.CancelJobRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized, call = _prepare_mutation(self._invoker, request, options)
        response = cast(
            job_service_pb2.CancelJobResponse,
            self._invoker.unary(CANCEL_JOB, materialized, call=call, retry_safe=True),
        )
        operation = _operation(self._invoker, response, label="job cancellation")
        if operation.job_id != materialized.name:
            raise ProtocolError(
                "job cancellation returned a different job identity",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return operation


class AsyncJobs(AsyncWithRawResponse):
    """Asyncio-native durable-job API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def request(
        self,
        command: job_commands_pb2.RequestJobCommand,
        *,
        options: CallOptions | None = None,
    ) -> tuple[job_pb2.Job, operation_pb2.Operation]:
        request, call = _prepare_command(self._invoker, command, options)
        response = cast(
            job_service_pb2.RequestJobResponse,
            await self._invoker.unary(REQUEST_JOB, request, call=call, retry_safe=True),
        )
        job = _job(self._invoker, response, label="job request")
        operation = _operation(self._invoker, response, label="job request")
        if job.operation_id != operation.operation_id or operation.job_id != job.job_id:
            raise ProtocolError(
                "job request returned inconsistent durable identities",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return job, operation

    async def get(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> job_pb2.Job:
        canonical = canonical_resource(self._invoker, name, "jobs")
        if len(if_none_match) > 512 or any(c in if_none_match for c in "\r\n\x00"):
            raise ValueError("job cache validator is invalid")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = await self._invoker.unary(
            GET_JOB,
            job_service_pb2.GetJobRequest(name=canonical, if_none_match=if_none_match),
            call=call,
            retry_safe=True,
        )
        return _job(self._invoker, response, label="job get", expected_name=canonical)

    async def list(
        self,
        request: job_service_pb2.ListJobsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[job_pb2.Job]:
        materialized = _list_request(self._invoker, request)
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        raw = await self._invoker.unary(LIST_JOBS, materialized, call=call, retry_safe=True)
        if not isinstance(raw, job_service_pb2.ListJobsResponse):
            raise ProtocolError(
                "job list response violated its generated contract",
                status=grpc.StatusCode.DATA_LOSS,
            )
        response = copy.deepcopy(raw)
        for value in response.jobs:
            envelope = job_service_pb2.GetJobResponse(job=value)
            _job(self._invoker, envelope, label="job list")

        async def follow(page_token: str) -> AsyncPage[job_pb2.Job]:
            return await self.list(
                next_request(materialized, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="jobs", fetch=follow, limits=limits)

    async def cancel(
        self,
        request: job_service_pb2.CancelJobRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized, call = _prepare_mutation(self._invoker, request, options)
        response = cast(
            job_service_pb2.CancelJobResponse,
            await self._invoker.unary(CANCEL_JOB, materialized, call=call, retry_safe=True),
        )
        operation = _operation(self._invoker, response, label="job cancellation")
        if operation.job_id != materialized.name:
            raise ProtocolError(
                "job cancellation returned a different job identity",
                status=grpc.StatusCode.DATA_LOSS,
            )
        return operation
