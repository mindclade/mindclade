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

class DatasetReleaseState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATASET_RELEASE_STATE_UNSPECIFIED: _ClassVar[DatasetReleaseState]
    DATASET_RELEASE_STATE_DRAFT: _ClassVar[DatasetReleaseState]
    DATASET_RELEASE_STATE_QUALIFIED: _ClassVar[DatasetReleaseState]
    DATASET_RELEASE_STATE_PUBLISHED: _ClassVar[DatasetReleaseState]
    DATASET_RELEASE_STATE_DEPRECATED: _ClassVar[DatasetReleaseState]
    DATASET_RELEASE_STATE_REVOKED: _ClassVar[DatasetReleaseState]
DATASET_RELEASE_STATE_UNSPECIFIED: DatasetReleaseState
DATASET_RELEASE_STATE_DRAFT: DatasetReleaseState
DATASET_RELEASE_STATE_QUALIFIED: DatasetReleaseState
DATASET_RELEASE_STATE_PUBLISHED: DatasetReleaseState
DATASET_RELEASE_STATE_DEPRECATED: DatasetReleaseState
DATASET_RELEASE_STATE_REVOKED: DatasetReleaseState

class DatasetRelease(_message.Message):
    __slots__ = ("name", "uid", "revision", "etag", "tenant_name", "project_name", "dataset_name", "release_id", "state", "manifest", "qualification_evidence", "parent_release", "use_policy", "policy_classification", "create_time", "publish_time", "revoke_time", "revocation_reason")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    TENANT_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    DATASET_NAME_FIELD_NUMBER: _ClassVar[int]
    RELEASE_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    MANIFEST_FIELD_NUMBER: _ClassVar[int]
    QUALIFICATION_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    PARENT_RELEASE_FIELD_NUMBER: _ClassVar[int]
    USE_POLICY_FIELD_NUMBER: _ClassVar[int]
    POLICY_CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    PUBLISH_TIME_FIELD_NUMBER: _ClassVar[int]
    REVOKE_TIME_FIELD_NUMBER: _ClassVar[int]
    REVOCATION_REASON_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    revision: int
    etag: str
    tenant_name: str
    project_name: str
    dataset_name: str
    release_id: str
    state: DatasetReleaseState
    manifest: _artifact_reference_pb2.ArtifactRef
    qualification_evidence: _containers.RepeatedCompositeFieldContainer[_evidence_reference_pb2.EvidenceRef]
    parent_release: _resource_reference_pb2.ResourceRef
    use_policy: _resource_reference_pb2.ResourceRef
    policy_classification: str
    create_time: _timestamp_pb2.Timestamp
    publish_time: _timestamp_pb2.Timestamp
    revoke_time: _timestamp_pb2.Timestamp
    revocation_reason: str
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., tenant_name: _Optional[str] = ..., project_name: _Optional[str] = ..., dataset_name: _Optional[str] = ..., release_id: _Optional[str] = ..., state: _Optional[_Union[DatasetReleaseState, str]] = ..., manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., qualification_evidence: _Optional[_Iterable[_Union[_evidence_reference_pb2.EvidenceRef, _Mapping]]] = ..., parent_release: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., use_policy: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., policy_classification: _Optional[str] = ..., create_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., publish_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., revoke_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., revocation_reason: _Optional[str] = ...) -> None: ...
