import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class OperationState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OPERATION_STATE_UNSPECIFIED: _ClassVar[OperationState]
    OPERATION_STATE_PENDING: _ClassVar[OperationState]
    OPERATION_STATE_RUNNING: _ClassVar[OperationState]
    OPERATION_STATE_SUCCEEDED: _ClassVar[OperationState]
    OPERATION_STATE_FAILED: _ClassVar[OperationState]
    OPERATION_STATE_CANCELLING: _ClassVar[OperationState]
    OPERATION_STATE_CANCELLED: _ClassVar[OperationState]
OPERATION_STATE_UNSPECIFIED: OperationState
OPERATION_STATE_PENDING: OperationState
OPERATION_STATE_RUNNING: OperationState
OPERATION_STATE_SUCCEEDED: OperationState
OPERATION_STATE_FAILED: OperationState
OPERATION_STATE_CANCELLING: OperationState
OPERATION_STATE_CANCELLED: OperationState

class Operation(_message.Message):
    __slots__ = ("operation_id", "tenant_id", "state", "resource_version", "result", "error", "project_id", "job_id", "created_at", "updated_at", "done", "etag")
    OPERATION_ID_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_VERSION_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    DONE_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    operation_id: str
    tenant_id: str
    state: OperationState
    resource_version: int
    result: _artifact_reference_pb2.ArtifactRef
    error: _error_detail_pb2.ErrorDetail
    project_id: str
    job_id: str
    created_at: _timestamp_pb2.Timestamp
    updated_at: _timestamp_pb2.Timestamp
    done: bool
    etag: str
    def __init__(self, operation_id: _Optional[str] = ..., tenant_id: _Optional[str] = ..., state: _Optional[_Union[OperationState, str]] = ..., resource_version: _Optional[int] = ..., result: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., error: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., project_id: _Optional[str] = ..., job_id: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., done: _Optional[bool] = ..., etag: _Optional[str] = ...) -> None: ...
