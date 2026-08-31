import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CommandContext(_message.Message):
    __slots__ = ("request_id", "idempotency_key", "principal_id", "trace_id", "deadline", "canonical_request_digest", "tenant_id", "project_id", "correlation_id", "causation_id", "cancellation_token_id")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    PRINCIPAL_ID_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    CANONICAL_REQUEST_DIGEST_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    CAUSATION_ID_FIELD_NUMBER: _ClassVar[int]
    CANCELLATION_TOKEN_ID_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    idempotency_key: str
    principal_id: str
    trace_id: str
    deadline: _timestamp_pb2.Timestamp
    canonical_request_digest: str
    tenant_id: str
    project_id: str
    correlation_id: str
    causation_id: str
    cancellation_token_id: str
    def __init__(self, request_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., principal_id: _Optional[str] = ..., trace_id: _Optional[str] = ..., deadline: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., canonical_request_digest: _Optional[str] = ..., tenant_id: _Optional[str] = ..., project_id: _Optional[str] = ..., correlation_id: _Optional[str] = ..., causation_id: _Optional[str] = ..., cancellation_token_id: _Optional[str] = ...) -> None: ...
