from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from mindclade_internal_sdk import CallOptions, Client
from mindclade_internal_sdk.resources import (
    ACTIVE_AGENT_DEFINITION_STATE,
    APPROVED_APPROVAL_STATE,
    AgentBudgetEnvelope,
    AgentDefinition,
    AgentExecutionLimits,
    AgentRun,
    ApprovalBinding,
    ApprovalRequest,
    CancelAgentRunRequest,
    Duration,
    Operation,
    StartAgentRunRequest,
    Timestamp,
    artifact_reference,
    resource_reference,
)

from examples.agent_workflow.simulate import (
    BoundedAgentConfiguration,
    BoundedAgentWorkflow,
    load_configuration,
)


def _configuration() -> BoundedAgentConfiguration:
    directory = Path(__file__).resolve().parent
    return load_configuration(directory / "agent.yaml", directory / "workflow.yaml")


def _definition() -> AgentDefinition:
    configuration = _configuration()
    return AgentDefinition(
        name=configuration.definition_name,
        state=ACTIVE_AGENT_DEFINITION_STATE,
        definition=artifact_reference(
            digest=configuration.definition_document_digest,
            media_type="application/schema+json",
            size_bytes=100,
        ),
        eligible_tools=[
            resource_reference(name=name, resource_type="tool")
            for name in sorted(configuration.allowed_tools)
        ],
        budget=AgentBudgetEnvelope(
            maximum_model_tokens=4096,
            maximum_iterations=8,
            maximum_tool_calls=12,
            maximum_concurrent_branches=1,
            maximum_storage_bytes=16_777_216,
            maximum_external_spend_micros=0,
            maximum_wall_time=Duration(seconds=120),
        ),
        limits=AgentExecutionLimits(
            maximum_depth=2,
            maximum_fan_out=1,
            maximum_observations_per_step=8,
            maximum_artifact_references_per_call=4,
        ),
    )


def _approval() -> ApprovalRequest:
    configuration = _configuration()
    expiry = Timestamp()
    expiry.FromDatetime(datetime.now(UTC) + timedelta(minutes=5))
    return ApprovalRequest(
        name=configuration.approval_request_name,
        state=APPROVED_APPROVAL_STATE,
        binding=ApprovalBinding(
            action="agent.run.start",
            binding_digest=configuration.approval_binding_digest,
        ),
        minimum_independent_approvers=1,
        expire_time=expiry,
    )


class _FakeAgents:
    def __init__(self) -> None:
        self.definition = _definition()
        self.run = AgentRun(
            name="tenants/example-tenant/projects/example-project/agentRuns/run-1",
            revision=3,
            etag="etag-3",
        )
        self.starts: list[tuple[StartAgentRunRequest, CallOptions | None]] = []
        self.cancellations: list[tuple[CancelAgentRunRequest, CallOptions | None]] = []

    def get_definition(self, name: str) -> AgentDefinition:
        if name != self.definition.name:
            raise AssertionError(name)
        return copy.deepcopy(self.definition)

    def start_run(
        self,
        request: StartAgentRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> Operation:
        self.starts.append((copy.deepcopy(request), options))
        return Operation(operation_id="operations/start-1")

    def get_run(self, name: str) -> AgentRun:
        if name != self.run.name:
            raise AssertionError(name)
        return copy.deepcopy(self.run)

    def cancel_run(
        self,
        request: CancelAgentRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> Operation:
        self.cancellations.append((copy.deepcopy(request), options))
        return Operation(operation_id="operations/cancel-1")


class _FakeApprovals:
    def __init__(self) -> None:
        self.approval = _approval()

    def get(self, name: str) -> ApprovalRequest:
        if name != self.approval.name:
            raise AssertionError(name)
        return copy.deepcopy(self.approval)


class _FakeClient:
    def __init__(self) -> None:
        self.agents = _FakeAgents()
        self.approvals = _FakeApprovals()


class BoundedAgentWorkflowTest(unittest.TestCase):
    def test_start_status_and_cancel_remain_inside_sdk_and_declared_bounds(self) -> None:
        configuration = _configuration()
        fake = _FakeClient()
        workflow = BoundedAgentWorkflow(cast(Client, fake), configuration)

        started = workflow.start("run-1", idempotency_key="run-1-start")
        self.assertEqual(started.operation_id, "operations/start-1")
        request, options = fake.agents.starts[0]
        self.assertEqual(request.agent_run_id, "run-1")
        self.assertEqual(request.agent_run.definition.name, configuration.definition_name)
        self.assertEqual(
            request.agent_run.budget_reservation.name,
            configuration.budget_reservation_name,
        )
        self.assertEqual(request.agent_run.workflow_run.name, configuration.workflow_run_name)
        self.assertIsNotNone(options)
        assert options is not None
        self.assertEqual(options.idempotency_key, "run-1-start")

        self.assertEqual(workflow.status(fake.agents.run.name).revision, 3)
        cancelled = workflow.cancel(
            fake.agents.run.name,
            etag="etag-3",
            reason="operator stopped bounded analysis",
            idempotency_key="run-1-cancel",
        )
        self.assertEqual(cancelled.operation_id, "operations/cancel-1")
        cancellation, cancellation_options = fake.agents.cancellations[0]
        self.assertEqual(cancellation.etag, "etag-3")
        self.assertIsNotNone(cancellation_options)
        assert cancellation_options is not None
        self.assertEqual(cancellation_options.idempotency_key, "run-1-cancel")

    def test_tool_budget_and_approval_drift_fail_before_admission(self) -> None:
        for mutation in ("tool", "budget", "approval"):
            with self.subTest(mutation=mutation):
                fake = _FakeClient()
                if mutation == "tool":
                    del fake.agents.definition.eligible_tools[-1]
                elif mutation == "budget":
                    fake.agents.definition.budget.maximum_model_tokens += 1
                else:
                    fake.approvals.approval.ClearField("state")
                workflow = BoundedAgentWorkflow(cast(Client, fake), _configuration())
                with self.assertRaises(ValueError):
                    workflow.start("run-1", idempotency_key="run-1-start")
                self.assertEqual(fake.agents.starts, [])

    def test_configuration_is_closed_and_disables_prohibited_capabilities(self) -> None:
        directory = Path(__file__).resolve().parent
        agent = (directory / "agent.yaml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid = Path(temporary_directory) / "agent.yaml"
            invalid.write_text(agent.replace('"clinical_use": false', '"clinical_use": true'))
            with self.assertRaisesRegex(ValueError, "prohibited agent capabilities"):
                load_configuration(invalid, directory / "workflow.yaml")


if __name__ == "__main__":
    unittest.main()
