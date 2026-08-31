import datetime

from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import command_context_pb2 as _command_context_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from policy.v1 import authorization_decision_pb2 as _authorization_decision_pb2
from workflow.v1 import approval_pb2 as _approval_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AgentStepKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AGENT_STEP_KIND_UNSPECIFIED: _ClassVar[AgentStepKind]
    AGENT_STEP_KIND_DECISION: _ClassVar[AgentStepKind]
    AGENT_STEP_KIND_TOOL: _ClassVar[AgentStepKind]
    AGENT_STEP_KIND_DOMAIN_JOB: _ClassVar[AgentStepKind]
    AGENT_STEP_KIND_APPROVAL: _ClassVar[AgentStepKind]
    AGENT_STEP_KIND_WAIT: _ClassVar[AgentStepKind]
    AGENT_STEP_KIND_TERMINAL: _ClassVar[AgentStepKind]

class AgentStepState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AGENT_STEP_STATE_UNSPECIFIED: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_CREATED: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_DISPATCHED: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_RUNNING: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_WAITING: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_SUCCEEDED: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_FAILED: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_CANCELLED: _ClassVar[AgentStepState]
    AGENT_STEP_STATE_EXPIRED: _ClassVar[AgentStepState]
AGENT_STEP_KIND_UNSPECIFIED: AgentStepKind
AGENT_STEP_KIND_DECISION: AgentStepKind
AGENT_STEP_KIND_TOOL: AgentStepKind
AGENT_STEP_KIND_DOMAIN_JOB: AgentStepKind
AGENT_STEP_KIND_APPROVAL: AgentStepKind
AGENT_STEP_KIND_WAIT: AgentStepKind
AGENT_STEP_KIND_TERMINAL: AgentStepKind
AGENT_STEP_STATE_UNSPECIFIED: AgentStepState
AGENT_STEP_STATE_CREATED: AgentStepState
AGENT_STEP_STATE_DISPATCHED: AgentStepState
AGENT_STEP_STATE_RUNNING: AgentStepState
AGENT_STEP_STATE_WAITING: AgentStepState
AGENT_STEP_STATE_SUCCEEDED: AgentStepState
AGENT_STEP_STATE_FAILED: AgentStepState
AGENT_STEP_STATE_CANCELLED: AgentStepState
AGENT_STEP_STATE_EXPIRED: AgentStepState

class ToolCall(_message.Message):
    __slots__ = ("context", "call_id", "agent_run_name", "agent_step_name", "tool", "tool_version", "authorization", "approvals", "input_digest", "parameters", "input_artifacts", "deadline", "budget_reservation", "expected_output_schema", "side_effect_class", "output_classification")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_RUN_NAME_FIELD_NUMBER: _ClassVar[int]
    AGENT_STEP_NAME_FIELD_NUMBER: _ClassVar[int]
    TOOL_FIELD_NUMBER: _ClassVar[int]
    TOOL_VERSION_FIELD_NUMBER: _ClassVar[int]
    AUTHORIZATION_FIELD_NUMBER: _ClassVar[int]
    APPROVALS_FIELD_NUMBER: _ClassVar[int]
    INPUT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    PARAMETERS_FIELD_NUMBER: _ClassVar[int]
    INPUT_ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    BUDGET_RESERVATION_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_OUTPUT_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    SIDE_EFFECT_CLASS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    call_id: str
    agent_run_name: str
    agent_step_name: str
    tool: _resource_reference_pb2.ResourceRef
    tool_version: str
    authorization: _authorization_decision_pb2.AuthorizationDecision
    approvals: _containers.RepeatedCompositeFieldContainer[_approval_pb2.ApprovalReceipt]
    input_digest: str
    parameters: _artifact_reference_pb2.ArtifactRef
    input_artifacts: _containers.RepeatedCompositeFieldContainer[_artifact_reference_pb2.ArtifactRef]
    deadline: _timestamp_pb2.Timestamp
    budget_reservation: _resource_reference_pb2.ResourceRef
    expected_output_schema: _artifact_reference_pb2.ArtifactRef
    side_effect_class: str
    output_classification: str
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., call_id: _Optional[str] = ..., agent_run_name: _Optional[str] = ..., agent_step_name: _Optional[str] = ..., tool: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., tool_version: _Optional[str] = ..., authorization: _Optional[_Union[_authorization_decision_pb2.AuthorizationDecision, _Mapping]] = ..., approvals: _Optional[_Iterable[_Union[_approval_pb2.ApprovalReceipt, _Mapping]]] = ..., input_digest: _Optional[str] = ..., parameters: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., input_artifacts: _Optional[_Iterable[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]]] = ..., deadline: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., budget_reservation: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., expected_output_schema: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., side_effect_class: _Optional[str] = ..., output_classification: _Optional[str] = ...) -> None: ...

