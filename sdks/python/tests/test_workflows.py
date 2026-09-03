from __future__ import annotations

import asyncio
import copy
import hashlib
import unittest
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime, timedelta

from google.protobuf.field_mask_pb2 import FieldMask
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.common.v1 import command_context_pb2, pagination_pb2, resource_reference_pb2
from mindclade.internal.workflow.v1 import workflow_service_pb2
from mindclade.job.v1 import lease_fencing_pb2, operation_pb2
from mindclade.workflow.v1 import approval_pb2, workflow_definition_pb2, workflow_run_pb2
from mindclade_internal_sdk import (
    AsyncClient,
    CallOptions,
    Client,
    ClientConfig,
    Environment,
    UnavailableError,
)
from mindclade_internal_sdk._invocation import canonical_digest
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
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
    Metadata,
)

PARENT = "tenants/tenant-a/projects/project-a"
DEFINITION_NAME = f"{PARENT}/workflowDefinitions/definition-1"
RUN_NAME = f"{PARENT}/workflowRuns/run-1"
APPROVAL_NAME = f"{PARENT}/approvalRequests/approval-1"
RECEIPT_NAME = f"{PARENT}/approvalReceipts/receipt-1"

UNARY_METHODS = (
    CREATE_WORKFLOW_DEFINITION,
    UPDATE_WORKFLOW_DEFINITION,
    GET_WORKFLOW_DEFINITION,
    LIST_WORKFLOW_DEFINITIONS,
    START_WORKFLOW_RUN,
    GET_WORKFLOW_RUN,
    LIST_WORKFLOW_RUNS,
    CANCEL_WORKFLOW_RUN,
    COMMIT_WORKFLOW_TRANSITION,
    REQUEST_APPROVAL,
    GET_APPROVAL_REQUEST,
    LIST_APPROVAL_REQUESTS,
    DECIDE_APPROVAL,
    CONSUME_APPROVAL,
)


def config() -> ClientConfig:
    return ClientConfig(
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:9443",
        tenant_id="tenant-a",
        project_id="project-a",
        principal_id="principal-a",
        insecure_for_testing=True,
    )


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def binding() -> approval_pb2.ApprovalBinding:
    value = approval_pb2.ApprovalBinding(
        action="workflow.execute",
        intent_digest=digest("intent"),
        parameters_digest=digest("parameters"),
        risk_class="bounded",
    )
    value.binding_digest = canonical_digest(value)
    return value


def operation(label: str) -> operation_pb2.Operation:
    return operation_pb2.Operation(operation_id=f"operations/{label}")


def receipt(
    *,
    decision: approval_pb2.ApprovalDecisionValue = (approval_pb2.APPROVAL_DECISION_VALUE_APPROVE),
    reason_code: str = "approved",
    safe_reason: str = "reviewed",
    consumed_by: str = "",
) -> approval_pb2.ApprovalReceipt:
    value = approval_pb2.ApprovalReceipt(
        name=RECEIPT_NAME,
        request=resource_reference_pb2.ResourceRef(
            resource_type="approval_request",
            resource_id="approval-1",
            tenant_id="tenant-a",
            project_id="project-a",
            name=APPROVAL_NAME,
        ),
        binding=binding(),
        decision=decision,
        reason_code=reason_code,
        safe_reason=safe_reason,
        decided_at=timestamp(datetime.now(UTC)),
        receipt_digest=digest("receipt"),
    )
    if consumed_by:
        value.consumed_at.CopyFrom(timestamp(datetime.now(UTC)))
        value.consumed_by_call_id = consumed_by
    return value


