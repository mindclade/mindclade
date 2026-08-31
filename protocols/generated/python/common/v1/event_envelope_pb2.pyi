import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DataClassification(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATA_CLASSIFICATION_UNSPECIFIED: _ClassVar[DataClassification]
    DATA_CLASSIFICATION_PUBLIC: _ClassVar[DataClassification]
    DATA_CLASSIFICATION_INTERNAL: _ClassVar[DataClassification]
    DATA_CLASSIFICATION_RESTRICTED: _ClassVar[DataClassification]
DATA_CLASSIFICATION_UNSPECIFIED: DataClassification
DATA_CLASSIFICATION_PUBLIC: DataClassification
DATA_CLASSIFICATION_INTERNAL: DataClassification
DATA_CLASSIFICATION_RESTRICTED: DataClassification

class EventEnvelope(_message.Message):
    __slots__ = ("event_id", "event_type", "event_version", "occurred_at", "tenant_id", "trace_id", "subject", "payload_digest", "payload", "recorded_at", "producer", "project_id", "aggregate_sequence", "request_id", "correlation_id", "causation_id", "job_id", "run_id", "deduplication_key", "payload_content_type", "classification")
    EVENT_ID_FIELD_NUMBER: _ClassVar[int]
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    EVENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_DIGEST_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    RECORDED_AT_FIELD_NUMBER: _ClassVar[int]
    PRODUCER_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    AGGREGATE_SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    CORRELATION_ID_FIELD_NUMBER: _ClassVar[int]
    CAUSATION_ID_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    DEDUPLICATION_KEY_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    CLASSIFICATION_FIELD_NUMBER: _ClassVar[int]
    event_id: str
    event_type: str
    event_version: int
    occurred_at: _timestamp_pb2.Timestamp
    tenant_id: str
    trace_id: str
    subject: _resource_reference_pb2.ResourceRef
    payload_digest: str
    payload: bytes
    recorded_at: _timestamp_pb2.Timestamp
    producer: str
    project_id: str
    aggregate_sequence: int
    request_id: str
    correlation_id: str
    causation_id: str
    job_id: str
    run_id: str
    deduplication_key: str
    payload_content_type: str
    classification: DataClassification
    def __init__(self, event_id: _Optional[str] = ..., event_type: _Optional[str] = ..., event_version: _Optional[int] = ..., occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., tenant_id: _Optional[str] = ..., trace_id: _Optional[str] = ..., subject: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., payload_digest: _Optional[str] = ..., payload: _Optional[bytes] = ..., recorded_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., producer: _Optional[str] = ..., project_id: _Optional[str] = ..., aggregate_sequence: _Optional[int] = ..., request_id: _Optional[str] = ..., correlation_id: _Optional[str] = ..., causation_id: _Optional[str] = ..., job_id: _Optional[str] = ..., run_id: _Optional[str] = ..., deduplication_key: _Optional[str] = ..., payload_content_type: _Optional[str] = ..., classification: _Optional[_Union[DataClassification, str]] = ...) -> None: ...
