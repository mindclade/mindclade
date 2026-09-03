from __future__ import annotations

import copy
import hashlib
import unittest
from datetime import UTC, datetime, timedelta

from google.protobuf.field_mask_pb2 import FieldMask
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.agent.v1 import agent_definition_pb2, agent_run_pb2, agent_step_pb2, tool_receipt_pb2
from mindclade.common.v1 import command_context_pb2, pagination_pb2, resource_reference_pb2
from mindclade.internal.agent.v1 import agent_service_pb2
from mindclade.job.v1 import lease_fencing_pb2, operation_pb2
from mindclade_internal_sdk._invocation import AsyncInvoker, SyncInvoker, canonical_digest
from mindclade_internal_sdk.agents import (
    CANCEL_AGENT_RUN,
    COMMIT_AGENT_STEP,
    COMMIT_TOOL_RECEIPT,
    CREATE_AGENT_DEFINITION,
    GET_AGENT_DEFINITION,
    GET_AGENT_RUN,
    GET_AGENT_STEP,
    LIST_AGENT_DEFINITIONS,
    LIST_AGENT_RUNS,
    LIST_AGENT_STEPS,
    START_AGENT_RUN,
    UPDATE_AGENT_DEFINITION,
    Agents,
    AsyncAgents,
)
from mindclade_internal_sdk.calls import CallOptions
from mindclade_internal_sdk.client import AsyncClient, Client
from mindclade_internal_sdk.config import ClientConfig, Environment
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import Metadata

PARENT = "tenants/tenant-a/projects/project-a"
DEFINITION_NAME = f"{PARENT}/agentDefinitions/definition-1"
RUN_NAME = f"{PARENT}/agentRuns/run-1"
STEP_NAME = f"{RUN_NAME}/agentSteps/1"
RECEIPT_NAME = f"{PARENT}/toolReceipts/receipt-1"


def config() -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-a",
        project_id="project-a",
        principal_id="principal-a",
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:1",
        insecure_for_testing=True,
        default_timeout=1,
    )


def reference(
    resource_type: str, collection: str, resource_id: str
) -> resource_reference_pb2.ResourceRef:
    return resource_reference_pb2.ResourceRef(
        resource_type=resource_type,
        resource_id=resource_id,
        name=f"{PARENT}/{collection}/{resource_id}",
    )


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def deadline() -> Timestamp:
    value = Timestamp()
    value.FromDatetime(datetime.now(UTC) + timedelta(minutes=1))
    return value


def fence(token: str) -> lease_fencing_pb2.LeaseFence:
    return lease_fencing_pb2.LeaseFence(
        tenant_id="tenant-a",
        project_id="project-a",
        job_id="jobs/job-1",
        run_id="runs/run-1",
        attempt_id="attempts/attempt-1",
        lease_epoch=1,
        deadline=deadline(),
        lease_token_digest=digest(token),
    )


def definition() -> agent_definition_pb2.AgentDefinition:
    return agent_definition_pb2.AgentDefinition(
        workflow_definition=reference("workflow_definition", "workflowDefinitions", "workflow-1"),
        evaluation_suite=reference("evaluation_suite", "evaluationSuites", "evaluation-1"),
        eligible_tools=[reference("tool", "tools", "tool-1")],
    )


def operation(value: str) -> operation_pb2.Operation:
    return operation_pb2.Operation(operation_id=f"operations/{value}")


def mutation_context(message: Message) -> command_context_pb2.CommandContext:
    if not isinstance(
        message,
        (
            agent_service_pb2.CreateAgentDefinitionRequest,
            agent_service_pb2.UpdateAgentDefinitionRequest,
            agent_service_pb2.StartAgentRunRequest,
            agent_service_pb2.CancelAgentRunRequest,
            agent_service_pb2.CommitAgentStepRequest,
            agent_service_pb2.CommitToolReceiptRequest,
        ),
    ):
        raise AssertionError(type(message))
    value = command_context_pb2.CommandContext()
    value.CopyFrom(message.context)
    return value


