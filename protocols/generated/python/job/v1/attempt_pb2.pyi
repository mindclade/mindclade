import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AttemptState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ATTEMPT_STATE_UNSPECIFIED: _ClassVar[AttemptState]
    ATTEMPT_STATE_LEASED: _ClassVar[AttemptState]
    ATTEMPT_STATE_RUNNING: _ClassVar[AttemptState]
    ATTEMPT_STATE_SUCCEEDED: _ClassVar[AttemptState]
    ATTEMPT_STATE_FAILED: _ClassVar[AttemptState]
    ATTEMPT_STATE_CANCELLED: _ClassVar[AttemptState]
    ATTEMPT_STATE_FENCED: _ClassVar[AttemptState]
    ATTEMPT_STATE_TIMED_OUT: _ClassVar[AttemptState]
ATTEMPT_STATE_UNSPECIFIED: AttemptState
ATTEMPT_STATE_LEASED: AttemptState
ATTEMPT_STATE_RUNNING: AttemptState
ATTEMPT_STATE_SUCCEEDED: AttemptState
ATTEMPT_STATE_FAILED: AttemptState
ATTEMPT_STATE_CANCELLED: AttemptState
ATTEMPT_STATE_FENCED: AttemptState
ATTEMPT_STATE_TIMED_OUT: AttemptState

class Attempt(_message.Message):
    __slots__ = ("attempt_id", "run_id", "lease_epoch", "state", "lease_expires_at", "tenant_id", "project_id", "job_id", "worker_id", "leased_at", "started_at", "completed_at", "outputs", "error", "resource_version")
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_EPOCH_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    LEASE_EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    WORKER_ID_FIELD_NUMBER: _ClassVar[int]
    LEASED_AT_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_VERSION_FIELD_NUMBER: _ClassVar[int]
    attempt_id: str
    run_id: str
    lease_epoch: int
    state: AttemptState
    lease_expires_at: _timestamp_pb2.Timestamp
    tenant_id: str
    project_id: str
    job_id: str
    worker_id: str
    leased_at: _timestamp_pb2.Timestamp
    started_at: _timestamp_pb2.Timestamp
    completed_at: _timestamp_pb2.Timestamp
    outputs: _containers.RepeatedCompositeFieldContainer[_artifact_reference_pb2.ArtifactRef]
    error: _error_detail_pb2.ErrorDetail
    resource_version: int
    def __init__(self, attempt_id: _Optional[str] = ..., run_id: _Optional[str] = ..., lease_epoch: _Optional[int] = ..., state: _Optional[_Union[AttemptState, str]] = ..., lease_expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., tenant_id: _Optional[str] = ..., project_id: _Optional[str] = ..., job_id: _Optional[str] = ..., worker_id: _Optional[str] = ..., leased_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., outputs: _Optional[_Iterable[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]]] = ..., error: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., resource_version: _Optional[int] = ...) -> None: ...
