"""Private AgentService facade over authoritative generated protobuf values."""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from google.protobuf.message import Message
from mindclade.agent.v1 import (
    agent_definition_pb2,
    agent_run_pb2,
    agent_step_pb2,
    tool_receipt_pb2,
)
from mindclade.common.v1 import resource_reference_pb2
from mindclade.internal.agent.v1 import agent_service_pb2
from mindclade.job.v1 import operation_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._validation import required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import ProtocolError

CREATE_AGENT_DEFINITION = "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition"
UPDATE_AGENT_DEFINITION = "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition"
GET_AGENT_DEFINITION = "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition"
LIST_AGENT_DEFINITIONS = "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions"
START_AGENT_RUN = "/mindclade.internal.agent.v1.AgentService/StartAgentRun"
GET_AGENT_RUN = "/mindclade.internal.agent.v1.AgentService/GetAgentRun"
LIST_AGENT_RUNS = "/mindclade.internal.agent.v1.AgentService/ListAgentRuns"
CANCEL_AGENT_RUN = "/mindclade.internal.agent.v1.AgentService/CancelAgentRun"
GET_AGENT_STEP = "/mindclade.internal.agent.v1.AgentService/GetAgentStep"
LIST_AGENT_STEPS = "/mindclade.internal.agent.v1.AgentService/ListAgentSteps"
COMMIT_AGENT_STEP = "/mindclade.internal.agent.v1.AgentService/CommitAgentStep"
COMMIT_TOOL_RECEIPT = "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt"

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAXIMUM_PAGE_SIZE = 200

type _Mutation = (
    agent_service_pb2.CreateAgentDefinitionRequest
    | agent_service_pb2.UpdateAgentDefinitionRequest
    | agent_service_pb2.StartAgentRunRequest
    | agent_service_pb2.CancelAgentRunRequest
    | agent_service_pb2.CommitAgentStepRequest
    | agent_service_pb2.CommitToolReceiptRequest
)


def _project(invoker: SyncInvoker | AsyncInvoker) -> str:
    return invoker.config.project_parent


def _parent(invoker: SyncInvoker | AsyncInvoker, value: str, label: str) -> str:
    expected = _project(invoker)
    if value and value != expected:
        raise ValueError(f"{label} parent must match the configured project")
    return expected


def _scoped_name(invoker: SyncInvoker | AsyncInvoker, value: str, collection: str) -> str:
    name = required_text(f"{collection} name", value, maximum=2048)
    prefix = f"{_project(invoker)}/{collection}/"
    suffix = name.removeprefix(prefix)
    if not name.startswith(prefix) or not suffix or "/" in suffix:
        raise ValueError(f"{collection} name must be scoped to the configured project")
    return name


def _step_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    name = required_text("agent step name", value, maximum=2048)
    prefix = f"{_project(invoker)}/agentRuns/"
    suffix = name.removeprefix(prefix)
    parts = suffix.split("/agentSteps/")
    if (
        not name.startswith(prefix)
        or len(parts) != 2
        or not all(parts)
        or any("/" in part for part in parts)
    ):
        raise ValueError("agent step name must be scoped to a configured-project run")
    return name


def _normalize_scope(
    invoker: SyncInvoker | AsyncInvoker,
    value: Any,
) -> None:
    config = invoker.config
    if value.tenant_id and value.tenant_id != config.tenant_id:
        raise ValueError("resource tenant conflicts with client identity")
    if value.project_id and value.project_id != config.project_id:
        raise ValueError("resource project conflicts with client identity")
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
            raise ValueError("resource reference ID conflicts with its name")
        value.resource_id = resource_id
    else:
        required_text("resource reference name", value.name, maximum=2048)
        required_text("resource reference ID", value.resource_id, maximum=256)
    if resource_type is not None:
        if value.resource_type and value.resource_type != resource_type:
            raise ValueError("resource reference type conflicts with generated semantics")
        value.resource_type = resource_type
    else:
        required_text("resource reference type", value.resource_type, maximum=256)
    _normalize_scope(invoker, value)