def response_for(request: Message) -> Message:
    if isinstance(request, workflow_service_pb2.CreateWorkflowDefinitionRequest):
        return workflow_service_pb2.CreateWorkflowDefinitionResponse(
            operation=operation("definition-create")
        )
    if isinstance(request, workflow_service_pb2.UpdateWorkflowDefinitionRequest):
        return workflow_service_pb2.UpdateWorkflowDefinitionResponse(
            operation=operation("definition-update")
        )
    if isinstance(request, workflow_service_pb2.GetWorkflowDefinitionRequest):
        return workflow_service_pb2.GetWorkflowDefinitionResponse(
            workflow_definition=workflow_definition_pb2.WorkflowDefinition(name=DEFINITION_NAME)
        )
    if isinstance(request, workflow_service_pb2.ListWorkflowDefinitionsRequest):
        return workflow_service_pb2.ListWorkflowDefinitionsResponse(
            page=pagination_pb2.PageResponse(next_page_token="definition-page")
        )
    if isinstance(request, workflow_service_pb2.StartWorkflowRunRequest):
        return workflow_service_pb2.StartWorkflowRunResponse(operation=operation("run-start"))
    if isinstance(request, workflow_service_pb2.GetWorkflowRunRequest):
        return workflow_service_pb2.GetWorkflowRunResponse(
            workflow_run=workflow_run_pb2.WorkflowRun(
                name=RUN_NAME,
                state=workflow_run_pb2.WORKFLOW_RUN_STATE_RUNNING,
                transition_sequence=1,
            )
        )
    if isinstance(request, workflow_service_pb2.ListWorkflowRunsRequest):
        return workflow_service_pb2.ListWorkflowRunsResponse(
            page=pagination_pb2.PageResponse(next_page_token="run-page")
        )
    if isinstance(request, workflow_service_pb2.CancelWorkflowRunRequest):
        return workflow_service_pb2.CancelWorkflowRunResponse(operation=operation("run-cancel"))
    if isinstance(request, workflow_service_pb2.CommitWorkflowTransitionRequest):
        run = copy.deepcopy(request.workflow_run)
        run.transition_sequence = request.expected_transition_sequence + 1
        return workflow_service_pb2.CommitWorkflowTransitionResponse(workflow_run=run)
    if isinstance(request, workflow_service_pb2.RequestApprovalRequest):
        created = copy.deepcopy(request.approval_request)
        created.name = APPROVAL_NAME
        return workflow_service_pb2.RequestApprovalResponse(approval_request=created)
    if isinstance(request, workflow_service_pb2.GetApprovalRequestRequest):
        return workflow_service_pb2.GetApprovalRequestResponse(
            approval_request=approval_pb2.ApprovalRequest(name=APPROVAL_NAME, binding=binding())
        )
    if isinstance(request, workflow_service_pb2.ListApprovalRequestsRequest):
        return workflow_service_pb2.ListApprovalRequestsResponse(
            page=pagination_pb2.PageResponse(next_page_token="approval-page")
        )
    if isinstance(request, workflow_service_pb2.DecideApprovalRequest):
        return workflow_service_pb2.DecideApprovalResponse(
            approval_receipt=receipt(
                decision=request.decision,
                reason_code=request.reason_code,
                safe_reason=request.safe_reason,
            )
        )
    if isinstance(request, workflow_service_pb2.ConsumeApprovalRequest):
        value = receipt(consumed_by=request.call_id)
        value.binding.binding_digest = request.binding_digest
        return workflow_service_pb2.ConsumeApprovalResponse(approval_receipt=value)
    raise AssertionError(type(request))


def watch_responses(request: Message) -> Iterable[Message]:
    assert isinstance(request, workflow_service_pb2.WatchWorkflowRunRequest)
    if request.after_transition_sequence == 0:
        yield workflow_service_pb2.WatchWorkflowRunResponse(
            workflow_run=workflow_run_pb2.WorkflowRun(
                name=RUN_NAME,
                state=workflow_run_pb2.WORKFLOW_RUN_STATE_RUNNING,
                transition_sequence=1,
            )
        )
        return
    yield workflow_service_pb2.WatchWorkflowRunResponse(
        workflow_run=workflow_run_pb2.WorkflowRun(
            name=RUN_NAME,
            state=workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED,
            transition_sequence=request.after_transition_sequence + 1,
        )
    )


def definition_create() -> workflow_service_pb2.CreateWorkflowDefinitionRequest:
    return workflow_service_pb2.CreateWorkflowDefinitionRequest(
        context=command_context_pb2.CommandContext(
            idempotency_key="definition-create", principal_id="forged"
        ),
        workflow_definition_id="definition-1",
        workflow_definition=workflow_definition_pb2.WorkflowDefinition(),
    )


def definition_update() -> workflow_service_pb2.UpdateWorkflowDefinitionRequest:
    return workflow_service_pb2.UpdateWorkflowDefinitionRequest(
        workflow_definition=workflow_definition_pb2.WorkflowDefinition(name=DEFINITION_NAME),
        update_mask=FieldMask(paths=["display_name"]),
        etag="etag-definition",
    )


def run_start() -> workflow_service_pb2.StartWorkflowRunRequest:
    return workflow_service_pb2.StartWorkflowRunRequest(
        workflow_run_id="run-1",
        workflow_run=workflow_run_pb2.WorkflowRun(
            definition=resource_reference_pb2.ResourceRef(name=DEFINITION_NAME)
        ),
    )


