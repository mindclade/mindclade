import datetime

from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StudyType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STUDY_TYPE_UNSPECIFIED: _ClassVar[StudyType]
    STUDY_TYPE_SCIENTIFIC: _ClassVar[StudyType]
    STUDY_TYPE_SYSTEMS: _ClassVar[StudyType]

class StudyState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STUDY_STATE_UNSPECIFIED: _ClassVar[StudyState]
    STUDY_STATE_CREATED: _ClassVar[StudyState]
    STUDY_STATE_RUNNING: _ClassVar[StudyState]
    STUDY_STATE_PAUSED: _ClassVar[StudyState]
    STUDY_STATE_COMPLETED: _ClassVar[StudyState]
    STUDY_STATE_CANCELLED: _ClassVar[StudyState]
    STUDY_STATE_FAILED: _ClassVar[StudyState]
STUDY_TYPE_UNSPECIFIED: StudyType
STUDY_TYPE_SCIENTIFIC: StudyType
STUDY_TYPE_SYSTEMS: StudyType
STUDY_STATE_UNSPECIFIED: StudyState
STUDY_STATE_CREATED: StudyState
STUDY_STATE_RUNNING: StudyState
STUDY_STATE_PAUSED: StudyState
STUDY_STATE_COMPLETED: StudyState
STUDY_STATE_CANCELLED: StudyState
STUDY_STATE_FAILED: StudyState

class StudyBudget(_message.Message):
    __slots__ = ("maximum_trials", "maximum_parallel_trials", "maximum_duration")
    MAXIMUM_TRIALS_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_PARALLEL_TRIALS_FIELD_NUMBER: _ClassVar[int]
    MAXIMUM_DURATION_FIELD_NUMBER: _ClassVar[int]
    maximum_trials: int
    maximum_parallel_trials: int
    maximum_duration: _duration_pb2.Duration
    def __init__(self, maximum_trials: _Optional[int] = ..., maximum_parallel_trials: _Optional[int] = ..., maximum_duration: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...

class Study(_message.Message):
    __slots__ = ("name", "uid", "revision", "etag", "tenant_name", "project_name", "experiment", "type", "state", "study_manifest", "base_configuration", "search_space", "objective_specification", "budget", "admitted_trial_count", "completed_trial_count", "create_time", "start_time", "complete_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    TENANT_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    EXPERIMENT_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    STUDY_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    BASE_CONFIGURATION_FIELD_NUMBER: _ClassVar[int]
    SEARCH_SPACE_FIELD_NUMBER: _ClassVar[int]
    OBJECTIVE_SPECIFICATION_FIELD_NUMBER: _ClassVar[int]
    BUDGET_FIELD_NUMBER: _ClassVar[int]
    ADMITTED_TRIAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_TRIAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    revision: int
    etag: str
    tenant_name: str
    project_name: str
    experiment: _resource_reference_pb2.ResourceRef
    type: StudyType
    state: StudyState
    study_manifest: _artifact_reference_pb2.ArtifactRef
    base_configuration: _artifact_reference_pb2.ArtifactRef
    search_space: _artifact_reference_pb2.ArtifactRef
    objective_specification: _artifact_reference_pb2.ArtifactRef
    budget: StudyBudget
    admitted_trial_count: int
    completed_trial_count: int
    create_time: _timestamp_pb2.Timestamp
    start_time: _timestamp_pb2.Timestamp
    complete_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., tenant_name: _Optional[str] = ..., project_name: _Optional[str] = ..., experiment: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., type: _Optional[_Union[StudyType, str]] = ..., state: _Optional[_Union[StudyState, str]] = ..., study_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., base_configuration: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., search_space: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., objective_specification: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., budget: _Optional[_Union[StudyBudget, _Mapping]] = ..., admitted_trial_count: _Optional[int] = ..., completed_trial_count: _Optional[int] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., complete_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
