from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class AttemptCompleted(_message.Message):
    __slots__ = ("attempt_id", "lease_epoch", "result_digest", "completion_receipt_digest")
    ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    LEASE_EPOCH_FIELD_NUMBER: _ClassVar[int]
    RESULT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_RECEIPT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    attempt_id: str
    lease_epoch: int
    result_digest: str
    completion_receipt_digest: str
    def __init__(self, attempt_id: _Optional[str] = ..., lease_epoch: _Optional[int] = ..., result_digest: _Optional[str] = ..., completion_receipt_digest: _Optional[str] = ...) -> None: ...
