from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class AttemptLeased(_message.Message):
    __slots__ = ("attempt_id", "lease_epoch", "lease_expires_at_utc")
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_EPOCH_FIELD_NUMBER: _ClassVar[int]
    LEASE_EXPIRES_AT_UTC_FIELD_NUMBER: _ClassVar[int]
    attempt_id: str
    lease_epoch: int
    lease_expires_at_utc: str
    def __init__(self, attempt_id: _Optional[str] = ..., lease_epoch: _Optional[int] = ..., lease_expires_at_utc: _Optional[str] = ...) -> None: ...
