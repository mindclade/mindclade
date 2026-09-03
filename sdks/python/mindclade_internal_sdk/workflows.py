"""Private Workflow and Approval facades over generated protobuf/gRPC clients."""

from __future__ import annotations

import asyncio
import copy
import hmac
import re
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from google.protobuf.message import Message
from mindclade.common.v1 import resource_reference_pb2
from mindclade.internal.workflow.v1 import workflow_service_pb2
from mindclade.operation.v1 import operation_pb2
from mindclade.workflow.v1 import approval_pb2, workflow_definition_pb2, workflow_run_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._raw import AsyncWithRawResponse, WithRawResponse, streaming_method
from ._validation import required_response_message, required_text
from ._watch import AsyncWatchStream, WatchSpec, WatchStream, watch_budget
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import (
    CancelledError,
    ProtocolError,
    UnavailableError,
    WorkflowRunFailedError,
)
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
    CANCEL_WORKFLOW_RUN,
    COMMIT_WORKFLOW_TRANSITION,
    CONSUME_APPROVAL,
    CREATE_WORKFLOW_DEFINITION,
    DECIDE_APPROVAL,
    GET_APPROVAL_REQUEST,
    GET_WORKFLOW_DEFINITION,
    GET_WORKFLOW_RUN,
    LIST_APPROVAL_REQUESTS,
    LIST_WORKFLOW_DEFINITIONS,
    LIST_WORKFLOW_RUNS,
    REQUEST_APPROVAL,
    START_WORKFLOW_RUN,
    UPDATE_WORKFLOW_DEFINITION,
    WATCH_WORKFLOW_RUN,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_MAXIMUM_PAGE_SIZE = 200
_TERMINAL_STATES = frozenset(
    {
        workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED,
        workflow_run_pb2.WORKFLOW_RUN_STATE_FAILED,
        workflow_run_pb2.WORKFLOW_RUN_STATE_CANCELLED,
        workflow_run_pb2.WORKFLOW_RUN_STATE_EXPIRED,
    }
)

type _TopLevelMutation = (
    workflow_service_pb2.CreateWorkflowDefinitionRequest
    | workflow_service_pb2.UpdateWorkflowDefinitionRequest
    | workflow_service_pb2.StartWorkflowRunRequest
    | workflow_service_pb2.CancelWorkflowRunRequest
    | workflow_service_pb2.CommitWorkflowTransitionRequest
    | workflow_service_pb2.DecideApprovalRequest
    | workflow_service_pb2.ConsumeApprovalRequest
)


def _project(invoker: SyncInvoker | AsyncInvoker) -> str:
    return invoker.config.project_parent


def _scoped_name(invoker: SyncInvoker | AsyncInvoker, value: str, collection: str) -> str:
    name = required_text(f"{collection} name", value, maximum=2048)
    prefix = f"{_project(invoker)}/{collection}/"
    resource_id = name.removeprefix(prefix)
    if not name.startswith(prefix) or not resource_id or "/" in resource_id:
        raise ValueError(f"{collection} name must be scoped to the configured project")
    return name


def _parent(invoker: SyncInvoker | AsyncInvoker, value: str, label: str) -> str:
    expected = _project(invoker)
    if value and value != expected:
        raise ValueError(f"{label} parent must match the configured project")
    return expected


def _normalize_scope(
    invoker: SyncInvoker | AsyncInvoker,
    value: Any,
) -> None:
    config = invoker.config
    if value.tenant_id and value.tenant_id != config.tenant_id:
        raise ValueError("resource tenant does not match client scope")
    if value.project_id and value.project_id != config.project_id:
        raise ValueError("resource project does not match client scope")
    value.tenant_id = config.tenant_id
    value.project_id = config.project_id


def _normalize_reference(
    invoker: SyncInvoker | AsyncInvoker,
    value: resource_reference_pb2.ResourceRef,
    *,
    resource_type: str | None = None,
    collection: str | None = None,
) -> None:
    if collection is not None:
        name = _scoped_name(invoker, value.name, collection)
        resource_id = name.rsplit("/", 1)[-1]
        if value.resource_id and value.resource_id != resource_id:
            raise ValueError("resource reference id does not match its name")
        value.resource_id = resource_id
    else:
        required_text("resource reference name", value.name, maximum=2048)
        required_text("resource reference id", value.resource_id, maximum=256)
    if resource_type is not None:
        if value.resource_type and value.resource_type != resource_type:
            raise ValueError("resource reference type does not match the generated request")
        value.resource_type = resource_type
    else:
        required_text("resource reference type", value.resource_type, maximum=256)
    _normalize_scope(invoker, value)


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _prepare_mutation[RequestT: _TopLevelMutation](
    invoker: SyncInvoker | AsyncInvoker,
    request: RequestT,
    options: CallOptions | None,
    *,
    lease_token: str | None = None,
) -> tuple[RequestT, PreparedCall]:
    value = copy.deepcopy(request)
    dynamic = cast(Any, value)
    key = dynamic.context.idempotency_key if value.HasField("context") else ""
    value.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    if lease_token is not None:
        call = replace(call, lease_token=_lease_token(lease_token))
    dynamic.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(value))
    )
    return value, call


