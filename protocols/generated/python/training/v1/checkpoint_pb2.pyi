import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from artifact.v1 import evidence_reference_pb2 as _evidence_reference_pb2
from common.v1 import error_detail_pb2 as _error_detail_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from training.v1 import training_progress_pb2 as _training_progress_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CheckpointState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHECKPOINT_STATE_UNSPECIFIED: _ClassVar[CheckpointState]
    CHECKPOINT_STATE_PREPARING: _ClassVar[CheckpointState]
    CHECKPOINT_STATE_WRITING: _ClassVar[CheckpointState]
    CHECKPOINT_STATE_VERIFYING: _ClassVar[CheckpointState]
    CHECKPOINT_STATE_COMMITTED: _ClassVar[CheckpointState]
    CHECKPOINT_STATE_INCOMPLETE: _ClassVar[CheckpointState]
    CHECKPOINT_STATE_REVOKED: _ClassVar[CheckpointState]
CHECKPOINT_STATE_UNSPECIFIED: CheckpointState
CHECKPOINT_STATE_PREPARING: CheckpointState
CHECKPOINT_STATE_WRITING: CheckpointState
CHECKPOINT_STATE_VERIFYING: CheckpointState
CHECKPOINT_STATE_COMMITTED: CheckpointState
CHECKPOINT_STATE_INCOMPLETE: CheckpointState
CHECKPOINT_STATE_REVOKED: CheckpointState

class Checkpoint(_message.Message):
    __slots__ = ("name", "uid", "revision", "etag", "tenant_name", "project_name", "training_run_name", "snapshot_epoch", "state", "checkpoint_manifest", "logical_state_descriptor", "committed_progress", "parent_checkpoint", "topology_envelope", "verification_evidence", "error", "prepare_time", "verify_time", "commit_time", "revoke_time")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    TENANT_NAME_FIELD_NUMBER: _ClassVar[int]
    PROJECT_NAME_FIELD_NUMBER: _ClassVar[int]
    TRAINING_RUN_NAME_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_EPOCH_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINT_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    LOGICAL_STATE_DESCRIPTOR_FIELD_NUMBER: _ClassVar[int]
    COMMITTED_PROGRESS_FIELD_NUMBER: _ClassVar[int]
    PARENT_CHECKPOINT_FIELD_NUMBER: _ClassVar[int]
    TOPOLOGY_ENVELOPE_FIELD_NUMBER: _ClassVar[int]
    VERIFICATION_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    PREPARE_TIME_FIELD_NUMBER: _ClassVar[int]
    VERIFY_TIME_FIELD_NUMBER: _ClassVar[int]
    COMMIT_TIME_FIELD_NUMBER: _ClassVar[int]
    REVOKE_TIME_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    revision: int
    etag: str
    tenant_name: str
    project_name: str
    training_run_name: str
    snapshot_epoch: int
    state: CheckpointState
    checkpoint_manifest: _artifact_reference_pb2.ArtifactRef
    logical_state_descriptor: _artifact_reference_pb2.ArtifactRef
    committed_progress: _training_progress_pb2.TrainingProgress
    parent_checkpoint: _resource_reference_pb2.ResourceRef
    topology_envelope: _artifact_reference_pb2.ArtifactRef
    verification_evidence: _evidence_reference_pb2.EvidenceRef
    error: _error_detail_pb2.ErrorDetail
    prepare_time: _timestamp_pb2.Timestamp
    verify_time: _timestamp_pb2.Timestamp
    commit_time: _timestamp_pb2.Timestamp
    revoke_time: _timestamp_pb2.Timestamp
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., revision: _Optional[int] = ..., etag: _Optional[str] = ..., tenant_name: _Optional[str] = ..., project_name: _Optional[str] = ..., training_run_name: _Optional[str] = ..., snapshot_epoch: _Optional[int] = ..., state: _Optional[_Union[CheckpointState, str]] = ..., checkpoint_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., logical_state_descriptor: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., committed_progress: _Optional[_Union[_training_progress_pb2.TrainingProgress, _Mapping]] = ..., parent_checkpoint: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., topology_envelope: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., verification_evidence: _Optional[_Union[_evidence_reference_pb2.EvidenceRef, _Mapping]] = ..., error: _Optional[_Union[_error_detail_pb2.ErrorDetail, _Mapping]] = ..., prepare_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., verify_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., commit_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., revoke_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
