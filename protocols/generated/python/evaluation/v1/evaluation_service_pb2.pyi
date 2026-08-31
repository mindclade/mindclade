import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from artifact.v1 import artifact_reference_pb2 as _artifact_reference_pb2
from common.v1 import command_context_pb2 as _command_context_pb2
from common.v1 import pagination_pb2 as _pagination_pb2
from common.v1 import resource_reference_pb2 as _resource_reference_pb2
from evaluation.v1 import evaluation_result_pb2 as _evaluation_result_pb2
from evaluation.v1 import evaluation_run_pb2 as _evaluation_run_pb2
from evaluation.v1 import promotion_decision_pb2 as _promotion_decision_pb2
from job.v1 import lease_fencing_pb2 as _lease_fencing_pb2
from job.v1 import operation_pb2 as _operation_pb2
from policy.v1 import policy_reference_pb2 as _policy_reference_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CreateEvaluationRunRequest(_message.Message):
    __slots__ = ("context", "parent", "evaluation_run_id", "suite", "datasets", "snapshot", "model_release", "inference_protocol", "executable_plan", "provider_manifest", "kernel_qualification", "policy_snapshots")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    EVALUATION_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    SUITE_FIELD_NUMBER: _ClassVar[int]
    DATASETS_FIELD_NUMBER: _ClassVar[int]
    SNAPSHOT_FIELD_NUMBER: _ClassVar[int]
    MODEL_RELEASE_FIELD_NUMBER: _ClassVar[int]
    INFERENCE_PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    EXECUTABLE_PLAN_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_MANIFEST_FIELD_NUMBER: _ClassVar[int]
    KERNEL_QUALIFICATION_FIELD_NUMBER: _ClassVar[int]
    POLICY_SNAPSHOTS_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    parent: str
    evaluation_run_id: str
    suite: _artifact_reference_pb2.ArtifactRef
    datasets: _containers.RepeatedCompositeFieldContainer[_artifact_reference_pb2.ArtifactRef]
    snapshot: _artifact_reference_pb2.ArtifactRef
    model_release: _resource_reference_pb2.ResourceRef
    inference_protocol: _artifact_reference_pb2.ArtifactRef
    executable_plan: _artifact_reference_pb2.ArtifactRef
    provider_manifest: _artifact_reference_pb2.ArtifactRef
    kernel_qualification: _artifact_reference_pb2.ArtifactRef
    policy_snapshots: _containers.RepeatedCompositeFieldContainer[_policy_reference_pb2.PolicyReference]
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., parent: _Optional[str] = ..., evaluation_run_id: _Optional[str] = ..., suite: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., datasets: _Optional[_Iterable[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]]] = ..., snapshot: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., model_release: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., inference_protocol: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., executable_plan: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., provider_manifest: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., kernel_qualification: _Optional[_Union[_artifact_reference_pb2.ArtifactRef, _Mapping]] = ..., policy_snapshots: _Optional[_Iterable[_Union[_policy_reference_pb2.PolicyReference, _Mapping]]] = ...) -> None: ...

class CreateEvaluationRunResponse(_message.Message):
    __slots__ = ("operation",)
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    operation: _operation_pb2.Operation
    def __init__(self, operation: _Optional[_Union[_operation_pb2.Operation, _Mapping]] = ...) -> None: ...

class GetEvaluationRunRequest(_message.Message):
    __slots__ = ("name", "if_none_match")
    NAME_FIELD_NUMBER: _ClassVar[int]
    IF_NONE_MATCH_FIELD_NUMBER: _ClassVar[int]
    name: str
    if_none_match: str
    def __init__(self, name: _Optional[str] = ..., if_none_match: _Optional[str] = ...) -> None: ...

class GetEvaluationRunResponse(_message.Message):
    __slots__ = ("evaluation_run",)
    EVALUATION_RUN_FIELD_NUMBER: _ClassVar[int]
    evaluation_run: _evaluation_run_pb2.EvaluationRun
    def __init__(self, evaluation_run: _Optional[_Union[_evaluation_run_pb2.EvaluationRun, _Mapping]] = ...) -> None: ...

