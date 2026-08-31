import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LeaseFence(_message.Message):
    __slots__ = ("job_id", "run_id", "attempt_id", "lease_epoch", "deadline", "tenant_id", "project_id", "lease_token_digest")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_EPOCH_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_TOKEN_DIGEST_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    run_id: str
    attempt_id: str
    lease_epoch: int
    deadline: _timestamp_pb2.Timestamp
    tenant_id: str
    project_id: str
    lease_token_digest: str
    def __init__(self, job_id: _Optional[str] = ..., run_id: _Optional[str] = ..., attempt_id: _Optional[str] = ..., lease_epoch: _Optional[int] = ..., deadline: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., tenant_id: _Optional[str] = ..., project_id: _Optional[str] = ..., lease_token_digest: _Optional[str] = ...) -> None: ...
