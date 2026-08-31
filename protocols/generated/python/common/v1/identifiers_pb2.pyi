from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Identifiers(_message.Message):
    __slots__ = ("tenant_id", "project_id", "principal_id", "request_id", "trace_id")
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    PRINCIPAL_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    tenant_id: str
    project_id: str
    principal_id: str
    request_id: str
    trace_id: str
    def __init__(self, tenant_id: _Optional[str] = ..., project_id: _Optional[str] = ..., principal_id: _Optional[str] = ..., request_id: _Optional[str] = ..., trace_id: _Optional[str] = ...) -> None: ...
