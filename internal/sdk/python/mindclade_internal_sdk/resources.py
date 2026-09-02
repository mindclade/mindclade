"""Factories and direct aliases for authoritative generated resource values.

Consumer applications import these names from the private SDK instead of
depending on generated-package locations.  Every returned object is still the
generated protobuf type; this module does not introduce another wire model.
"""

from __future__ import annotations

from datetime import UTC, datetime

from google.protobuf.duration_pb2 import Duration
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.agent.v1.agent_definition_pb2 import (
    AGENT_DEFINITION_STATE_ACTIVE,
    AgentBudgetEnvelope,
    AgentDefinition,
    AgentExecutionLimits,
)
from mindclade.agent.v1.agent_run_pb2 import AgentRun
from mindclade.artifact.v1.artifact_reference_pb2 import ArtifactRef
from mindclade.common.v1.resource_reference_pb2 import ResourceRef
from mindclade.internal.agent.v1.agent_service_pb2 import (
    CancelAgentRunRequest,
    StartAgentRunRequest,
)
from mindclade.job.v1.operation_pb2 import Operation
from mindclade.workflow.v1.approval_pb2 import (
    APPROVAL_STATE_APPROVED,
    ApprovalBinding,
    ApprovalRequest,
)

from ._validation import artifact_ref, required_text, resource_id, resource_ref

ACTIVE_AGENT_DEFINITION_STATE = AGENT_DEFINITION_STATE_ACTIVE
APPROVED_APPROVAL_STATE = APPROVAL_STATE_APPROVED


def artifact_reference(
    *,
    digest: str,
    media_type: str,
    size_bytes: int,
    artifact_kind: str = "",
    schema_id: str = "",
    integrity_digest: str = "",
    uri: str = "",
    schema_version: str = "",
) -> ArtifactRef:
    """Build and validate one generated immutable artifact reference."""

    value = ArtifactRef(
        digest=digest,
        media_type=media_type,
        size_bytes=size_bytes,
        artifact_kind=artifact_kind,
        schema_id=schema_id,
        integrity_digest=integrity_digest,
        uri=uri,
        schema_version=schema_version,
    )
    artifact_ref("artifact", value)
    return value


def resource_reference(
    *,
    name: str,
    resource_type: str,
    resource_id_value: str | None = None,
    tenant_id: str = "",
    project_id: str = "",
    resource_version: int = 0,
    etag: str = "",
) -> ResourceRef:
    """Build and validate one generated logical resource reference."""

    normalized_name = required_text("resource name", name, maximum=2048)
    identifier = resource_id("resource ID", resource_id_value or normalized_name.rsplit("/", 1)[-1])
    value = ResourceRef(
        resource_type=required_text("resource type", resource_type, maximum=256),
        resource_id=identifier,
        tenant_id=tenant_id,
        project_id=project_id,
        resource_version=resource_version,
        name=normalized_name,
        etag=etag,
    )
    resource_ref("resource", value)
    return value


def start_agent_run_request(
    *,
    agent_run_id: str,
    definition_name: str,
    budget_reservation_name: str,
    workflow_run_name: str | None = None,
    input_artifact: ArtifactRef | None = None,
) -> StartAgentRunRequest:
    """Build generated agent-run intent without exposing package layout."""

    run = AgentRun(
        definition=resource_reference(
            name=definition_name,
            resource_type="agent_definition",
        ),
        budget_reservation=resource_reference(
            name=budget_reservation_name,
            resource_type="budget_reservation",
        ),
    )
    if workflow_run_name is not None:
        run.workflow_run.CopyFrom(
            resource_reference(name=workflow_run_name, resource_type="workflow_run")
        )
    if input_artifact is not None:
        artifact_ref("agent input", input_artifact)
        run.input.CopyFrom(input_artifact)
    return StartAgentRunRequest(
        agent_run_id=resource_id("agent run ID", agent_run_id),
        agent_run=run,
    )


def cancel_agent_run_request(*, name: str, etag: str, reason: str) -> CancelAgentRunRequest:
    """Build generated cancellation intent under optimistic concurrency."""

    return CancelAgentRunRequest(
        name=required_text("agent run name", name, maximum=2048),
        etag=required_text("agent run ETag", etag, maximum=1024),
        reason=required_text("agent cancellation reason", reason, maximum=1024),
    )


def agent_definition_is_active(value: AgentDefinition) -> bool:
    """Return whether the generated definition is explicitly active."""

    return value.state == AGENT_DEFINITION_STATE_ACTIVE


def approval_is_current_and_approved(
    value: ApprovalRequest, *, now: datetime | None = None
) -> bool:
    """Fail closed unless approval is approved and has a future expiration."""

    if value.state != APPROVAL_STATE_APPROVED or not value.HasField("expire_time"):
        return False
    try:
        expiry = value.expire_time.ToDatetime(tzinfo=UTC)
    except (OverflowError, ValueError):
        return False
    return expiry > (now or datetime.now(UTC))


__all__ = [
    "ACTIVE_AGENT_DEFINITION_STATE",
    "APPROVED_APPROVAL_STATE",
    "AgentBudgetEnvelope",
    "AgentDefinition",
    "AgentExecutionLimits",
    "AgentRun",
    "ApprovalBinding",
    "ApprovalRequest",
    "ArtifactRef",
    "Duration",
    "Operation",
    "ResourceRef",
    "Timestamp",
    "agent_definition_is_active",
    "approval_is_current_and_approved",
    "artifact_reference",
    "cancel_agent_run_request",
    "resource_reference",
    "start_agent_run_request",
]