def _normalize_definition(
    invoker: SyncInvoker | AsyncInvoker,
    value: agent_definition_pb2.AgentDefinition,
    *,
    creating: bool,
) -> None:
    if creating and (
        value.name
        or value.uid
        or value.revision
        or value.etag
        or value.tenant_id
        or value.project_id
        or value.HasField("create_time")
        or value.HasField("update_time")
        or value.HasField("delete_time")
    ):
        raise ValueError("server-managed agent definition fields must be unset")
    if not creating:
        _scoped_name(invoker, value.name, "agentDefinitions")
        _normalize_scope(invoker, value)
    if not value.HasField("workflow_definition"):
        raise ValueError("agent definition requires a workflow definition")
    _normalize_reference(
        invoker,
        value.workflow_definition,
        resource_type="workflow_definition",
        collection="workflowDefinitions",
    )
    if not value.HasField("evaluation_suite"):
        raise ValueError("agent definition requires an evaluation suite")
    _normalize_reference(invoker, value.evaluation_suite)
    if not value.eligible_tools:
        raise ValueError("agent definition requires at least one allowlisted tool")
    for tool in value.eligible_tools:
        _normalize_reference(invoker, tool)


def _normalize_page(request: Message) -> None:
    dynamic = cast(Any, request)
    if request.HasField("page") and dynamic.page.page_size > _MAXIMUM_PAGE_SIZE:
        raise ValueError("agent page size cannot exceed 200")


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _lease_token(explicit: str | None, options: CallOptions | None) -> str:
    option_token = options.lease_token if options else None
    if explicit is not None and option_token is not None and explicit != option_token:
        raise ValueError("conflicting agent lease tokens")
    selected = explicit or option_token
    if selected is None:
        raise ValueError("fenced agent commit requires a raw lease token")
    token = selected.strip()
    if not token or len(token) > 4096 or any(character.isspace() for character in token):
        raise ValueError("agent lease token is invalid")
    return token


def _prepare_mutation[RequestT: _Mutation](
    invoker: SyncInvoker | AsyncInvoker,
    request: RequestT,
    options: CallOptions | None,
    *,
    lease_token: str | None = None,
) -> tuple[RequestT, PreparedCall]:
    value = copy.deepcopy(request)
    key = value.context.idempotency_key if value.HasField("context") else ""
    value.ClearField("context")
    call = prepare_call(
        _mutation_options(key, options),
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    if lease_token is not None:
        call = replace(call, lease_token=lease_token)
    value.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(value))
    )
    return value, call


def _normalize_fence(
    invoker: SyncInvoker | AsyncInvoker,
    fence: Any,
) -> None:
    for label, item in {
        "agent fence job ID": fence.job_id,
        "agent fence run ID": fence.run_id,
        "agent fence attempt ID": fence.attempt_id,
    }.items():
        required_text(label, item, maximum=2048)
    if fence.lease_epoch <= 0 or not fence.HasField("deadline"):
        raise ValueError("agent fence requires an epoch and deadline")
    try:
        deadline = fence.deadline.ToDatetime(tzinfo=UTC)
    except ValueError as error:
        raise ValueError("agent fence deadline is invalid") from error
    if deadline <= datetime.now(UTC):
        raise ValueError("agent fence is expired")
    if _DIGEST.fullmatch(fence.lease_token_digest) is None:
        raise ValueError("agent fence lease-token digest must be canonical SHA-256")
    _normalize_scope(invoker, fence)


def _operation(response: Message, label: str) -> operation_pb2.Operation:
    value = required_response_message(response, "operation", operation_pb2.Operation, label=label)
    required_text("operation ID", value.operation_id, maximum=2048)
    return value


def _definition(response: Message, expected_name: str) -> agent_definition_pb2.AgentDefinition:
    value = required_response_message(
        response,
        "agent_definition",
        agent_definition_pb2.AgentDefinition,
        label="agent definition get",
    )
    if value.name != expected_name:
        raise ProtocolError("agent definition response changed resource identity")
    return value


def _run(response: Message, expected_name: str) -> agent_run_pb2.AgentRun:
    value = required_response_message(
        response, "agent_run", agent_run_pb2.AgentRun, label="agent run"
    )
    if value.name != expected_name:
        raise ProtocolError("agent run response changed resource identity")
    return value


def _step(response: Message, expected_name: str) -> agent_step_pb2.AgentStep:
    value = required_response_message(
        response, "agent_step", agent_step_pb2.AgentStep, label="agent step"
    )
    if value.name != expected_name:
        raise ProtocolError("agent step response changed resource identity")
    return value


