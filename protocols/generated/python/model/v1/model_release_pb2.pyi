import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from artifact.v1 import evidence_reference_pb2 as _evidence_reference_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ModelReleaseStage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MODEL_RELEASE_STAGE_UNSPECIFIED: _ClassVar[ModelReleaseStage]
    MODEL_RELEASE_STAGE_EXPERIMENTAL: _ClassVar[ModelReleaseStage]
    MODEL_RELEASE_STAGE_QUALIFIED: _ClassVar[ModelReleaseStage]
    MODEL_RELEASE_STAGE_RELEASE_CANDIDATE: _ClassVar[ModelReleaseStage]
    MODEL_RELEASE_STAGE_RELEASED: _ClassVar[ModelReleaseStage]
    MODEL_RELEASE_STAGE_DEPRECATED: _ClassVar[ModelReleaseStage]
    MODEL_RELEASE_STAGE_REVOKED: _ClassVar[ModelReleaseStage]
MODEL_RELEASE_STAGE_UNSPECIFIED: ModelReleaseStage
MODEL_RELEASE_STAGE_EXPERIMENTAL: ModelReleaseStage
MODEL_RELEASE_STAGE_QUALIFIED: ModelReleaseStage
MODEL_RELEASE_STAGE_RELEASE_CANDIDATE: ModelReleaseStage
MODEL_RELEASE_STAGE_RELEASED: ModelReleaseStage
MODEL_RELEASE_STAGE_DEPRECATED: ModelReleaseStage
MODEL_RELEASE_STAGE_REVOKED: ModelReleaseStage

class ModelRelease(_message.Message):
    __slots__ = ("name", "uid", "revision", "etag", "tenant_name", "project_name", "model_name", "release_id", "stage", "bundle_manifest", "model_manifest", "checkpoint", "evaluation_evidence", "feature_requirement_set", "model_feature_view", "release_policy", "policy_classification", "create_time", "qualify_time", "release_time", "revoke_time", "revocation_reason")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    TENANT_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    RELEASE_ID_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    BUNDLE_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    MODEL_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_FIELD_NUMBER: _ClassVar[int]
    EVALUATION_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    FEATURE_REQUIREMENT_SET_FIELD_NUMBER: _ClassVar[int]
    MODEL_FEATURE_VIEW_FIELD_NUMBER: _ClassVar[int]
    RELEASE_POLICY_FIELD_NUMBER: _ClassVar[int]
    POLICY_CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    QUALIFY_TIME_FIELD_NUMBER: _ClassVar[int]
    RELEASE_TIME_FIELD_NUMBER: _ClassVar[int]
    REVOKE_TIME_FIELD_NUMBER: _ClassVar[int]
    REVOCATION_REASON_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    revision: int
    etag: str
    tenant_name: str
    project_name: str
    model_name: str
    release_id: str
    stage: ModelReleaseStage
    bundle_manifest: _artifact_reference_pb2.ArtifactRef
    model_manifest: _artifact_reference_pb2.ArtifactRef
    checkpoint: _resource_reference_pb2.ResourceRef
    evaluation_evidence: _containers.RepeatedCompositeFieldContainer[_evidence_reference_pb2.EvidenceRef]
    feature_requirement_set: _artifact_reference_pb2.ArtifactRef
    model_feature_view: _artifact_reference_pb2.ArtifactRef
    release_policy: _resource_reference_pb2.ResourceRef
    policy_classification: str
    create_time: _timestamp_pb2.Timestamp
    qualify_time: _timestamp_pb2.Timestamp
    release_time: _timestamp_pb2.Timestamp
    revoke_time: _timestamp_pb2.Timestamp
    revocation_reason: str
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., tenant_name: _Optional[str] = ..., project_name: _Optional[str] = ..., model_name: _Optional[str] = ..., release_id: _Optional[str] = ..., stage: _Optional[_Union[ModelReleaseStage, str]] = ..., bundle_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., model_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., checkpoint: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., evaluation_evidence: _Optional[_Iterable[_Union[_evidence_reference_pb2.EvidenceRef, _Mapping]]] = ..., feature_requirement_set: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., model_feature_view: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., release_policy: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., policy_classification: _Optional[str] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., qualify_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., release_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., revoke_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., revocation_reason: _Optional[str] = ...) -> None: ...