class ListEvaluationRunsRequest(_message.Message):
    __slots__ = ("parent", "page", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page: _pagination_pb2.PageRequest
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page: _Optional[_Union[_pagination_pb2.PageRequest, _Mapping]] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListEvaluationRunsResponse(_message.Message):
    __slots__ = ("evaluation_runs", "page", "read_time")
    EVALUATION_RUNS_FIELD_NUMBER: _ClassVar[int]
    PAGE_FIELD_NUMBER: _ClassVar[int]
    READ_TIME_FIELD_NUMBER: _ClassVar[int]
    evaluation_runs: _containers.RepeatedCompositeFieldContainer[_evaluation_run_pb2.EvaluationRun]
    page: _pagination_pb2.PageResponse
    read_time: _timestamp_pb2.Timestamp
    def __init__(self, evaluation_runs: _Optional[_Iterable[_Union[_evaluation_run_pb2.EvaluationRun, _Mapping]]] = ..., page: _Optional[_Union[_pagination_pb2.PageResponse, _Mapping]] = ..., read_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class CancelEvaluationRunRequest(_message.Message):
    __slots__ = ("context", "name", "etag", "reason")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    name: str
    etag: str
    reason: str
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., name: _Optional[str] = ..., etag: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class CancelEvaluationRunResponse(_message.Message):
    __slots__ = ("operation",)
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    operation: _operation_pb2.Operation
    def __init__(self, operation: _Optional[_Union[_operation_pb2.Operation, _Mapping]] = ...) -> None: ...

class CommitEvaluationResultRequest(_message.Message):
    __slots__ = ("context", "evaluation_run", "fence", "result", "etag")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    EVALUATION_RUN_FIELD_NUMBER: _ClassVar[int]
    FENCE_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    evaluation_run: _resource_reference_pb2.ResourceRef
    fence: _lease_fencing_pb2.LeaseFence
    result: _evaluation_result_pb2.EvaluationResult
    etag: str
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., evaluation_run: _Optional[_Union[_resource_reference_pb2.ResourceRef, _Mapping]] = ..., fence: _Optional[_Union[_lease_fencing_pb2.LeaseFence, _Mapping]] = ..., result: _Optional[_Union[_evaluation_result_pb2.EvaluationResult, _Mapping]] = ..., etag: _Optional[str] = ...) -> None: ...

class CommitEvaluationResultResponse(_message.Message):
    __slots__ = ("result", "evaluation_run")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    EVALUATION_RUN_FIELD_NUMBER: _ClassVar[int]
    result: _evaluation_result_pb2.EvaluationResult
    evaluation_run: _evaluation_run_pb2.EvaluationRun
    def __init__(self, result: _Optional[_Union[_evaluation_result_pb2.EvaluationResult, _Mapping]] = ..., evaluation_run: _Optional[_Union[_evaluation_run_pb2.EvaluationRun, _Mapping]] = ...) -> None: ...

class GetEvaluationResultRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class GetEvaluationResultResponse(_message.Message):
    __slots__ = ("result",)
    RESULT_FIELD_NUMBER: _ClassVar[int]
    result: _evaluation_result_pb2.EvaluationResult
    def __init__(self, result: _Optional[_Union[_evaluation_result_pb2.EvaluationResult, _Mapping]] = ...) -> None: ...

class CreatePromotionDecisionRequest(_message.Message):
    __slots__ = ("context", "promotion_decision")
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    PROMOTION_DECISION_FIELD_NUMBER: _ClassVar[int]
    context: _command_context_pb2.CommandContext
    promotion_decision: _promotion_decision_pb2.PromotionDecision
    def __init__(self, context: _Optional[_Union[_command_context_pb2.CommandContext, _Mapping]] = ..., promotion_decision: _Optional[_Union[_promotion_decision_pb2.PromotionDecision, _Mapping]] = ...) -> None: ...

class CreatePromotionDecisionResponse(_message.Message):
    __slots__ = ("operation",)
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    operation: _operation_pb2.Operation
    def __init__(self, operation: _Optional[_Union[_operation_pb2.Operation, _Mapping]] = ...) -> None: ...

class GetPromotionDecisionRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class GetPromotionDecisionResponse(_message.Message):
    __slots__ = ("promotion_decision",)
    PROMOTION_DECISION_FIELD_NUMBER: _ClassVar[int]
    promotion_decision: _promotion_decision_pb2.PromotionDecision
    def __init__(self, promotion_decision: _Optional[_Union[_promotion_decision_pb2.PromotionDecision, _Mapping]] = ...) -> None: ...
