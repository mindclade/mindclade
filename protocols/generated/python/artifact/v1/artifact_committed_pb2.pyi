from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ArtifactCommitted(_message.Message):
    __slots__ = ("artifact", "producer_attempt_id")
    ARTIFACT_FIELD_NUMBER: _ClassVar[int]
    PRODUCER_ATTEMPT_ID_FIELD_NUMBER: _ClassVar[int]
    artifact: _artifact_reference_pb2.ArtifactRef
    producer_attempt_id: str
    def __init__(self, artifact: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., producer_attempt_id: _Optional[str] = ...) -> None: ...
