import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from job.v1 import lease_fencing_pb2 as _lease_fencing_pb2
from training.v1 import training_progress_pb2 as _training_progress_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TrainingRunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TRAINING_RUN_STATE_UNSPECIFIED: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_CREATED: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_VALIDATING: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_ADMITTED: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_RUNNING: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_CHECKPOINTING: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_RECOVERING: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_DRAINING: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_COMPLETED: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_FAILED: _ClassVar[TrainingRunState]
    TRAINING_RUN_STATE_CANCELLED: _ClassVar[TrainingRunState]

class TrainingTerminalClassification(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_CANCELLED: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_POLICY_DENIED: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_INVALID_INPUT: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_RESOURCE_EXHAUSTED: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_TRANSIENT_FAILURE: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_EXECUTION_FAILURE: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_NUMERICAL_FAILURE: _ClassVar[TrainingTerminalClassification]
    TRAINING_TERMINAL_CLASSIFICATION_STALE_FENCE: _ClassVar[TrainingTerminalClassification]
TRAINING_RUN_STATE_UNSPECIFIED: TrainingRunState
TRAINING_RUN_STATE_CREATED: TrainingRunState
TRAINING_RUN_STATE_VALIDATING: TrainingRunState
TRAINING_RUN_STATE_ADMITTED: TrainingRunState
TRAINING_RUN_STATE_RUNNING: TrainingRunState
TRAINING_RUN_STATE_CHECKPOINTING: TrainingRunState
TRAINING_RUN_STATE_RECOVERING: TrainingRunState
TRAINING_RUN_STATE_DRAINING: TrainingRunState
TRAINING_RUN_STATE_COMPLETED: TrainingRunState
TRAINING_RUN_STATE_FAILED: TrainingRunState
TRAINING_RUN_STATE_CANCELLED: TrainingRunState
TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_CANCELLED: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_POLICY_DENIED: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_INVALID_INPUT: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_RESOURCE_EXHAUSTED: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_TRANSIENT_FAILURE: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_EXECUTION_FAILURE: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_NUMERICAL_FAILURE: TrainingTerminalClassification
TRAINING_TERMINAL_CLASSIFICATION_STALE_FENCE: TrainingTerminalClassification

class TrainingRun(_message.Message):
    __slots__ = ("name", "uid", "revision", "etag", "tenant_name", "project_name", "state", "training_recipe", "dataset_release", "model_release", "executable_plan", "hardware_topology", "use_policy", "active_fence", "committed_progress", "latest_checkpoint", "result_manifest", "terminal_classification", "error", "labels", "policy_classification", "create_time", "start_time", "complete_time")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    TENANT_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    TRAINING_RECIPE_FIELD_NUMBER: _ClassVar[int]
    DATASET_RELEASE_FIELD_NUMBER: _ClassVar[int]
    MODEL_RELEASE_FIELD_NUMBER: _ClassVar[int]
    EXECUTABLE_PLAN_FIELD_NUMBER: _ClassVar[int]
    HARDWARE_TOPOLOGY_FIELD_NUMBER: _ClassVar[int]
    USE_POLICY_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FENCE_FIELD_NUMBER: _ClassVar[int]
    COMMITTED_PROGRESS_FIELD_NUMBER: _ClassVar[int]
    LATEST_CHECKPOINT_FIELD_NUMBER: _ClassVar[int]
    RESULT_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    TERMINAL_CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    POLICY_CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    revision: int
    etag: str
    tenant_name: str
    project_name: str
    state: TrainingRunState
    training_recipe: _artifact_reference_pb2.ArtifactRef
    dataset_release: _resource_reference_pb2.ResourceRef
    model_release: _resource_reference_pb2.ResourceRef
    executable_plan: _artifact_reference_pb2.ArtifactRef
    hardware_topology: _artifact_reference_pb2.ArtifactRef
    use_policy: _resource_reference_pb2.ResourceRef
    active_fence: _lease_fencing_pb2.LeaseFence
    committed_progress: _training_progress_pb2.TrainingProgress
    latest_checkpoint: _resource_reference_pb2.ResourceRef
    result_manifest: _artifact_reference_pb2.ArtifactRef
    terminal_classification: TrainingTerminalClassification
    error: _error_detail_pb2.ErrorDetail
    labels: _containers.ScalarMap[str, str]
    policy_classification: str
    create_time: _timestamp_pb2.Timestamp
    start_time: _timestamp_pb2.Timestamp
    complete_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., tenant_name: _Optional[str] = ..., project_name: _Optional[str] = ..., state: _Optional[_Union[TrainingRunState, str]] = ..., training_recipe: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., dataset_release: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., model_release: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., executable_plan: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., hardware_topology: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., use_policy: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., active_fence: _Optional[_Union[_lease_fencing_pb2.LeaseFence, _Mapping]] = ..., committed_progress: _Optional[_Union[_training_progress_pb2.TrainingProgress, _Mapping]] = ..., latest_checkpoint: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., result_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., terminal_classification: _Optional[_Union[TrainingTerminalClassification, str]] = ..., error: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., labels: _Optional[_Mapping[str, str]] = ..., policy_classification: _Optional[str] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., complete_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
