import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from feature.v1 import feature_materialization_pb2 as _feature_materialization_pb2
from job.v1 import lease_fencing_pb2 as _lease_fencing_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FeatureMaterializationCompleted(_message.Message):
    __slots__ = ("materialization_name", "materialization_revision", "fence", "classification", "receipt", "output_refs", "error", "completed_at")
    MATERIALIZATION_NAME_FIELD_NUMBER: _ClassVar[int]
    MATERIALIZATION_REVISION_FIELD_NUMBER: _ClassVar[int]
    FENCE_FIELD_NUMBER: _ClassVar[int]
    CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_REFS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    materialization_name: str
    materialization_revision: int
    fence: _lease_fencing_pb2.LeaseFence
    classification: _feature_materialization_pb2.FeatureMaterializationTerminalClassification
    receipt: _artifact_reference_pb2.ArtifactRef
    output_refs: _containers.RepeatedCompositeFieldContainer[_artifact_reference_pb2.ArtifactRef]
    error: _error_detail_pb2.ErrorDetail
    completed_at: _timestamp_pb2.Timestamp
    def __init__(self, materialization_name: _Optional[str] = ..., materialization_revision: _Optional[int] = ..., fence: _Optional[_Union[_lease_fencing_pb2.LeaseFence, _Mapping]] = ..., classification: _Optional[_Union[_feature_materialization_pb2.FeatureMaterializationTerminalClassification, str]] = ..., receipt: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., output_refs: _Optional[_Iterable[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]]] = ..., error: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
