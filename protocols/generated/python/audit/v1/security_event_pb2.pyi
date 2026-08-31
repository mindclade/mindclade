from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class SecurityEvent(_message.Message):
    __slots__ = ("severity", "control", "evidence_digest")
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    CONTROL_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_DIGEST_FIELD_NUMBER: _ClassVar[int]
    severity: str
    control: str
    evidence_digest: str
    def __init__(self, severity: _Optional[str] = ..., control: _Optional[str] = ..., evidence_digest: _Optional[str] = ...) -> None: ...
