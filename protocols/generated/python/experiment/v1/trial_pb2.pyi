import datetime

from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from artifact.v1 import evidence_reference_pb2 as _evidence_reference_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TrialState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TRIAL_STATE_UNSPECIFIED: _ClassVar[TrialState]
    TRIAL_STATE_CREATED: _ClassVar[TrialState]
    TRIAL_STATE_ADMITTED: _ClassVar[TrialState]
    TRIAL_STATE_RUNNING: _ClassVar[TrialState]
    TRIAL_STATE_COMPLETED: _ClassVar[TrialState]
    TRIAL_STATE_FAILED: _ClassVar[TrialState]
    TRIAL_STATE_CANCELLED: _ClassVar[TrialState]
    TRIAL_STATE_INVALID: _ClassVar[TrialState]

class TrialOutcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TRIAL_OUTCOME_UNSPECIFIED: _ClassVar[TrialOutcome]
    TRIAL_OUTCOME_SUCCEEDED: _ClassVar[TrialOutcome]
    TRIAL_OUTCOME_FAILED: _ClassVar[TrialOutcome]
    TRIAL_OUTCOME_INFEASIBLE: _ClassVar[TrialOutcome]
    TRIAL_OUTCOME_PRUNED: _ClassVar[TrialOutcome]
    TRIAL_OUTCOME_CANCELLED: _ClassVar[TrialOutcome]
TRIAL_STATE_UNSPECIFIED: TrialState
TRIAL_STATE_CREATED: TrialState
TRIAL_STATE_ADMITTED: TrialState
TRIAL_STATE_RUNNING: TrialState
TRIAL_STATE_COMPLETED: TrialState
TRIAL_STATE_FAILED: TrialState
TRIAL_STATE_CANCELLED: TrialState
TRIAL_STATE_INVALID: TrialState
TRIAL_OUTCOME_UNSPECIFIED: TrialOutcome
TRIAL_OUTCOME_SUCCEEDED: TrialOutcome
TRIAL_OUTCOME_FAILED: TrialOutcome
TRIAL_OUTCOME_INFEASIBLE: TrialOutcome
TRIAL_OUTCOME_PRUNED: TrialOutcome
TRIAL_OUTCOME_CANCELLED: TrialOutcome

class Trial(_message.Message):
    __slots__ = ("name", "uid", "revision", "etag", "tenant_name", "project_name", "study", "trial_number", "state", "outcome", "resolved_configuration", "execution", "result_manifest", "evidence", "error", "create_time", "start_time", "complete_time", "elapsed_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    TENANT_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    STUDY_FIELD_NUMBER: _ClassVar[int]
    TRIAL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    RESOLVED_CONFIGURATION_FIELD_NUMBER: _ClassVar[int]
    EXECUTION_FIELD_NUMBER: _ClassVar[int]
    RESULT_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_TIME_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    revision: int
    etag: str
    tenant_name: str
    project_name: str
    study: _resource_reference_pb2.ResourceRef
    trial_number: int
    state: TrialState
    outcome: TrialOutcome
    resolved_configuration: _artifact_reference_pb2.ArtifactRef
    execution: _resource_reference_pb2.ResourceRef
    result_manifest: _artifact_reference_pb2.ArtifactRef
    evidence: _containers.RepeatedCompositeFieldContainer[_evidence_reference_pb2.EvidenceRef]
    error: _error_detail_pb2.ErrorDetail
    create_time: _timestamp_pb2.Timestamp
    start_time: _timestamp_pb2.Timestamp
    complete_time: _timestamp_pb2.Timestamp
    elapsed_time: _duration_pb2.Duration
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., tenant_name: _Optional[str] = ..., project_name: _Optional[str] = ..., study: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., trial_number: _Optional[int] = ..., state: _Optional[_Union[TrialState, str]] = ..., outcome: _Optional[_Union[TrialOutcome, str]] = ..., resolved_configuration: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., execution: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., result_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., evidence: _Optional[_Iterable[_Union[_evidence_reference_pb2.EvidenceRef, _Mapping]]] = ..., error: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., complete_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., elapsed_time: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ...) -> None: ...