def _create_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: agent_service_pb2.CreateAgentDefinitionRequest,
) -> agent_service_pb2.CreateAgentDefinitionRequest:
    value = copy.deepcopy(request)
    value.parent = _parent(invoker, value.parent, "agent definition")
    required_text("agent definition ID", value.agent_definition_id, maximum=128)
    if not value.HasField("agent_definition"):
        raise ValueError("agent definition create requires a generated definition")
    _normalize_definition(invoker, value.agent_definition, creating=True)
    return value


def _update_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: agent_service_pb2.UpdateAgentDefinitionRequest,
) -> agent_service_pb2.UpdateAgentDefinitionRequest:
    value = copy.deepcopy(request)
    if not value.HasField("agent_definition") or not value.HasField("update_mask"):
        raise ValueError("agent definition update requires a definition and field mask")
    if not value.update_mask.paths or len(value.update_mask.paths) > 32:
        raise ValueError("agent definition field mask must contain at most 32 paths")
    required_text("agent definition ETag", value.etag, maximum=1024)
    _normalize_definition(invoker, value.agent_definition, creating=False)
    return value


def _start_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: agent_service_pb2.StartAgentRunRequest,
) -> agent_service_pb2.StartAgentRunRequest:
    value = copy.deepcopy(request)
    value.parent = _parent(invoker, value.parent, "agent run")
    required_text("agent run ID", value.agent_run_id, maximum=128)
    if not value.HasField("agent_run") or not value.agent_run.HasField("definition"):
        raise ValueError("agent run start requires generated intent and definition")
    _normalize_reference(
        invoker,
        value.agent_run.definition,
        resource_type="agent_definition",
        collection="agentDefinitions",
    )
    if value.agent_run.HasField("workflow_run"):
        _normalize_reference(
            invoker,
            value.agent_run.workflow_run,
            resource_type="workflow_run",
            collection="workflowRuns",
        )
    if not value.agent_run.HasField("budget_reservation"):
        raise ValueError("agent run start requires a budget reservation")
    _normalize_reference(invoker, value.agent_run.budget_reservation)
    return value


def _commit_step_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: agent_service_pb2.CommitAgentStepRequest,
) -> agent_service_pb2.CommitAgentStepRequest:
    value = copy.deepcopy(request)
    if not value.HasField("agent_step") or not value.HasField("fence"):
        raise ValueError("agent step commit requires a generated step and fence")
    required_text("agent run ETag", value.run_etag, maximum=1024)
    if value.expected_next_step_sequence <= 0 or (
        value.agent_step.sequence != value.expected_next_step_sequence
    ):
        raise ValueError("agent step sequence must equal the expected next sequence")
    if not value.agent_step.HasField("run"):
        raise ValueError("agent step requires a run reference")
    _normalize_reference(
        invoker,
        value.agent_step.run,
        resource_type="agent_run",
        collection="agentRuns",
    )
    _normalize_fence(invoker, value.fence)
    return value


def _commit_receipt_request(
    invoker: SyncInvoker | AsyncInvoker,
    request: agent_service_pb2.CommitToolReceiptRequest,
) -> agent_service_pb2.CommitToolReceiptRequest:
    value = copy.deepcopy(request)
    if not value.HasField("tool_receipt") or not value.HasField("fence"):
        raise ValueError("tool receipt commit requires generated evidence and a fence")
    required_text("agent run ETag", value.run_etag, maximum=1024)
    _scoped_name(invoker, value.tool_receipt.name, "toolReceipts")
    _scoped_name(invoker, value.tool_receipt.agent_run_name, "agentRuns")
    _step_name(invoker, value.tool_receipt.agent_step_name)
    if not value.tool_receipt.HasField("tool"):
        raise ValueError("tool receipt requires an authoritative tool reference")
    _normalize_reference(invoker, value.tool_receipt.tool)
    _normalize_fence(invoker, value.fence)
    return value


