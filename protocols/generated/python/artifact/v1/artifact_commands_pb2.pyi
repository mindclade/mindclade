from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import command_context_pb2 as _command_context_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CommitArtifactCommand(_message.Message):
    __slots__ = ("context", "artifact", "staging_receipt_digest")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    STAGING_RECEIPT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    artifact: _artifact_reference_pb2.ArtifactRef
    staging_receipt_digest: str
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., artifact: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., staging_receipt_digest: _Optional[str] = ...) -> None: ...