class SyncAgentsTest(unittest.TestCase):
    def test_all_generated_rpcs_identity_digest_pagination_and_fence(self) -> None:
        transport = FakeSyncTransport()
        captured: list[tuple[Message, Metadata]] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            captured.append((copy.deepcopy(request), metadata))
            if isinstance(request, agent_service_pb2.CreateAgentDefinitionRequest):
                return agent_service_pb2.CreateAgentDefinitionResponse(
                    operation=operation("create")
                )
            if isinstance(request, agent_service_pb2.UpdateAgentDefinitionRequest):
                return agent_service_pb2.UpdateAgentDefinitionResponse(
                    operation=operation("update")
                )
            if isinstance(request, agent_service_pb2.GetAgentDefinitionRequest):
                return agent_service_pb2.GetAgentDefinitionResponse(
                    agent_definition=agent_definition_pb2.AgentDefinition(name=request.name)
                )
            if isinstance(request, agent_service_pb2.ListAgentDefinitionsRequest):
                return agent_service_pb2.ListAgentDefinitionsResponse(
                    page=pagination_pb2.PageResponse(
                        next_page_token=request.page.page_token + "-definition"
                    )
                )
            if isinstance(request, agent_service_pb2.StartAgentRunRequest):
                return agent_service_pb2.StartAgentRunResponse(operation=operation("start"))
            if isinstance(request, agent_service_pb2.GetAgentRunRequest):
                return agent_service_pb2.GetAgentRunResponse(
                    agent_run=agent_run_pb2.AgentRun(name=request.name)
                )
            if isinstance(request, agent_service_pb2.ListAgentRunsRequest):
                return agent_service_pb2.ListAgentRunsResponse(
                    page=pagination_pb2.PageResponse(
                        next_page_token=request.page.page_token + "-run"
                    )
                )
            if isinstance(request, agent_service_pb2.CancelAgentRunRequest):
                return agent_service_pb2.CancelAgentRunResponse(operation=operation("cancel"))
            if isinstance(request, agent_service_pb2.GetAgentStepRequest):
                return agent_service_pb2.GetAgentStepResponse(
                    agent_step=agent_step_pb2.AgentStep(name=request.name, sequence=1)
                )
            if isinstance(request, agent_service_pb2.ListAgentStepsRequest):
                return agent_service_pb2.ListAgentStepsResponse(
                    page=pagination_pb2.PageResponse(
                        next_page_token=request.page.page_token + "-step"
                    )
                )
            if isinstance(request, agent_service_pb2.CommitAgentStepRequest):
                accepted = copy.deepcopy(request.agent_step)
                accepted.name = STEP_NAME
                return agent_service_pb2.CommitAgentStepResponse(
                    agent_step=accepted, agent_run=agent_run_pb2.AgentRun(name=RUN_NAME)
                )
            if isinstance(request, agent_service_pb2.CommitToolReceiptRequest):
                return agent_service_pb2.CommitToolReceiptResponse(
                    tool_receipt=request.tool_receipt,
                    agent_run=agent_run_pb2.AgentRun(name=RUN_NAME),
                )
            raise AssertionError(type(request))

        for route in (
            CREATE_AGENT_DEFINITION,
            UPDATE_AGENT_DEFINITION,
            GET_AGENT_DEFINITION,
            LIST_AGENT_DEFINITIONS,
            START_AGENT_RUN,
            GET_AGENT_RUN,
            LIST_AGENT_RUNS,
            CANCEL_AGENT_RUN,
            GET_AGENT_STEP,
            LIST_AGENT_STEPS,
            COMMIT_AGENT_STEP,
            COMMIT_TOOL_RECEIPT,
        ):
            transport.unary_handlers[route] = handler

        agents = Agents(SyncInvoker(config(), transport))
        create = agent_service_pb2.CreateAgentDefinitionRequest(
            agent_definition_id="definition-1", agent_definition=definition()
        )
        original = copy.deepcopy(create)
        self.assertEqual(agents.create_definition(create).operation_id, "operations/create")
        self.assertEqual(create, original)

        updated = definition()
        updated.name = DEFINITION_NAME
        agents.update_definition(
            agent_service_pb2.UpdateAgentDefinitionRequest(
                agent_definition=updated,
                update_mask=FieldMask(paths=["purpose"]),
                etag="etag-1",
            )
        )
        self.assertEqual(agents.get_definition(DEFINITION_NAME).name, DEFINITION_NAME)
        self.assertEqual(
            agents.list_definitions(
                agent_service_pb2.ListAgentDefinitionsRequest(
                    page=pagination_pb2.PageRequest(page_token="opaque")
                )
            ).page.next_page_token,
            "opaque-definition",
        )

        run = agent_run_pb2.AgentRun(
            definition=reference("agent_definition", "agentDefinitions", "definition-1"),
            budget_reservation=reference("budget_reservation", "budgetReservations", "budget-1"),
        )
        agents.start_run(
            agent_service_pb2.StartAgentRunRequest(agent_run_id="run-1", agent_run=run)
        )
        self.assertEqual(agents.get_run(RUN_NAME).name, RUN_NAME)
        self.assertEqual(
            agents.list_runs(
                agent_service_pb2.ListAgentRunsRequest(
                    page=pagination_pb2.PageRequest(page_token="opaque")
                )
            ).page.next_page_token,
            "opaque-run",
        )
        agents.cancel_run(
            agent_service_pb2.CancelAgentRunRequest(
                name=RUN_NAME, etag="etag-2", reason="operator request"
            )
        )
        self.assertEqual(agents.get_step(STEP_NAME).name, STEP_NAME)
        self.assertEqual(
            agents.list_steps(
                agent_service_pb2.ListAgentStepsRequest(
                    parent=RUN_NAME,
                    page=pagination_pb2.PageRequest(page_token="opaque"),
                )
            ).page.next_page_token,
            "opaque-step",
        )

        token = "scheduler-issued-agent-token"
        accepted, reconciled = agents.commit_step(
            agent_service_pb2.CommitAgentStepRequest(
                agent_step=agent_step_pb2.AgentStep(
                    run=reference("agent_run", "agentRuns", "run-1"), sequence=1
                ),
                fence=fence(token),
                run_etag="etag-3",
                expected_next_step_sequence=1,
            ),
            options=CallOptions(lease_token=token),
        )
        self.assertEqual((accepted.name, reconciled.name), (STEP_NAME, RUN_NAME))
        receipt, receipt_run = agents.commit_tool_receipt(
            agent_service_pb2.CommitToolReceiptRequest(
                tool_receipt=tool_receipt_pb2.ToolReceipt(
                    name=RECEIPT_NAME,
                    call_id="call-1",
                    agent_run_name=RUN_NAME,
                    agent_step_name=STEP_NAME,
                    tool=reference("tool", "tools", "tool-1"),
                ),
                run_etag="etag-4",
                fence=fence(token),
            ),
            lease_token=token,
        )
        self.assertEqual((receipt.name, receipt_run.name), (RECEIPT_NAME, RUN_NAME))

        mutation_indices = (0, 1, 4, 7, 10, 11)
        for index in mutation_indices:
            request = captured[index][0]
            context = mutation_context(request)
            self.assertEqual(context.principal_id, "principal-a")
            self.assertEqual(context.tenant_id, "tenant-a")
            self.assertEqual(context.project_id, "project-a")
            canonical = copy.deepcopy(request)
            canonical.ClearField("context")
            self.assertEqual(context.canonical_request_digest, canonical_digest(canonical))

        for request, metadata in captured[:10]:
            del request
            self.assertNotIn("x-mindclade-lease-token", dict(metadata))
        self.assertEqual(dict(captured[10][1])["x-mindclade-lease-token"], token)
        self.assertEqual(dict(captured[11][1])["x-mindclade-lease-token"], token)

    def test_fenced_commit_requires_raw_token_and_page_is_bounded(self) -> None:
        agents = Agents(SyncInvoker(config(), FakeSyncTransport()))
        with self.assertRaises(ValueError):
            agents.commit_step(
                agent_service_pb2.CommitAgentStepRequest(
                    agent_step=agent_step_pb2.AgentStep(
                        run=reference("agent_run", "agentRuns", "run-1"), sequence=1
                    ),
                    fence=fence("token"),
                    run_etag="etag",
                    expected_next_step_sequence=1,
                )
            )
        with self.assertRaises(ValueError):
            agents.list_steps(
                agent_service_pb2.ListAgentStepsRequest(
                    parent=RUN_NAME,
                    page=pagination_pb2.PageRequest(page_size=201),
                )
            )

    def test_top_level_client_registers_agent_facade(self) -> None:
        client = Client(config(), transport=FakeSyncTransport(), close_transport=False)
        self.assertIsInstance(client.agents, Agents)


class AsyncAgentsTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_facade_covers_all_generated_rpcs(self) -> None:
        transport = FakeAsyncTransport()
        seen: list[tuple[Message, Metadata]] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            seen.append((copy.deepcopy(request), metadata))
            if isinstance(request, agent_service_pb2.CreateAgentDefinitionRequest):
                return agent_service_pb2.CreateAgentDefinitionResponse(
                    operation=operation("async-create")
                )
            if isinstance(request, agent_service_pb2.UpdateAgentDefinitionRequest):
                return agent_service_pb2.UpdateAgentDefinitionResponse(
                    operation=operation("async-update")
                )
            if isinstance(request, agent_service_pb2.GetAgentDefinitionRequest):
                return agent_service_pb2.GetAgentDefinitionResponse(
                    agent_definition=agent_definition_pb2.AgentDefinition(name=request.name)
                )
            if isinstance(request, agent_service_pb2.ListAgentDefinitionsRequest):
                return agent_service_pb2.ListAgentDefinitionsResponse(
                    page=pagination_pb2.PageResponse(next_page_token="next-definition")
                )
            if isinstance(request, agent_service_pb2.StartAgentRunRequest):
                return agent_service_pb2.StartAgentRunResponse(operation=operation("async-start"))
            if isinstance(request, agent_service_pb2.GetAgentRunRequest):
                return agent_service_pb2.GetAgentRunResponse(
                    agent_run=agent_run_pb2.AgentRun(name=request.name)
                )
            if isinstance(request, agent_service_pb2.ListAgentRunsRequest):
                return agent_service_pb2.ListAgentRunsResponse(
                    page=pagination_pb2.PageResponse(next_page_token="next-run")
                )
            if isinstance(request, agent_service_pb2.CancelAgentRunRequest):
                return agent_service_pb2.CancelAgentRunResponse(operation=operation("async-cancel"))
            if isinstance(request, agent_service_pb2.GetAgentStepRequest):
                return agent_service_pb2.GetAgentStepResponse(
                    agent_step=agent_step_pb2.AgentStep(name=request.name, sequence=1)
                )
            if isinstance(request, agent_service_pb2.ListAgentStepsRequest):
                return agent_service_pb2.ListAgentStepsResponse(
                    page=pagination_pb2.PageResponse(next_page_token="next-step")
                )
            if isinstance(request, agent_service_pb2.CommitAgentStepRequest):
                accepted = copy.deepcopy(request.agent_step)
                accepted.name = STEP_NAME
                return agent_service_pb2.CommitAgentStepResponse(
                    agent_step=accepted,
                    agent_run=agent_run_pb2.AgentRun(name=RUN_NAME),
                )
            if isinstance(request, agent_service_pb2.CommitToolReceiptRequest):
                return agent_service_pb2.CommitToolReceiptResponse(
                    tool_receipt=request.tool_receipt,
                    agent_run=agent_run_pb2.AgentRun(name=RUN_NAME),
                )
            raise AssertionError(type(request))

        routes = (
            CREATE_AGENT_DEFINITION,
            UPDATE_AGENT_DEFINITION,
            GET_AGENT_DEFINITION,
            LIST_AGENT_DEFINITIONS,
            START_AGENT_RUN,
            GET_AGENT_RUN,
            LIST_AGENT_RUNS,
            CANCEL_AGENT_RUN,
            GET_AGENT_STEP,
            LIST_AGENT_STEPS,
            COMMIT_AGENT_STEP,
            COMMIT_TOOL_RECEIPT,
        )
        for route in routes:
            transport.unary_handlers[route] = handler

        agents = AsyncAgents(AsyncInvoker(config(), transport))
        client = AsyncClient(config(), transport=transport, close_transport=False)
        self.assertIsInstance(client.agents, AsyncAgents)

        self.assertEqual(
            (
                await agents.create_definition(
                    agent_service_pb2.CreateAgentDefinitionRequest(
                        agent_definition_id="definition-1", agent_definition=definition()
                    )
                )
            ).operation_id,
            "operations/async-create",
        )
        updated = definition()
        updated.name = DEFINITION_NAME
        await agents.update_definition(
            agent_service_pb2.UpdateAgentDefinitionRequest(
                agent_definition=updated,
                update_mask=FieldMask(paths=["purpose"]),
                etag="etag-1",
            )
        )
        self.assertEqual((await agents.get_definition(DEFINITION_NAME)).name, DEFINITION_NAME)
        self.assertEqual(
            (
                await agents.list_definitions(
                    agent_service_pb2.ListAgentDefinitionsRequest(
                        page=pagination_pb2.PageRequest(page_token="opaque")
                    )
                )
            ).page.next_page_token,
            "next-definition",
        )
        started = await agents.start_run(
            agent_service_pb2.StartAgentRunRequest(
                agent_run_id="run-1",
                agent_run=agent_run_pb2.AgentRun(
                    definition=reference("agent_definition", "agentDefinitions", "definition-1"),
                    budget_reservation=reference(
                        "budget_reservation", "budgetReservations", "budget-1"
                    ),
                ),
            )
        )
        self.assertEqual(started.operation_id, "operations/async-start")
        self.assertEqual((await agents.get_run(RUN_NAME)).name, RUN_NAME)
        self.assertEqual(
            (await agents.list_runs()).page.next_page_token,
            "next-run",
        )
        self.assertEqual(
            (
                await agents.cancel_run(
                    agent_service_pb2.CancelAgentRunRequest(
                        name=RUN_NAME, etag="etag-2", reason="operator request"
                    )
                )
            ).operation_id,
            "operations/async-cancel",
        )
        self.assertEqual((await agents.get_step(STEP_NAME)).name, STEP_NAME)
        self.assertEqual(
            (
                await agents.list_steps(agent_service_pb2.ListAgentStepsRequest(parent=RUN_NAME))
            ).page.next_page_token,
            "next-step",
        )

        token = "scheduler-issued-async-agent-token"
        accepted, accepted_run = await agents.commit_step(
            agent_service_pb2.CommitAgentStepRequest(
                agent_step=agent_step_pb2.AgentStep(
                    run=reference("agent_run", "agentRuns", "run-1"), sequence=1
                ),
                fence=fence(token),
                run_etag="etag-3",
                expected_next_step_sequence=1,
            ),
            options=CallOptions(lease_token=token),
        )
        self.assertEqual((accepted.name, accepted_run.name), (STEP_NAME, RUN_NAME))
        receipt, receipt_run = await agents.commit_tool_receipt(
            agent_service_pb2.CommitToolReceiptRequest(
                tool_receipt=tool_receipt_pb2.ToolReceipt(
                    name=RECEIPT_NAME,
                    call_id="call-async",
                    agent_run_name=RUN_NAME,
                    agent_step_name=STEP_NAME,
                    tool=reference("tool", "tools", "tool-1"),
                ),
                run_etag="etag-4",
                fence=fence(token),
            ),
            lease_token=token,
        )
        self.assertEqual((receipt.name, receipt_run.name), (RECEIPT_NAME, RUN_NAME))

        self.assertEqual(len(seen), 12)
        for index in (0, 1, 4, 7, 10, 11):
            context = mutation_context(seen[index][0])
            self.assertEqual(context.principal_id, "principal-a")
            self.assertRegex(context.canonical_request_digest, r"^sha256:[0-9a-f]{64}$")
        for _, metadata in seen[:10]:
            self.assertNotIn("x-mindclade-lease-token", dict(metadata))
        self.assertEqual(dict(seen[10][1])["x-mindclade-lease-token"], token)
        self.assertEqual(dict(seen[11][1])["x-mindclade-lease-token"], token)


if __name__ == "__main__":
    unittest.main()