class Agents:
    """Synchronous generated-type-only AgentService API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def create_definition(
        self,
        request: agent_service_pb2.CreateAgentDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value, call = _prepare_mutation(
            self._invoker, _create_request(self._invoker, request), options
        )
        return _operation(
            self._invoker.unary(CREATE_AGENT_DEFINITION, value, call=call, retry_safe=True),
            "agent definition create",
        )

    def update_definition(
        self,
        request: agent_service_pb2.UpdateAgentDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value, call = _prepare_mutation(
            self._invoker, _update_request(self._invoker, request), options
        )
        return _operation(
            self._invoker.unary(UPDATE_AGENT_DEFINITION, value, call=call, retry_safe=True),
            "agent definition update",
        )

    def get_definition(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> agent_definition_pb2.AgentDefinition:
        expected = _scoped_name(self._invoker, name, "agentDefinitions")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = self._invoker.unary(
            GET_AGENT_DEFINITION,
            agent_service_pb2.GetAgentDefinitionRequest(
                name=expected, if_none_match=if_none_match.strip()
            ),
            call=call,
            retry_safe=True,
        )
        return _definition(response, expected)

    def list_definitions(
        self,
        request: agent_service_pb2.ListAgentDefinitionsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> agent_service_pb2.ListAgentDefinitionsResponse:
        value = (
            copy.deepcopy(request) if request else agent_service_pb2.ListAgentDefinitionsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "agent definition list")
        _normalize_page(value)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            agent_service_pb2.ListAgentDefinitionsResponse,
            self._invoker.unary(LIST_AGENT_DEFINITIONS, value, call=call, retry_safe=True),
        )

    def start_run(
        self,
        request: agent_service_pb2.StartAgentRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value, call = _prepare_mutation(
            self._invoker, _start_request(self._invoker, request), options
        )
        return _operation(
            self._invoker.unary(START_AGENT_RUN, value, call=call, retry_safe=True),
            "agent run start",
        )

    def get_run(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> agent_run_pb2.AgentRun:
        expected = _scoped_name(self._invoker, name, "agentRuns")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = self._invoker.unary(
            GET_AGENT_RUN,
            agent_service_pb2.GetAgentRunRequest(
                name=expected, if_none_match=if_none_match.strip()
            ),
            call=call,
            retry_safe=True,
        )
        return _run(response, expected)

    def list_runs(
        self,
        request: agent_service_pb2.ListAgentRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> agent_service_pb2.ListAgentRunsResponse:
        value = copy.deepcopy(request) if request else agent_service_pb2.ListAgentRunsRequest()
        value.parent = _parent(self._invoker, value.parent, "agent run list")
        _normalize_page(value)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            agent_service_pb2.ListAgentRunsResponse,
            self._invoker.unary(LIST_AGENT_RUNS, value, call=call, retry_safe=True),
        )

    def cancel_run(
        self,
        request: agent_service_pb2.CancelAgentRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.name, "agentRuns")
        required_text("agent run ETag", value.etag, maximum=1024)
        required_text("agent cancellation reason", value.reason, maximum=1024)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            self._invoker.unary(CANCEL_AGENT_RUN, value, call=call, retry_safe=True),
            "agent run cancellation",
        )

    def get_step(
        self, name: str, *, options: CallOptions | None = None
    ) -> agent_step_pb2.AgentStep:
        expected = _step_name(self._invoker, name)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = self._invoker.unary(
            GET_AGENT_STEP,
            agent_service_pb2.GetAgentStepRequest(name=expected),
            call=call,
            retry_safe=True,
        )
        return _step(response, expected)

    def list_steps(
        self,
        request: agent_service_pb2.ListAgentStepsRequest,
        *,
        options: CallOptions | None = None,
    ) -> agent_service_pb2.ListAgentStepsResponse:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.parent, "agentRuns")
        _normalize_page(value)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            agent_service_pb2.ListAgentStepsResponse,
            self._invoker.unary(LIST_AGENT_STEPS, value, call=call, retry_safe=True),
        )

    def commit_step(
        self,
        request: agent_service_pb2.CommitAgentStepRequest,
        *,
        lease_token: str | None = None,
        options: CallOptions | None = None,
    ) -> tuple[agent_step_pb2.AgentStep, agent_run_pb2.AgentRun]:
        value = _commit_step_request(self._invoker, request)
        expected_run = value.agent_step.run.name
        expected_sequence = value.expected_next_step_sequence
        value, call = _prepare_mutation(
            self._invoker, value, options, lease_token=_lease_token(lease_token, options)
        )
        response = cast(
            agent_service_pb2.CommitAgentStepResponse,
            self._invoker.unary(COMMIT_AGENT_STEP, value, call=call, retry_safe=True),
        )
        step = required_response_message(
            response, "agent_step", agent_step_pb2.AgentStep, label="agent step commit"
        )
        run = _run(response, expected_run)
        if step.sequence != expected_sequence or step.run.name != expected_run:
            raise ProtocolError("agent step commit returned inconsistent durable state")
        return step, run

    def commit_tool_receipt(
        self,
        request: agent_service_pb2.CommitToolReceiptRequest,
        *,
        lease_token: str | None = None,
        options: CallOptions | None = None,
    ) -> tuple[tool_receipt_pb2.ToolReceipt, agent_run_pb2.AgentRun]:
        value = _commit_receipt_request(self._invoker, request)
        expected_name, expected_call, expected_run = (
            value.tool_receipt.name,
            value.tool_receipt.call_id,
            value.tool_receipt.agent_run_name,
        )
        value, call = _prepare_mutation(
            self._invoker, value, options, lease_token=_lease_token(lease_token, options)
        )
        response = cast(
            agent_service_pb2.CommitToolReceiptResponse,
            self._invoker.unary(COMMIT_TOOL_RECEIPT, value, call=call, retry_safe=True),
        )
        receipt = required_response_message(
            response, "tool_receipt", tool_receipt_pb2.ToolReceipt, label="tool receipt commit"
        )
        run = _run(response, expected_run)
        if receipt.name != expected_name or receipt.call_id != expected_call:
            raise ProtocolError("tool receipt commit returned inconsistent durable evidence")
        return receipt, run


class AsyncAgents:
    """Asyncio generated-type-only AgentService API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def create_definition(
        self,
        request: agent_service_pb2.CreateAgentDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value, call = _prepare_mutation(
            self._invoker, _create_request(self._invoker, request), options
        )
        return _operation(
            await self._invoker.unary(CREATE_AGENT_DEFINITION, value, call=call, retry_safe=True),
            "agent definition create",
        )

    async def update_definition(
        self,
        request: agent_service_pb2.UpdateAgentDefinitionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value, call = _prepare_mutation(
            self._invoker, _update_request(self._invoker, request), options
        )
        return _operation(
            await self._invoker.unary(UPDATE_AGENT_DEFINITION, value, call=call, retry_safe=True),
            "agent definition update",
        )

    async def get_definition(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> agent_definition_pb2.AgentDefinition:
        expected = _scoped_name(self._invoker, name, "agentDefinitions")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = await self._invoker.unary(
            GET_AGENT_DEFINITION,
            agent_service_pb2.GetAgentDefinitionRequest(
                name=expected, if_none_match=if_none_match.strip()
            ),
            call=call,
            retry_safe=True,
        )
        return _definition(response, expected)

    async def list_definitions(
        self,
        request: agent_service_pb2.ListAgentDefinitionsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> agent_service_pb2.ListAgentDefinitionsResponse:
        value = (
            copy.deepcopy(request) if request else agent_service_pb2.ListAgentDefinitionsRequest()
        )
        value.parent = _parent(self._invoker, value.parent, "agent definition list")
        _normalize_page(value)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            agent_service_pb2.ListAgentDefinitionsResponse,
            await self._invoker.unary(LIST_AGENT_DEFINITIONS, value, call=call, retry_safe=True),
        )

    async def start_run(
        self, request: agent_service_pb2.StartAgentRunRequest, *, options: CallOptions | None = None
    ) -> operation_pb2.Operation:
        value, call = _prepare_mutation(
            self._invoker, _start_request(self._invoker, request), options
        )
        return _operation(
            await self._invoker.unary(START_AGENT_RUN, value, call=call, retry_safe=True),
            "agent run start",
        )

    async def get_run(
        self, name: str, *, if_none_match: str = "", options: CallOptions | None = None
    ) -> agent_run_pb2.AgentRun:
        expected = _scoped_name(self._invoker, name, "agentRuns")
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = await self._invoker.unary(
            GET_AGENT_RUN,
            agent_service_pb2.GetAgentRunRequest(
                name=expected, if_none_match=if_none_match.strip()
            ),
            call=call,
            retry_safe=True,
        )
        return _run(response, expected)

    async def list_runs(
        self,
        request: agent_service_pb2.ListAgentRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
    ) -> agent_service_pb2.ListAgentRunsResponse:
        value = copy.deepcopy(request) if request else agent_service_pb2.ListAgentRunsRequest()
        value.parent = _parent(self._invoker, value.parent, "agent run list")
        _normalize_page(value)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            agent_service_pb2.ListAgentRunsResponse,
            await self._invoker.unary(LIST_AGENT_RUNS, value, call=call, retry_safe=True),
        )

    async def cancel_run(
        self,
        request: agent_service_pb2.CancelAgentRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.name, "agentRuns")
        required_text("agent run ETag", value.etag, maximum=1024)
        required_text("agent cancellation reason", value.reason, maximum=1024)
        value, call = _prepare_mutation(self._invoker, value, options)
        return _operation(
            await self._invoker.unary(CANCEL_AGENT_RUN, value, call=call, retry_safe=True),
            "agent run cancellation",
        )

    async def get_step(
        self, name: str, *, options: CallOptions | None = None
    ) -> agent_step_pb2.AgentStep:
        expected = _step_name(self._invoker, name)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        response = await self._invoker.unary(
            GET_AGENT_STEP,
            agent_service_pb2.GetAgentStepRequest(name=expected),
            call=call,
            retry_safe=True,
        )
        return _step(response, expected)

    async def list_steps(
        self,
        request: agent_service_pb2.ListAgentStepsRequest,
        *,
        options: CallOptions | None = None,
    ) -> agent_service_pb2.ListAgentStepsResponse:
        value = copy.deepcopy(request)
        _scoped_name(self._invoker, value.parent, "agentRuns")
        _normalize_page(value)
        call = prepare_call(
            options, default_timeout=self._invoker.config.default_timeout, require_idempotency=False
        )
        return cast(
            agent_service_pb2.ListAgentStepsResponse,
            await self._invoker.unary(LIST_AGENT_STEPS, value, call=call, retry_safe=True),
        )

    async def commit_step(
        self,
        request: agent_service_pb2.CommitAgentStepRequest,
        *,
        lease_token: str | None = None,
        options: CallOptions | None = None,
    ) -> tuple[agent_step_pb2.AgentStep, agent_run_pb2.AgentRun]:
        value = _commit_step_request(self._invoker, request)
        expected_run, expected_sequence = (
            value.agent_step.run.name,
            value.expected_next_step_sequence,
        )
        value, call = _prepare_mutation(
            self._invoker, value, options, lease_token=_lease_token(lease_token, options)
        )
        response = cast(
            agent_service_pb2.CommitAgentStepResponse,
            await self._invoker.unary(COMMIT_AGENT_STEP, value, call=call, retry_safe=True),
        )
        step = required_response_message(
            response, "agent_step", agent_step_pb2.AgentStep, label="agent step commit"
        )
        run = _run(response, expected_run)
        if step.sequence != expected_sequence or step.run.name != expected_run:
            raise ProtocolError("agent step commit returned inconsistent durable state")
        return step, run

    async def commit_tool_receipt(
        self,
        request: agent_service_pb2.CommitToolReceiptRequest,
        *,
        lease_token: str | None = None,
        options: CallOptions | None = None,
    ) -> tuple[tool_receipt_pb2.ToolReceipt, agent_run_pb2.AgentRun]:
        value = _commit_receipt_request(self._invoker, request)
        expected_name, expected_call, expected_run = (
            value.tool_receipt.name,
            value.tool_receipt.call_id,
            value.tool_receipt.agent_run_name,
        )
        value, call = _prepare_mutation(
            self._invoker, value, options, lease_token=_lease_token(lease_token, options)
        )
        response = cast(
            agent_service_pb2.CommitToolReceiptResponse,
            await self._invoker.unary(COMMIT_TOOL_RECEIPT, value, call=call, retry_safe=True),
        )
        receipt = required_response_message(
            response, "tool_receipt", tool_receipt_pb2.ToolReceipt, label="tool receipt commit"
        )
        run = _run(response, expected_run)
        if receipt.name != expected_name or receipt.call_id != expected_call:
            raise ProtocolError("tool receipt commit returned inconsistent durable evidence")
        return receipt, run
