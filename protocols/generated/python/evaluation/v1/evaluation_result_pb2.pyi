import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class EvaluationResultOutcome(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EVALUATION_RESULT_OUTCOME_UNSPECIFIED: _ClassVar[EvaluationResultOutcome]
    EVALUATION_RESULT_OUTCOME_PASSED: _ClassVar[EvaluationResultOutcome]
    EVALUATION_RESULT_OUTCOME_FAILED: _ClassVar[EvaluationResultOutcome]
    EVALUATION_RESULT_OUTCOME_INCONCLUSIVE: _ClassVar[EvaluationResultOutcome]
    EVALUATION_RESULT_OUTCOME_INVALID: _ClassVar[EvaluationResultOutcome]
    EVALUATION_RESULT_OUTCOME_CANCELLED: _ClassVar[EvaluationResultOutcome]

class MetricDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    METRIC_DIRECTION_UNSPECIFIED: _ClassVar[MetricDirection]
    METRIC_DIRECTION_HIGHER_IS_BETTER: _ClassVar[MetricDirection]
    METRIC_DIRECTION_LOWER_IS_BETTER: _ClassVar[MetricDirection]
    METRIC_DIRECTION_TARGET_IS_BETTER: _ClassVar[MetricDirection]

class ThresholdResult(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    THRESHOLD_RESULT_UNSPECIFIED: _ClassVar[ThresholdResult]
    THRESHOLD_RESULT_PASS: _ClassVar[ThresholdResult]
    THRESHOLD_RESULT_FAIL: _ClassVar[ThresholdResult]
    THRESHOLD_RESULT_INCONCLUSIVE: _ClassVar[ThresholdResult]
    THRESHOLD_RESULT_NOT_APPLICABLE: _ClassVar[ThresholdResult]
EVALUATION_RESULT_OUTCOME_UNSPECIFIED: EvaluationResultOutcome
EVALUATION_RESULT_OUTCOME_PASSED: EvaluationResultOutcome
EVALUATION_RESULT_OUTCOME_FAILED: EvaluationResultOutcome
EVALUATION_RESULT_OUTCOME_INCONCLUSIVE: EvaluationResultOutcome
EVALUATION_RESULT_OUTCOME_INVALID: EvaluationResultOutcome
EVALUATION_RESULT_OUTCOME_CANCELLED: EvaluationResultOutcome
METRIC_DIRECTION_UNSPECIFIED: MetricDirection
METRIC_DIRECTION_HIGHER_IS_BETTER: MetricDirection
METRIC_DIRECTION_LOWER_IS_BETTER: MetricDirection
METRIC_DIRECTION_TARGET_IS_BETTER: MetricDirection
THRESHOLD_RESULT_UNSPECIFIED: ThresholdResult
THRESHOLD_RESULT_PASS: ThresholdResult
THRESHOLD_RESULT_FAIL: ThresholdResult
THRESHOLD_RESULT_INCONCLUSIVE: ThresholdResult
THRESHOLD_RESULT_NOT_APPLICABLE: ThresholdResult

class MetricSummary(_message.Message):
    __slots__ = ("metric_id", "metric_version", "unit", "direction", "value", "interval_lower", "interval_upper", "valid_count", "invalid_count", "cohort_id")
    METRIC_ID_FIELD_NUMBER: _ClassVar[int]
    METRIC_VERSION_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_LOWER_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_UPPER_FIELD_NUMBER: _ClassVar[int]
    VALID_COUNT_FIELD_NUMBER: _ClassVar[int]
    INVALID_COUNT_FIELD_NUMBER: _ClassVar[int]
    COHORT_ID_FIELD_NUMBER: _ClassVar[int]
    metric_id: str
    metric_version: str
    unit: str
    direction: MetricDirection
    value: float
    interval_lower: float
    interval_upper: float
    valid_count: int
    invalid_count: int
    cohort_id: str
    def __init__(self, metric_id: _Optional[str] = ..., metric_version: _Optional[str] = ..., unit: _Optional[str] = ..., direction: _Optional[_Union[MetricDirection, str]] = ..., value: _Optional[float] = ..., interval_lower: _Optional[float] = ..., interval_upper: _Optional[float] = ..., valid_count: _Optional[int] = ..., invalid_count: _Optional[int] = ..., cohort_id: _Optional[str] = ...) -> None: ...

class ThresholdOutcome(_message.Message):
    __slots__ = ("rule_id", "metric_id", "result", "reason_code", "evidence")
    RULE_ID_FIELD_NUMBER: _ClassVar[int]
    METRIC_ID_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    REASON_CODE_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    rule_id: str
    metric_id: str
    result: ThresholdResult
    reason_code: str
    evidence: _artifact_reference_pb2.ArtifactRef
    def __init__(self, rule_id: _Optional[str] = ..., metric_id: _Optional[str] = ..., result: _Optional[_Union[ThresholdResult, str]] = ..., reason_code: _Optional[str] = ..., evidence: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ...) -> None: ...

class EvaluationFailureCount(_message.Message):
    __slots__ = ("failure_class", "count")
    FAILURE_CLASS_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    failure_class: str
    count: int
    def __init__(self, failure_class: _Optional[str] = ..., count: _Optional[int] = ...) -> None: ...

class EvaluationResult(_message.Message):
    __slots__ = ("name", "uid", "run", "run_digest", "outcome", "report", "suite", "snapshot", "dataset_manifest", "inference_protocol", "metrics", "thresholds", "failure_counts", "leakage_evidence", "safety_evidence", "statistical_evidence", "performance_evidence", "source_revision", "finalized_at", "result_digest")
    NAME_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    RUN_FIELD_NUMBER: _ClassVar[int]
    RUN_DIGEST_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    REPORT_FIELD_NUMBER: _ClassVar[int]
    SUITE_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    DATASET_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    INFERENCE_PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    THRESHOLDS_FIELD_NUMBER: _ClassVar[int]
    FAILURE_COUNTS_FIELD_NUMBER: _ClassVar[int]
    LEAKAGE_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    SAFETY_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    STATISTICAL_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    PERFORMANCE_EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_REVISION_FIELD_NUMBER: _ClassVar[int]
    FINALIZED_AT_FIELD_NUMBER: _ClassVar[int]
    RESULT_DIGEST_FIELD_NUMBER: _ClassVar[int]
    name: str
    uid: str
    run: _resource_reference_pb2.ResourceRef
    run_digest: str
    outcome: EvaluationResultOutcome
    report: _artifact_reference_pb2.ArtifactRef
    suite: _artifact_reference_pb2.ArtifactRef
    snapshot: _artifact_reference_pb2.ArtifactRef
    dataset_manifest: _artifact_reference_pb2.ArtifactRef
    inference_protocol: _artifact_reference_pb2.ArtifactRef
    metrics: _containers.RepeatedCompositeFieldContainer[MetricSummary]
    thresholds: _containers.RepeatedCompositeFieldContainer[ThresholdOutcome]
    failure_counts: _containers.RepeatedCompositeFieldContainer[EvaluationFailureCount]
    leakage_evidence: _artifact_reference_pb2.ArtifactRef
    safety_evidence: _artifact_reference_pb2.ArtifactRef
    statistical_evidence: _artifact_reference_pb2.ArtifactRef
    performance_evidence: _artifact_reference_pb2.ArtifactRef
    source_revision: str
    finalized_at: _timestamp_pb2.Timestamp
    result_digest: str
    def __init__(self, name: _Optional[str] = ..., uid: _Optional[str] = ..., run: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., run_digest: _Optional[str] = ..., outcome: _Optional[_Union[EvaluationResultOutcome, str]] = ..., report: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., suite: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., snapshot: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., dataset_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., inference_protocol: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., metrics: _Optional[_Iterable[_Union[MetricSummary, _Mapping]]] = ..., thresholds: _Optional[_Iterable[_Union[ThresholdOutcome, _Mapping]]] = ..., failure_counts: _Optional[_Iterable[_Union[EvaluationFailureCount, _Mapping]]] = ..., leakage_evidence: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., safety_evidence: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., statistical_evidence: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., performance_evidence: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., source_revision: _Optional[str] = ..., finalized_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., result_digest: _Optional[str] = ...) -> None: ...