def transition() -> workflow_service_pb2.CommitWorkflowTransitionRequest:
    return workflow_service_pb2.CommitWorkflowTransitionRequest(
        workflow_run=workflow_run_pb2.WorkflowRun(name=RUN_NAME),
        expected_transition_sequence=1,
        etag="etag-run",
        fence=lease_fencing_pb2.LeaseFence(
            job_id="jobs/job-1",
            run_id="runs/run-1",
            attempt_id="attempts/attempt-1",
            lease_epoch=1,
            deadline=timestamp(datetime.now(UTC) + timedelta(minutes=1)),
            lease_token_digest=digest("lease-token"),
        ),
    )


def approval_request() -> approval_pb2.ApprovalRequest:
    return approval_pb2.ApprovalRequest(
        context=command_context_pb2.CommandContext(
            idempotency_key="approval-request", principal_id="forged"
        ),
        binding=binding(),
    )


def decision() -> workflow_service_pb2.DecideApprovalRequest:
    return workflow_service_pb2.DecideApprovalRequest(
        name=APPROVAL_NAME,
        etag="etag-approval",
        decision=approval_pb2.APPROVAL_DECISION_VALUE_APPROVE,
        reason_code="approved",
        safe_reason="reviewed",
    )


def consumption() -> workflow_service_pb2.ConsumeApprovalRequest:
    return workflow_service_pb2.ConsumeApprovalRequest(
        receipt_name=RECEIPT_NAME,
        binding_digest=binding().binding_digest,
        call_id="call-1",
    )


