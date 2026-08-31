from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class AuditEvent(_message.Message):
    __slots__ = ("actor_principal_id", "action", "decision", "policy_digest")
    ACTOR_PRINCIPAL_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    POLICY_DIGEST_FIELD_NUMBER: _ClassVar[int]
    actor_principal_id: str
    action: str
    decision: str
    policy_digest: str
    def __init__(self, actor_principal_id: _Optional[str] = ..., action: _Optional[str] = ..., decision: _Optional[str] = ..., policy_digest: _Optional[str] = ...) -> None: ...
