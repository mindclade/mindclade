import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import command_context_pb2 as _command_context_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from feature.v1 import feature_materialization_pb2 as _feature_materialization_pb2
from job.v1 import lease_fencing_pb2 as _lease_fencing_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FeatureSchedulingHint(_message.Message):
    __slots__ = ("key", "value")
    KEY_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    key: str
    value: str
    def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

class MaterializeFeaturesCommand(_message.Message):
    __slots__ = ("context", "project", "materialization_id", "feature_plan", "transform_execution_plan", "fence", "deadline", "delegated_capability", "scheduling_hints")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    MATERIALIZATION_ID_FIELD_NUMBER: _ClassVar[int]
    FEATURE_PLAN_FIELD_NUMBER: _ClassVar[int]
    TRANSFORM_EXECUTION_PLAN_FIELD_NUMBER: _ClassVar[int]
    FENCE_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    DELEGATED_CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    SCHEDULING_HINTS_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    project: _resource_reference_pb2.ResourceRef
    materialization_id: str
    feature_plan: _artifact_reference_pb2.ArtifactRef
    transform_execution_plan: _artifact_reference_pb2.ArtifactRef
    fence: _lease_fencing_pb2.LeaseFence
    deadline: _timestamp_pb2.Timestamp
    delegated_capability: _resource_reference_pb2.ResourceRef
    scheduling_hints: _containers.RepeatedCompositeFieldContainer[FeatureSchedulingHint]
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., project: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., materialization_id: _Optional[str] = ..., feature_plan: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., transform_execution_plan: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., fence: _Optional[_Union[_lease_fencing_pb2.LeaseFence, _Mapping]] = ..., deadline: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., delegated_capability: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., scheduling_hints: _Optional[_Iterable[_Union[FeatureSchedulingHint, _Mapping]]] = ...) -> None: ...

class CommitFeatureMaterializationCommand(_message.Message):
    __slots__ = ("context", "materialization_name", "fence", "classification", "receipt", "output_refs", "error", "completed_at")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    MATERIALIZATION_NAME_FIELD_NUMBER: _ClassVar[int]
    FENCE_FIELD_NUMBER: _ClassVar[int]
    CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_REFS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    materialization_name: str
    fence: _lease_fencing_pb2.LeaseFence
    classification: _feature_materialization_pb2.FeatureMaterializationTerminalClassification
    receipt: _artifact_reference_pb2.ArtifactRef
    output_refs: _containers.RepeatedCompositeFieldContainer[_artifact_reference_pb2.ArtifactRef]
    error: _error_detail_pb2.ErrorDetail
    completed_at: _timestamp_pb2.Timestamp
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., materialization_name: _Optional[str] = ..., fence: _Optional[_Union[_lease_fencing_pb2.LeaseFence, _Mapping]] = ..., classification: _Optional[_Union[_feature_materialization_pb2.FeatureMaterializationTerminalClassification, str]] = ..., receipt: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., output_refs: _Optional[_Iterable[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]]] = ..., error: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class CancelFeatureMaterializationCommand(_message.Message):
    __slots__ = ("context", "materialization_name", "etag", "reason")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    MATERIALIZATION_NAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    materialization_name: str
    etag: str
    reason: str
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., materialization_name: _Optional[str] = ..., etag: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...
