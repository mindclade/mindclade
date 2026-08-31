import datetime

from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from policy.v1 import policy_reference_pb2 as _policy_reference_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AgentDefinitionState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AGENT_DEFINITION_STATE_UNSPECIFIED: _ClassVar[AgentDefinitionState]
    AGENT_DEFINITION_STATE_DRAFT: _ClassVar[AgentDefinitionState]
    AGENT_DEFINITION_STATE_ACTIVE: _ClassVar[AgentDefinitionState]
    AGENT_DEFINITION_STATE_DEPRECATED: _ClassVar[AgentDefinitionState]
    AGENT_DEFINITION_STATE_REVOKED: _ClassVar[AgentDefinitionState]
    AGENT_DEFINITION_STATE_ARCHIVED: _ClassVar[AgentDefinitionState]
AGENT_DEFINITION_STATE_UNSPECIFIED: AgentDefinitionState
AGENT_DEFINITION_STATE_DRAFT: AgentDefinitionState
AGENT_DEFINITION_STATE_ACTIVE: AgentDefinitionState
AGENT_DEFINITION_STATE_DEPRECATED: AgentDefinitionState
AGENT_DEFINITION_STATE_REVOKED: AgentDefinitionState
AGENT_DEFINITION_STATE_ARCHIVED: AgentDefinitionState

class AgentBudgetEnvelope(_message.Message):
    __slots__ = ("maximum_model_tokens", "maximum_iterations", "maximum_tool_calls", "maximum_concurrent_branches", "maximum_storage_bytes", "maximum_external_spend_micros", "maximum_wall_time", "maximum_accelerator_time", "maximum_cpu_time")
    MAXIMUM_MODEL_TOKENS_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_ITERATIONS_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_CONCURRENT_BRANCHES_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_STORAGE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_EXTERNAL_SPEND_MICROS_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_WALL_TIME_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_ACCELERATOR_TIME_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_CPU_TIME_FIELD_NUMBER: _ClassVar[int]
    maximum_model_tokens: int
    maximum_iterations: int
    maximum_tool_calls: int
    maximum_concurrent_branches: int
    maximum_storage_bytes: int
    maximum_external_spend_micros: int
    maximum_wall_time: _duration_pb2.Duration
    maximum_accelerator_time: _duration_pb2.Duration
    maximum_cpu_time: _duration_pb2.Duration
    def __init__(self, maximum_model_tokens: _Optional[int] = ..., maximum_iterations: _Optional[int] = ..., maximum_tool_calls: _Optional[int] = ..., maximum_concurrent_branches: _Optional[int] = ..., maximum_storage_bytes: _Optional[int] = ..., maximum_external_spend_micros: _Optional[int] = ..., maximum_wall_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., maximum_accelerator_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., maximum_cpu_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class AgentExecutionLimits(_message.Message):
    __slots__ = ("maximum_depth", "maximum_fan_out", "maximum_observations_per_step", "maximum_artifact_references_per_call")
    MAXIMUM_DEPTH_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_FAN_OUT_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_OBSERVATIONS_PER_STEP_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_ARTIFACT_REFERENCES_PER_CALL_FIELD_NUMBER: _ClassVar[int]
    maximum_depth: int
    maximum_fan_out: int
    maximum_observations_per_step: int
    maximum_artifact_references_per_call: int
    def __init__(self, maximum_depth: _Optional[int] = ..., maximum_fan_out: _Optional[int] = ..., maximum_observations_per_step: _Optional[int] = ..., maximum_artifact_references_per_call: _Optional[int] = ...) -> None: ...

class AgentDefinition(_message.Message):
    __slots__ = ("name", "uid", "revision", "etag", "tenant_id", "project_id", "display_name", "semantic_version", "state", "purpose", "non_goals", "definition", "workflow_definition", "eligible_tools", "policy_snapshots", "input_schema", "output_schema", "model_capability", "evaluation_suite", "budget", "limits", "qualification_level", "create_time", "update_time", "delete_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_VERSION_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PURPOSE_FIELD_NUMBER: _ClassVar[int]
    NON_GOALS_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_FIELD_NUMBER: _ClassVar[int]
    WORKFLOW_DEFINITION_FIELD_NUMBER: _ClassVar[int]
    ELIGIBLE_TOOLS_FIELD_NUMBER: _ClassVar[int]
    POLICY_SNAPSHOTS_FIELD_NUMBER: _ClassVar[int]
    INPUT_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_SCHEMA_FIELD_NUMBER: _ClassVar[int]
    MODEL_CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    EVALUATION_SUITE_FIELD_NUMBER: _ClassVar[int]
    BUDGET_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    QUALIFICATION_LEVEL_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
    DELETE_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    revision: int
    etag: str
    tenant_id: str
    project_id: str
    display_name: str
    semantic_version: str
    state: AgentDefinitionState
    purpose: str
    non_goals: _containers.RepeatedScalarFieldContainer[str]
    definition: _artifact_reference_pb2.ArtifactRef
    workflow_definition: _resource_reference_pb2.ResourceRef
    eligible_tools: _containers.RepeatedCompositeFieldContainer[_resource_reference_pb2.ResourceRef]
    policy_snapshots: _containers.RepeatedCompositeFieldContainer[_policy_reference_pb2.PolicyReference]
    input_schema: _artifact_reference_pb2.ArtifactRef
    output_schema: _artifact_reference_pb2.ArtifactRef
    model_capability: str
    evaluation_suite: _resource_reference_pb2.ResourceRef
    budget: AgentBudgetEnvelope
    limits: AgentExecutionLimits
    qualification_level: str
    create_time: _timestamp_pb2.Timestamp
    update_time: _timestamp_pb2.Timestamp
    delete_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., tenant_id: _Optional[str] = ..., project_id: _Optional[str] = ..., display_name: _Optional[str] = ..., semantic_version: _Optional[str] = ..., state: _Optional[_Union[AgentDefinitionState, str]] = ..., purpose: _Optional[str] = ..., non_goals: _Optional[_Iterable[str]] = ..., definition: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., workflow_definition: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., eligible_tools: _Optional[_Iterable[_Union[_resource_reference_pb2.ResourceRef, _Mapping]]] = ..., policy_snapshots: _Optional[_Iterable[_Union[_policy_reference_pb2.PolicyReference, _Mapping]]] = ..., input_schema: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., output_schema: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., model_capability: _Optional[str] = ..., evaluation_suite: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., budget: _Optional[_Union[AgentBudgetEnvelope, _Mapping]] = ..., limits: _Optional[_Union[AgentExecutionLimits, _Mapping]] = ..., qualification_level: _Optional[str] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., update_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., delete_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