def _selected_lease_token(explicit: str | None, options: CallOptions | None) -> str:
    selected = explicit or (options.lease_token if options else None)
    if selected is None:
        raise ValueError("fenced workflow transition requires a lease token")
    if explicit is not None and options and options.lease_token and explicit != options.lease_token:
        raise ValueError("conflicting workflow lease tokens")
    return _lease_token(selected)


def _prepare_approval(
    invoker: SyncInvoker | AsyncInvoker,
    request: approval_pb2.ApprovalRequest,
    options: CallOptions | None,
) -> tuple[approval_pb2.ApprovalRequest, PreparedCall]:
    value = copy.deepcopy(request)
    key = value.context.idempotency_key if value.HasField("context") else ""
    value.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    value.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(value))
    )
    return value, call


def _lease_token(value: str) -> str:
    token = value.strip()
    if not token or len(token) > 4096 or any(character.isspace() for character in token):
        raise ValueError("lease token is invalid")
    return token


def _digest(value: str, label: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical SHA-256 digest")
    return value


def _operation(response: Message, label: str) -> operation_pb2.Operation:
    value = required_response_message(response, "operation", operation_pb2.Operation, label=label)
    required_text("operation id", value.operation_id)
    return value


def _verify_binding(binding: approval_pb2.ApprovalBinding) -> None:
    _digest(binding.intent_digest, "approval intent digest")
    _digest(binding.parameters_digest, "approval parameters digest")
    supplied = _digest(binding.binding_digest, "approval binding digest")
    value = copy.deepcopy(binding)
    value.binding_digest = ""
    if not hmac.compare_digest(supplied, canonical_digest(value)):
        raise ValueError("approval binding digest does not match the generated binding")


def _normalize_page(request: Message) -> None:
    dynamic = cast(Any, request)
    if request.HasField("page") and dynamic.page.page_size > _MAXIMUM_PAGE_SIZE:
        raise ValueError("workflow page size cannot exceed 200")


def _normalize_start(
    invoker: SyncInvoker | AsyncInvoker, request: workflow_service_pb2.StartWorkflowRunRequest
) -> None:
    request.parent = _parent(invoker, request.parent, "workflow run")
    required_text("workflow run id", request.workflow_run_id, maximum=128)
    if not request.HasField("workflow_run") or not request.workflow_run.HasField("definition"):
        raise ValueError("workflow start requires a generated run and definition")
    _normalize_reference(
        invoker,
        request.workflow_run.definition,
        resource_type="workflow_definition",
        collection="workflowDefinitions",
    )
    if request.workflow_run.HasField("agent_run"):
        _normalize_reference(
            invoker,
            request.workflow_run.agent_run,
            resource_type="agent_run",
            collection="agentRuns",
        )


def _normalize_fence(
    invoker: SyncInvoker | AsyncInvoker,
    request: workflow_service_pb2.CommitWorkflowTransitionRequest,
) -> None:
    if not request.HasField("workflow_run") or not request.HasField("fence"):
        raise ValueError("workflow transition requires a generated run and fence")
    _scoped_name(invoker, request.workflow_run.name, "workflowRuns")
    _normalize_scope(invoker, request.workflow_run)
    fence = request.fence
    for label, value in {
        "fence job id": fence.job_id,
        "fence run id": fence.run_id,
        "fence attempt id": fence.attempt_id,
    }.items():
        required_text(label, value, maximum=2048)
    if fence.lease_epoch == 0 or not fence.HasField("deadline"):
        raise ValueError("workflow fence requires a lease epoch and deadline")
    try:
        deadline = fence.deadline.ToDatetime(tzinfo=UTC)
    except ValueError as error:
        raise ValueError("workflow fence deadline is invalid") from error
    if deadline <= datetime.now(UTC):
        raise ValueError("workflow fence is expired")
    _digest(fence.lease_token_digest, "workflow fence lease token digest")
    _normalize_scope(invoker, fence)
    required_text("workflow transition ETag", request.etag, maximum=1024)


def _response_run(
    response: Message,
    *,
    label: str,
) -> workflow_run_pb2.WorkflowRun:
    return required_response_message(
        response, "workflow_run", workflow_run_pb2.WorkflowRun, label=label
    )


type WorkflowWatchSpec = WatchSpec[workflow_run_pb2.WorkflowRun, int]


def _workflow_watch_spec(run_name: str) -> WorkflowWatchSpec:
    """Describe the workflow-run watch to the shared resumable watcher."""

    def build(cursor: int, remaining: float) -> Message:
        del remaining
        return workflow_service_pb2.WatchWorkflowRunRequest(
            name=run_name,
            after_transition_sequence=cursor,
        )

    def accept(raw: Message, cursor: int) -> tuple[workflow_run_pb2.WorkflowRun, int, bool]:
        response = cast(workflow_service_pb2.WatchWorkflowRunResponse, raw)
        run = _response_run(response, label="workflow watch")
        if run.name != run_name or run.transition_sequence != cursor + 1:
            raise ProtocolError(
                "workflow watch returned an invalid identity or non-contiguous sequence"
            )
        return run, run.transition_sequence, run.state in _TERMINAL_STATES

    return WatchSpec(
        method=WATCH_WORKFLOW_RUN,
        build_request=build,
        accept=accept,
        # The watcher surfaces this only after the retry budget is spent, and
        # surfaces the real transport failure instead when there was one. The
        # previous loop discarded that cause and always reported a protocol
        # violation, which sent operators looking in the wrong place.
        closed_error=lambda: UnavailableError(
            "workflow watch ended before terminal durable state",
            retryable=True,
        ),
        timeout_error=lambda: TimeoutError("workflow watch deadline expired"),
        cancelled_error=lambda: CancelledError("workflow watch was cancelled"),
    )


class Workflows(WithRawResponse):
    """Synchronous generated-type-only Workflow API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def create_definition(
        self,
        request: workflow_service_pb2.CreateWorkflowDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        value.parent = _parent(self._invoker, value.parent, "workflow definition")
        required_text("workflow definition id", value.workflow_definition_id, maximum=128)
        if not value.HasField("workflow_definition"):
            raise ValueError("workflow create requires a generated definition")
        for reference in value.workflow_definition.eligible_tools:
            _normalize_reference(self._invoker, reference)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            self._invoker.unary(CREATE_WORKFLOW_DEFINITION, value, call=call, retry_safe=True),
            "workflow definition create",
        )

    def update_definition(
        self,
        request: workflow_service_pb2.UpdateWorkflowDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        if not value.HasField("workflow_definition") or not value.HasField("update_mask"):
            raise ValueError("workflow update requires a generated definition and field mask")
        _scoped_name(self._invoker, value.workflow_definition.name, "workflowDefinitions")
        _normalize_scope(self._invoker, value.workflow_definition)
        if not value.update_mask.paths:
            raise ValueError("workflow update field mask cannot be empty")
        required_text("workflow definition ETag", value.etag, maximum=1024)
        for reference in value.workflow_definition.eligible_tools:
            _normalize_reference(self._invoker, reference)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            self._invoker.unary(UPDATE_WORKFLOW_DEFINITION, value, call=call, retry_safe=True),
            "workflow definition update",
        )

    def get_definition(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> workflow_definition_pb2.WorkflowDefinition:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.GetWorkflowDefinitionResponse,
            self._invoker.unary(
                GET_WORKFLOW_DEFINITION,
                workflow_service_pb2.GetWorkflowDefinitionRequest(
                    name=_scoped_name(self._invoker, name, "workflowDefinitions"),
                    if_none_match=if_none_match.strip(),
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "workflow_definition",
            workflow_definition_pb2.WorkflowDefinition,
            label="workflow definition get",
        )

    def list_definitions(
        self,
        request: workflow_service_pb2.ListWorkflowDefinitionsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[workflow_definition_pb2.WorkflowDefinition]:
        value = (
            copy.deepcopy(request)
            if request
            else workflow_service_pb2.ListWorkflowDefinitionsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "workflow definition list")
        _normalize_page(value)
        apply_default_page_size(value, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.ListWorkflowDefinitionsResponse,
            self._invoker.unary(LIST_WORKFLOW_DEFINITIONS, value, call=call, retry_safe=True),
        )

        def follow(page_token: str) -> Page[workflow_definition_pb2.WorkflowDefinition]:
            return self.list_definitions(
                next_request(value, page_token), options=options, limits=limits
            )

        return sync_page(response, items_field="workflow_definitions", fetch=follow, limits=limits)

    def start_run(
        self,
        request: workflow_service_pb2.StartWorkflowRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        _normalize_start(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            self._invoker.unary(START_WORKFLOW_RUN, value, call=call, retry_safe=True),
            "workflow run start",
        )

    def get_run(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> workflow_run_pb2.WorkflowRun:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.GetWorkflowRunResponse,
            self._invoker.unary(
                GET_WORKFLOW_RUN,
                workflow_service_pb2.GetWorkflowRunRequest(
                    name=_scoped_name(self._invoker, name, "workflowRuns"),
                    if_none_match=if_none_match.strip(),
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return _response_run(response, label="workflow run get")

    def list_runs(
        self,
        request: workflow_service_pb2.ListWorkflowRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[workflow_run_pb2.WorkflowRun]:
        value = (
            copy.deepcopy(request) if request else workflow_service_pb2.ListWorkflowRunsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "workflow run list")
        _normalize_page(value)
        apply_default_page_size(value, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.ListWorkflowRunsResponse,
            self._invoker.unary(LIST_WORKFLOW_RUNS, value, call=call, retry_safe=True),
        )

        def follow(page_token: str) -> Page[workflow_run_pb2.WorkflowRun]:
            return self.list_runs(next_request(value, page_token), options=options, limits=limits)

        return sync_page(response, items_field="workflow_runs", fetch=follow, limits=limits)

    def cancel_run(
        self,
        request: workflow_service_pb2.CancelWorkflowRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.name, "workflowRuns")
        required_text("workflow run ETag", value.etag, maximum=1024)
        required_text("workflow cancellation reason", value.reason, maximum=1024)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            self._invoker.unary(CANCEL_WORKFLOW_RUN, value, call=call, retry_safe=True),
            "workflow cancellation",
        )

    def commit_transition(
        self,
        request: workflow_service_pb2.CommitWorkflowTransitionRequest,
        *,
        lease_token: str | None = None,
        options: CallOptions | None = None,
    ) -> workflow_run_pb2.WorkflowRun:
        value = copy.deepcopy(request)
        _normalize_fence(self._invoker, value)
        expected_name = value.workflow_run.name
        expected_sequence = value.expected_transition_sequence + 1
        value, call = _prepare_mutation(
            self._invoker,
            value,
            options,
            lease_token=_selected_lease_token(lease_token, options),
        )
        response = cast(
            workflow_service_pb2.CommitWorkflowTransitionResponse,
            self._invoker.unary(COMMIT_WORKFLOW_TRANSITION, value, call=call, retry_safe=True),
        )
        run = _response_run(response, label="workflow transition")
        if run.name != expected_name or run.transition_sequence != expected_sequence:
            raise ProtocolError("workflow transition returned inconsistent durable state")
        return run

    @streaming_method
    def watch(
        self,
        name: str,
        *,
        after_transition_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: threading.Event | None = None,
        options: CallOptions | None = None,
    ) -> WatchStream[workflow_run_pb2.WorkflowRun, int]:
        """Follow one workflow run's transitions, reconnecting inside the deadline."""

        run_name = _scoped_name(self._invoker, name, "workflowRuns")
        if after_transition_sequence < 0:
            raise ValueError("workflow watch cursor cannot be negative")
        if cancellation is not None and cancellation.is_set():
            raise CancelledError("workflow watch was cancelled")
        base, total = watch_budget(timeout, options)
        return WatchStream(
            self._invoker,
            _workflow_watch_spec(run_name),
            cursor=after_transition_sequence,
            call=base,
            total=total,
            cancellation=cancellation,
        )

    def wait(
        self,
        name: str,
        *,
        after_transition_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: threading.Event | None = None,
        options: CallOptions | None = None,
    ) -> workflow_run_pb2.WorkflowRun:
        for run in self.watch(
            name,
            after_transition_sequence=after_transition_sequence,
            timeout=timeout,
            cancellation=cancellation,
            options=options,
        ):
            if run.state not in _TERMINAL_STATES:
                continue
            if run.state != workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED:
                raise WorkflowRunFailedError(run)
            return run
        raise ProtocolError("workflow watch ended before terminal durable state")


class AsyncWorkflows(AsyncWithRawResponse):
    """Asyncio generated-type-only Workflow API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def create_definition(
        self,
        request: workflow_service_pb2.CreateWorkflowDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        value.parent = _parent(self._invoker, value.parent, "workflow definition")
        required_text("workflow definition id", value.workflow_definition_id, maximum=128)
        if not value.HasField("workflow_definition"):
            raise ValueError("workflow create requires a generated definition")
        for reference in value.workflow_definition.eligible_tools:
            _normalize_reference(self._invoker, reference)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            await self._invoker.unary(
                CREATE_WORKFLOW_DEFINITION, value, call=call, retry_safe=True
            ),
            "workflow definition create",
        )

    async def update_definition(
        self,
        request: workflow_service_pb2.UpdateWorkflowDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        if not value.HasField("workflow_definition") or not value.HasField("update_mask"):
            raise ValueError("workflow update requires a generated definition and field mask")
        _scoped_name(self._invoker, value.workflow_definition.name, "workflowDefinitions")
        _normalize_scope(self._invoker, value.workflow_definition)
        if not value.update_mask.paths:
            raise ValueError("workflow update field mask cannot be empty")
        required_text("workflow definition ETag", value.etag, maximum=1024)
        for reference in value.workflow_definition.eligible_tools:
            _normalize_reference(self._invoker, reference)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            await self._invoker.unary(
                UPDATE_WORKFLOW_DEFINITION, value, call=call, retry_safe=True
            ),
            "workflow definition update",
        )

    async def get_definition(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> workflow_definition_pb2.WorkflowDefinition:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.GetWorkflowDefinitionResponse,
            await self._invoker.unary(
                GET_WORKFLOW_DEFINITION,
                workflow_service_pb2.GetWorkflowDefinitionRequest(
                    name=_scoped_name(self._invoker, name, "workflowDefinitions"),
                    if_none_match=if_none_match.strip(),
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "workflow_definition",
            workflow_definition_pb2.WorkflowDefinition,
            label="workflow definition get",
        )

    async def list_definitions(
        self,
        request: workflow_service_pb2.ListWorkflowDefinitionsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[workflow_definition_pb2.WorkflowDefinition]:
        value = (
            copy.deepcopy(request)
            if request
            else workflow_service_pb2.ListWorkflowDefinitionsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "workflow definition list")
        _normalize_page(value)
        apply_default_page_size(value, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.ListWorkflowDefinitionsResponse,
            await self._invoker.unary(LIST_WORKFLOW_DEFINITIONS, value, call=call, retry_safe=True),
        )

        async def follow(page_token: str) -> AsyncPage[workflow_definition_pb2.WorkflowDefinition]:
            return await self.list_definitions(
                next_request(value, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="workflow_definitions", fetch=follow, limits=limits)

    async def start_run(
        self,
        request: workflow_service_pb2.StartWorkflowRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        _normalize_start(self._invoker, value)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            await self._invoker.unary(START_WORKFLOW_RUN, value, call=call, retry_safe=True),
            "workflow run start",
        )

    async def get_run(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> workflow_run_pb2.WorkflowRun:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.GetWorkflowRunResponse,
            await self._invoker.unary(
                GET_WORKFLOW_RUN,
                workflow_service_pb2.GetWorkflowRunRequest(
                    name=_scoped_name(self._invoker, name, "workflowRuns"),
                    if_none_match=if_none_match.strip(),
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return _response_run(response, label="workflow run get")

    async def list_runs(
        self,
        request: workflow_service_pb2.ListWorkflowRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[workflow_run_pb2.WorkflowRun]:
        value = (
            copy.deepcopy(request) if request else workflow_service_pb2.ListWorkflowRunsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "workflow run list")
        _normalize_page(value)
        apply_default_page_size(value, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.ListWorkflowRunsResponse,
            await self._invoker.unary(LIST_WORKFLOW_RUNS, value, call=call, retry_safe=True),
        )

        async def follow(page_token: str) -> AsyncPage[workflow_run_pb2.WorkflowRun]:
            return await self.list_runs(
                next_request(value, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="workflow_runs", fetch=follow, limits=limits)

    async def cancel_run(
        self,
        request: workflow_service_pb2.CancelWorkflowRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.name, "workflowRuns")
        required_text("workflow run ETag", value.etag, maximum=1024)
        required_text("workflow cancellation reason", value.reason, maximum=1024)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            await self._invoker.unary(CANCEL_WORKFLOW_RUN, value, call=call, retry_safe=True),
            "workflow cancellation",
        )

    async def commit_transition(
        self,
        request: workflow_service_pb2.CommitWorkflowTransitionRequest,
        *,
        lease_token: str | None = None,
        options: CallOptions | None = None,
    ) -> workflow_run_pb2.WorkflowRun:
        value = copy.deepcopy(request)
        _normalize_fence(self._invoker, value)
        expected_name = value.workflow_run.name
        expected_sequence = value.expected_transition_sequence + 1
        value, call = _prepare_mutation(
            self._invoker,
            value,
            options,
            lease_token=_selected_lease_token(lease_token, options),
        )
        response = cast(
            workflow_service_pb2.CommitWorkflowTransitionResponse,
            await self._invoker.unary(
                COMMIT_WORKFLOW_TRANSITION, value, call=call, retry_safe=True
            ),
        )
        run = _response_run(response, label="workflow transition")
        if run.name != expected_name or run.transition_sequence != expected_sequence:
            raise ProtocolError("workflow transition returned inconsistent durable state")
        return run

    @streaming_method
    def watch(
        self,
        name: str,
        *,
        after_transition_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: asyncio.Event | None = None,
        options: CallOptions | None = None,
    ) -> AsyncWatchStream[workflow_run_pb2.WorkflowRun, int]:
        """Follow one workflow run's transitions, reconnecting inside the deadline."""

        run_name = _scoped_name(self._invoker, name, "workflowRuns")
        if after_transition_sequence < 0:
            raise ValueError("workflow watch cursor cannot be negative")
        if cancellation is not None and cancellation.is_set():
            raise CancelledError("workflow watch was cancelled")
        base, total = watch_budget(timeout, options)
        return AsyncWatchStream(
            self._invoker,
            _workflow_watch_spec(run_name),
            cursor=after_transition_sequence,
            call=base,
            total=total,
            cancellation=cancellation,
        )

    async def wait(
        self,
        name: str,
        *,
        after_transition_sequence: int = 0,
        timeout: float = 300.0,
        cancellation: asyncio.Event | None = None,
        options: CallOptions | None = None,
    ) -> workflow_run_pb2.WorkflowRun:
        async for run in self.watch(
            name,
            after_transition_sequence=after_transition_sequence,
            timeout=timeout,
            cancellation=cancellation,
            options=options,
        ):
            if run.state not in _TERMINAL_STATES:
                continue
            if run.state != workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED:
                raise WorkflowRunFailedError(run)
            return run
        raise ProtocolError("workflow watch ended before terminal durable state")


def _validate_receipt_digest(receipt: approval_pb2.ApprovalReceipt) -> None:
    _digest(receipt.receipt_digest, "approval receipt digest")
    if not receipt.HasField("binding"):
        raise ProtocolError("approval receipt omitted its binding")


class Approvals(WithRawResponse):
    """Synchronous generated-type-only exact-intent Approval API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def request(
        self,
        request: approval_pb2.ApprovalRequest,
        *,
        options: CallOptions | None = None,
    ) -> approval_pb2.ApprovalRequest:
        value = copy.deepcopy(request)
        if not value.HasField("binding"):
            raise ValueError("approval request requires a generated binding")
        value.requested_by_principal_ref = self._invoker.config.principal_id
        if value.binding.HasField("tool"):
            _normalize_reference(self._invoker, value.binding.tool)
        for decision in value.policy_decisions:
            if decision.HasField("resource"):
                _normalize_reference(self._invoker, decision.resource)
        _verify_binding(value.binding)
        value, call = _prepare_approval(self._invoker, value, options)
        response = cast(
            workflow_service_pb2.RequestApprovalResponse,
            self._invoker.unary(
                REQUEST_APPROVAL,
                workflow_service_pb2.RequestApprovalRequest(approval_request=value),
                call=call,
                retry_safe=True,
            ),
        )
        created = required_response_message(
            response,
            "approval_request",
            approval_pb2.ApprovalRequest,
            label="approval request",
        )
        _scoped_name(self._invoker, created.name, "approvalRequests")
        if not created.HasField("binding") or not hmac.compare_digest(
            created.binding.binding_digest, value.binding.binding_digest
        ):
            raise ProtocolError("approval service returned inconsistent durable intent")
        return created

    def get(self, name: str, *, options: CallOptions | None = None) -> approval_pb2.ApprovalRequest:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.GetApprovalRequestResponse,
            self._invoker.unary(
                GET_APPROVAL_REQUEST,
                workflow_service_pb2.GetApprovalRequestRequest(
                    name=_scoped_name(self._invoker, name, "approvalRequests")
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "approval_request",
            approval_pb2.ApprovalRequest,
            label="approval get",
        )

    def list(
        self,
        request: workflow_service_pb2.ListApprovalRequestsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[approval_pb2.ApprovalRequest]:
        value = (
            copy.deepcopy(request)
            if request
            else workflow_service_pb2.ListApprovalRequestsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "approval list")
        _normalize_page(value)
        apply_default_page_size(value, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.ListApprovalRequestsResponse,
            self._invoker.unary(LIST_APPROVAL_REQUESTS, value, call=call, retry_safe=True),
        )

        def follow(page_token: str) -> Page[approval_pb2.ApprovalRequest]:
            return self.list(next_request(value, page_token), options=options, limits=limits)

        return sync_page(response, items_field="approval_requests", fetch=follow, limits=limits)

    def decide(
        self,
        request: workflow_service_pb2.DecideApprovalRequest,
        *,
        options: CallOptions | None = None,
    ) -> approval_pb2.ApprovalReceipt:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.name, "approvalRequests")
        required_text("approval ETag", value.etag, maximum=1024)
        if value.decision == approval_pb2.APPROVAL_DECISION_VALUE_UNSPECIFIED:
            raise ValueError("approval decision is required")
        required_text("approval reason code", value.reason_code, maximum=1024)
        if len(value.safe_reason) > 2048:
            raise ValueError("approval safe reason is too long")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = cast(
            workflow_service_pb2.DecideApprovalResponse,
            self._invoker.unary(DECIDE_APPROVAL, value, call=call, retry_safe=True),
        )
        receipt = required_response_message(
            response,
            "approval_receipt",
            approval_pb2.ApprovalReceipt,
            label="approval decision",
        )
        _validate_receipt_digest(receipt)
        _scoped_name(self._invoker, receipt.name, "approvalReceipts")
        if (
            not receipt.HasField("request")
            or receipt.request.name != value.name
            or receipt.decision != value.decision
            or receipt.reason_code != value.reason_code
            or receipt.safe_reason != value.safe_reason
            or not receipt.HasField("decided_at")
        ):
            raise ProtocolError("approval decision returned an inconsistent receipt")
        _normalize_reference(self._invoker, receipt.request)
        return receipt

    def consume(
        self,
        request: workflow_service_pb2.ConsumeApprovalRequest,
        *,
        options: CallOptions | None = None,
    ) -> approval_pb2.ApprovalReceipt:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.receipt_name, "approvalReceipts")
        _digest(value.binding_digest, "approval consumption binding digest")
        required_text("approval consumption call id", value.call_id, maximum=1024)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = cast(
            workflow_service_pb2.ConsumeApprovalResponse,
            self._invoker.unary(CONSUME_APPROVAL, value, call=call, retry_safe=True),
        )
        receipt = required_response_message(
            response,
            "approval_receipt",
            approval_pb2.ApprovalReceipt,
            label="approval consumption",
        )
        _validate_receipt_digest(receipt)
        if (
            receipt.name != value.receipt_name
            or receipt.binding.binding_digest != value.binding_digest
            or not receipt.HasField("consumed_at")
            or receipt.consumed_by_call_id != value.call_id
        ):
            raise ProtocolError("approval consumption returned an inconsistent receipt")
        return receipt


class AsyncApprovals(AsyncWithRawResponse):
    """Asyncio generated-type-only exact-intent Approval API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def request(
        self,
        request: approval_pb2.ApprovalRequest,
        *,
        options: CallOptions | None = None,
    ) -> approval_pb2.ApprovalRequest:
        value = copy.deepcopy(request)
        if not value.HasField("binding"):
            raise ValueError("approval request requires a generated binding")
        value.requested_by_principal_ref = self._invoker.config.principal_id
        if value.binding.HasField("tool"):
            _normalize_reference(self._invoker, value.binding.tool)
        for decision in value.policy_decisions:
            if decision.HasField("resource"):
                _normalize_reference(self._invoker, decision.resource)
        _verify_binding(value.binding)
        value, call = _prepare_approval(self._invoker, value, options)
        response = cast(
            workflow_service_pb2.RequestApprovalResponse,
            await self._invoker.unary(
                REQUEST_APPROVAL,
                workflow_service_pb2.RequestApprovalRequest(approval_request=value),
                call=call,
                retry_safe=True,
            ),
        )
        created = required_response_message(
            response,
            "approval_request",
            approval_pb2.ApprovalRequest,
            label="approval request",
        )
        _scoped_name(self._invoker, created.name, "approvalRequests")
        if not created.HasField("binding") or not hmac.compare_digest(
            created.binding.binding_digest, value.binding.binding_digest
        ):
            raise ProtocolError("approval service returned inconsistent durable intent")
        return created

    async def get(
        self, name: str, *, options: CallOptions | None = None
    ) -> approval_pb2.ApprovalRequest:
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.GetApprovalRequestResponse,
            await self._invoker.unary(
                GET_APPROVAL_REQUEST,
                workflow_service_pb2.GetApprovalRequestRequest(
                    name=_scoped_name(self._invoker, name, "approvalRequests")
                ),
                call=call,
                retry_safe=True,
            ),
        )
        return required_response_message(
            response,
            "approval_request",
            approval_pb2.ApprovalRequest,
            label="approval get",
        )

    async def list(
        self,
        request: workflow_service_pb2.ListApprovalRequestsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[approval_pb2.ApprovalRequest]:
        value = (
            copy.deepcopy(request)
            if request
            else workflow_service_pb2.ListApprovalRequestsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "approval list")
        _normalize_page(value)
        apply_default_page_size(value, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            workflow_service_pb2.ListApprovalRequestsResponse,
            await self._invoker.unary(LIST_APPROVAL_REQUESTS, value, call=call, retry_safe=True),
        )

        async def follow(page_token: str) -> AsyncPage[approval_pb2.ApprovalRequest]:
            return await self.list(next_request(value, page_token), options=options, limits=limits)

        return async_page(response, items_field="approval_requests", fetch=follow, limits=limits)

    async def decide(
        self,
        request: workflow_service_pb2.DecideApprovalRequest,
        *,
        options: CallOptions | None = None,
    ) -> approval_pb2.ApprovalReceipt:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.name, "approvalRequests")
        required_text("approval ETag", value.etag, maximum=1024)
        if value.decision == approval_pb2.APPROVAL_DECISION_VALUE_UNSPECIFIED:
            raise ValueError("approval decision is required")
        required_text("approval reason code", value.reason_code, maximum=1024)
        if len(value.safe_reason) > 2048:
            raise ValueError("approval safe reason is too long")
        value, call = _prepare_mutation(self._invoker, value, options)
        response = cast(
            workflow_service_pb2.DecideApprovalResponse,
            await self._invoker.unary(DECIDE_APPROVAL, value, call=call, retry_safe=True),
        )
        receipt = required_response_message(
            response,
            "approval_receipt",
            approval_pb2.ApprovalReceipt,
            label="approval decision",
        )
        _validate_receipt_digest(receipt)
        _scoped_name(self._invoker, receipt.name, "approvalReceipts")
        if (
            not receipt.HasField("request")
            or receipt.request.name != value.name
            or receipt.decision != value.decision
            or receipt.reason_code != value.reason_code
            or receipt.safe_reason != value.safe_reason
            or not receipt.HasField("decided_at")
        ):
            raise ProtocolError("approval decision returned an inconsistent receipt")
        _normalize_reference(self._invoker, receipt.request)
        return receipt

    async def consume(
        self,
        request: workflow_service_pb2.ConsumeApprovalRequest,
        *,
        options: CallOptions | None = None,
    ) -> approval_pb2.ApprovalReceipt:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.receipt_name, "approvalReceipts")
        _digest(value.binding_digest, "approval consumption binding digest")
        required_text("approval consumption call id", value.call_id, maximum=1024)
        value, call = _prepare_mutation(self._invoker, value, options)
        response = cast(
            workflow_service_pb2.ConsumeApprovalResponse,
            await self._invoker.unary(CONSUME_APPROVAL, value, call=call, retry_safe=True),
        )
        receipt = required_response_message(
            response,
            "approval_receipt",
            approval_pb2.ApprovalReceipt,
            label="approval consumption",
        )
        _validate_receipt_digest(receipt)
        if (
            receipt.name != value.receipt_name
            or receipt.binding.binding_digest != value.binding_digest
            or not receipt.HasField("consumed_at")
            or receipt.consumed_by_call_id != value.call_id
        ):
            raise ProtocolError("approval consumption returned an inconsistent receipt")
        return receipt