class WorkflowApprovalTest(unittest.TestCase):
    def test_all_generated_rpcs_scope_context_watch_fence_and_receipts(self) -> None:
        transport = FakeSyncTransport()
        captured: dict[str, list[tuple[Message, Metadata]]] = {}

        def unary(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            method = next(
                method for method in UNARY_METHODS if transport.calls[-1].method == method
            )
            captured.setdefault(method, []).append((copy.deepcopy(request), metadata))
            return response_for(request)

        for method in UNARY_METHODS:
            transport.unary_handlers[method] = unary
        transport.stream_handlers[WATCH_WORKFLOW_RUN] = lambda request, timeout, metadata: (
            watch_responses(request)
        )
        client = Client(config(), transport=transport)

        create = definition_create()
        original = copy.deepcopy(create)
        self.assertEqual(
            client.workflows.create_definition(create).operation_id, "operations/definition-create"
        )
        self.assertEqual(create, original)
        self.assertEqual(
            client.workflows.update_definition(definition_update()).operation_id,
            "operations/definition-update",
        )
        self.assertEqual(client.workflows.get_definition(DEFINITION_NAME).name, DEFINITION_NAME)
        self.assertEqual(
            client.workflows.list_definitions().page.next_page_token, "definition-page"
        )
        self.assertEqual(
            client.workflows.start_run(run_start()).operation_id, "operations/run-start"
        )
        self.assertEqual(client.workflows.get_run(RUN_NAME).name, RUN_NAME)
        self.assertEqual(client.workflows.list_runs().page.next_page_token, "run-page")
        self.assertEqual(
            client.workflows.cancel_run(
                workflow_service_pb2.CancelWorkflowRunRequest(
                    name=RUN_NAME, etag="etag-run", reason="operator request"
                )
            ).operation_id,
            "operations/run-cancel",
        )
        committed = client.workflows.commit_transition(
            transition(), options=CallOptions(lease_token="lease-token")
        )
        self.assertEqual(committed.transition_sequence, 2)
        self.assertEqual(
            [run.transition_sequence for run in client.workflows.watch(RUN_NAME, timeout=1)],
            [1, 2],
        )
        self.assertEqual(
            client.workflows.wait(RUN_NAME, after_transition_sequence=1, timeout=1).state,
            workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED,
        )

        created = client.approvals.request(approval_request())
        self.assertEqual(created.name, APPROVAL_NAME)
        self.assertEqual(created.requested_by_principal_ref, "principal-a")
        self.assertEqual(client.approvals.get(APPROVAL_NAME).name, APPROVAL_NAME)
        self.assertEqual(client.approvals.list().page.next_page_token, "approval-page")
        decided = client.approvals.decide(decision())
        self.assertEqual(decided.name, RECEIPT_NAME)
        self.assertEqual(client.approvals.consume(consumption()).consumed_by_call_id, "call-1")

        self.assertEqual(set(captured), set(UNARY_METHODS))
        create_wire = captured[CREATE_WORKFLOW_DEFINITION][0][0]
        assert isinstance(create_wire, workflow_service_pb2.CreateWorkflowDefinitionRequest)
        self.assertEqual(create_wire.parent, PARENT)
        self.assertEqual(create_wire.context.principal_id, "principal-a")
        self.assertRegex(create_wire.context.canonical_request_digest, r"^sha256:[0-9a-f]{64}$")
        commit_metadata = dict(captured[COMMIT_WORKFLOW_TRANSITION][0][1])
        self.assertEqual(commit_metadata["x-mindclade-lease-token"], "lease-token")
        for method, calls in captured.items():
            if method != COMMIT_WORKFLOW_TRANSITION:
                self.assertNotIn("x-mindclade-lease-token", dict(calls[0][1]))

    def test_scope_page_fence_and_lease_fail_before_transport(self) -> None:
        transport = FakeSyncTransport()
        client = Client(config(), transport=transport)
        with self.assertRaisesRegex(ValueError, "configured project"):
            client.workflows.get_run("tenants/other/projects/other/workflowRuns/run-1")
        with self.assertRaisesRegex(ValueError, "page size"):
            client.approvals.list(
                workflow_service_pb2.ListApprovalRequestsRequest(
                    page=pagination_pb2.PageRequest(page_size=201)
                )
            )
        with self.assertRaisesRegex(ValueError, "lease token"):
            client.workflows.commit_transition(transition(), lease_token="unsafe token")
        self.assertEqual(transport.calls, [])

    def test_watch_treats_zero_retry_after_as_immediate_retry(self) -> None:
        transport = FakeSyncTransport()
        attempts = 0

        def stream(request: Message, timeout: float, metadata: Metadata) -> Iterable[Message]:
            del timeout, metadata
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise UnavailableError(
                    "transient workflow stream failure",
                    retryable=True,
                    retry_after=0.0,
                )
            return watch_responses(request)

        transport.stream_handlers[WATCH_WORKFLOW_RUN] = stream
        client = Client(config(), transport=transport)
        runs = list(client.workflows.watch(RUN_NAME, timeout=1))
        self.assertEqual(attempts, 3)
        self.assertEqual(runs[-1].state, workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED)


class AsyncWorkflowApprovalTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_surface_covers_every_generated_rpc_and_watch_resume(self) -> None:
        transport = FakeAsyncTransport()

        def unary(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            return response_for(request)

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del timeout, metadata
            for value in watch_responses(request):
                yield value

        for method in UNARY_METHODS:
            transport.unary_handlers[method] = unary
        transport.stream_handlers[WATCH_WORKFLOW_RUN] = stream
        client = AsyncClient(config(), transport=transport)
        await client.workflows.create_definition(definition_create())
        await client.workflows.update_definition(definition_update())
        await client.workflows.get_definition(DEFINITION_NAME)
        await client.workflows.list_definitions()
        await client.workflows.start_run(run_start())
        await client.workflows.get_run(RUN_NAME)
        await client.workflows.list_runs()
        await client.workflows.cancel_run(
            workflow_service_pb2.CancelWorkflowRunRequest(
                name=RUN_NAME, etag="etag-run", reason="operator request"
            )
        )
        await client.workflows.commit_transition(transition(), lease_token="lease-token")
        self.assertEqual(
            [run.transition_sequence async for run in client.workflows.watch(RUN_NAME, timeout=1)],
            [1, 2],
        )
        await client.approvals.request(approval_request())
        await client.approvals.get(APPROVAL_NAME)
        await client.approvals.list()
        await client.approvals.decide(decision())
        await client.approvals.consume(consumption())
        self.assertTrue(set(UNARY_METHODS).issubset({call.method for call in transport.calls}))
        self.assertIn(WATCH_WORKFLOW_RUN, {call.method for call in transport.calls})

    async def test_async_cancellation_is_observed(self) -> None:
        transport = FakeAsyncTransport()
        cancellation = asyncio.Event()
        cancellation.set()
        client = AsyncClient(config(), transport=transport)
        with self.assertRaisesRegex(Exception, "cancelled"):
            async for _ in client.workflows.watch(RUN_NAME, timeout=1, cancellation=cancellation):
                self.fail("cancelled watch yielded a value")

    async def test_watch_treats_zero_retry_after_as_immediate_retry(self) -> None:
        transport = FakeAsyncTransport()
        attempts = 0

        async def stream(
            request: Message, timeout: float, metadata: Metadata
        ) -> AsyncIterator[Message]:
            del timeout, metadata
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise UnavailableError(
                    "transient workflow stream failure",
                    retryable=True,
                    retry_after=0.0,
                )
            for response in watch_responses(request):
                yield response

        transport.stream_handlers[WATCH_WORKFLOW_RUN] = stream
        client = AsyncClient(config(), transport=transport)
        runs = [run async for run in client.workflows.watch(RUN_NAME, timeout=1)]
        self.assertEqual(attempts, 3)
        self.assertEqual(runs[-1].state, workflow_run_pb2.WORKFLOW_RUN_STATE_SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