class AgentWait(_message.Message):
    __slots__ = ("maximum_duration", "correlation_ref")
    MAXIMUM_DURATION_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_REF_FIELD_NUMBER: _ClassVar[int]
    maximum_duration: _duration_pb2.Duration
    correlation_ref: str
    def __init__(self, maximum_duration: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., correlation_ref: _Optional[str] = ...) -> None: ...

class AgentDecision(_message.Message):
    __slots__ = ("decision_id", "decision_type", "rationale_summary", "evidence", "tool_call", "domain_job", "approval_request", "wait", "terminal_result", "replay_digest")
    DECISION_ID_FIELD_NUMBER: _ClassVar[int]
    DECISION_TYPE_FIELD_NUMBER: _ClassVar[int]
    RATIONALE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_JOB_FIELD_NUMBER: _ClassVar[int]
    APPROVAL_REQUEST_FIELD_NUMBER: _ClassVar[int]
    WAIT_FIELD_NUMBER: _ClassVar[int]
    TERMINAL_RESULT_FIELD_NUMBER: _ClassVar[int]
    REPLAY_DIGEST_FIELD_NUMBER: _ClassVar[int]
    decision_id: str
    decision_type: str
    rationale_summary: str
    evidence: _containers.RepeatedCompositeFieldContainer[_artifact_reference_pb2.ArtifactRef]
    tool_call: ToolCall
    domain_job: _resource_reference_pb2.ResourceRef
    approval_request: _resource_reference_pb2.ResourceRef
    wait: AgentWait
    terminal_result: _artifact_reference_pb2.ArtifactRef
    replay_digest: str
    def __init__(self, decision_id: _Optional[str] = ..., decision_type: _Optional[str] = ..., rationale_summary: _Optional[str] = ..., evidence: _Optional[_Iterable[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]]] = ..., tool_call: _Optional[_Union[ToolCall, _Mapping]] = ..., domain_job: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., approval_request: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., wait: _Optional[_Union[AgentWait, _Mapping]] = ..., terminal_result: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., replay_digest: _Optional[str] = ...) -> None: ...

class AgentStep(_message.Message):
    __slots__ = ("name", "uid", "run", "sequence", "revision", "etag", "kind", "state", "attempt_id", "lease_epoch", "policy_decisions", "observations", "decision", "output", "failure", "create_time", "update_time", "end_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    RUN_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_EPOCH_FIELD_NUMBER: _ClassVar[int]
    POLICY_DECISIONS_FIELD_NUMBER: _ClassVar[int]
    OBSERVATIONS_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    FAILURE_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    run: _resource_reference_pb2.ResourceRef
    sequence: int
    revision: int
    etag: str
    kind: AgentStepKind
    state: AgentStepState
    attempt_id: str
    lease_epoch: int
    policy_decisions: _containers.RepeatedCompositeFieldContainer[_authorization_decision_pb2.AuthorizationDecision]
    observations: _containers.RepeatedCompositeFieldContainer[_artifact_reference_pb2.ArtifactRef]
    decision: AgentDecision
    output: _artifact_reference_pb2.ArtifactRef
    failure: _error_detail_pb2.ErrorDetail
    create_time: _timestamp_pb2.Timestamp
    update_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., run: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., sequence: _Optional[int] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., kind: _Optional[_Union[AgentStepKind, str]] = ..., state: _Optional[_Union[AgentStepState, str]] = ..., attempt_id: _Optional[str] = ..., lease_epoch: _Optional[int] = ..., policy_decisions: _Optional[_Iterable[_Union[_authorization_decision_pb2.AuthorizationDecision, _Mapping]]] = ..., observations: _Optional[_Iterable[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]]] = ..., decision: _Optional[_Union[AgentDecision, _Mapping]] = ..., output: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., failure: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
