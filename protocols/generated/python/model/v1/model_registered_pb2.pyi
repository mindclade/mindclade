import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ModelRegistered(_message.Message):
    __slots__ = ("model_name", "model_uid", "model_revision", "family", "definition_manifest", "feature_requirement_set", "model_feature_view", "registered_at")
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    MODEL_UID_FIELD_NUMBER: _ClassVar[int]
    MODEL_REVISION_FIELD_NUMBER: _ClassVar[int]
    FAMILY_FIELD_NUMBER: _ClassVar[int]
    DEFINITION_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    FEATURE_REQUIREMENT_SET_FIELD_NUMBER: _ClassVar[int]
    MODEL_FEATURE_VIEW_FIELD_NUMBER: _ClassVar[int]
    REGISTERED_AT_FIELD_NUMBER: _ClassVar[int]
    model_name: str
    model_uid: str
    model_revision: int
    family: str
    definition_manifest: _artifact_reference_pb2.ArtifactRef
    feature_requirement_set: _artifact_reference_pb2.ArtifactRef
    model_feature_view: _artifact_reference_pb2.ArtifactRef
    registered_at: _timestamp_pb2.Timestamp
    def __init__(self, model_name: _Optional[str] = ..., model_uid: _Optional[str] = ..., model_revision: _Optional[int] = ..., family: _Optional[str] = ..., definition_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., feature_requirement_set: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., model_feature_view: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., registered_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
