"""Generated-type-only evaluation lifecycle and evidence-governance facade."""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import grpc
from google.protobuf.message import Message
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import resource_reference_pb2
from mindclade.evaluation.v1 import (
    evaluation_result_pb2,
    evaluation_run_pb2,
    promotion_decision_pb2,
)
from mindclade.internal.evaluation.v1 import evaluation_service_pb2
from mindclade.job.v1 import lease_fencing_pb2, operation_pb2

from ._invocation import AsyncInvoker, SyncInvoker, canonical_digest, command_context
from ._raw import AsyncWithRawResponse, WithRawResponse
from ._validation import artifact_ref, required_response_message, required_text
from .calls import CallOptions, PreparedCall, prepare_call
from .errors import ProtocolError
from .pagination import (
    AsyncPage,
    Page,
    PaginationLimits,
    apply_default_page_size,
    async_page,
    next_request,
    sync_page,
)
from .transport import (
    CANCEL_EVALUATION_RUN,
    COMMIT_EVALUATION_RESULT,
    CREATE_EVALUATION_RUN,
    CREATE_PROMOTION_DECISION,
    GET_EVALUATION_RESULT,
    GET_EVALUATION_RUN,
    GET_PROMOTION_DECISION,
    LIST_EVALUATION_RUNS,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _project(invoker: SyncInvoker | AsyncInvoker) -> str:
    return invoker.config.project_parent


def _scoped_name(invoker: SyncInvoker | AsyncInvoker, value: str, collection: str) -> str:
    name = required_text(f"{collection} name", value, maximum=2048)
    prefix = f"{_project(invoker)}/{collection}/"
    suffix = name.removeprefix(prefix)
    if not name.startswith(prefix) or not suffix or "/" in suffix:
        raise ValueError(f"{collection} name must be scoped to the configured project")
    return name


def _model_release_name(invoker: SyncInvoker | AsyncInvoker, value: str) -> str:
    name = required_text("model release name", value, maximum=2048)
    prefix = f"{_project(invoker)}/models/"
    suffix = name.removeprefix(prefix)
    parts = suffix.split("/releases/")
    if (
        not name.startswith(prefix)
        or len(parts) != 2
        or not all(parts)
        or any("/" in part for part in parts)
    ):
        raise ValueError("model release must be scoped to the configured project")
    return name


def _normalize_reference(
    invoker: SyncInvoker | AsyncInvoker,
    reference: resource_reference_pb2.ResourceRef,
    *,
    resource_type: str,
    collection: str,
) -> None:
    name = _scoped_name(invoker, reference.name, collection)
    _normalize_named_reference(invoker, reference, resource_type=resource_type, name=name)


def _normalize_model_release(
    invoker: SyncInvoker | AsyncInvoker,
    reference: resource_reference_pb2.ResourceRef,
) -> None:
    name = _model_release_name(invoker, reference.name)
    _normalize_named_reference(invoker, reference, resource_type="model_release", name=name)


def _normalize_named_reference(
    invoker: SyncInvoker | AsyncInvoker,
    reference: resource_reference_pb2.ResourceRef,
    *,
    resource_type: str,
    name: str,
) -> None:
    resource_id = name.rsplit("/", 1)[-1]
    config = invoker.config
    if reference.resource_type not in ("", resource_type):
        raise ValueError("resource reference type conflicts with evaluation intent")
    if reference.resource_id not in ("", resource_id):
        raise ValueError("resource reference ID conflicts with its name")
    if reference.tenant_id not in ("", config.tenant_id) or reference.project_id not in (
        "",
        config.project_id,
    ):
        raise ValueError("resource reference conflicts with client scope")
    reference.resource_type = resource_type
    reference.resource_id = resource_id
    reference.tenant_id = config.tenant_id
    reference.project_id = config.project_id


def _validate_artifact(label: str, value: Message | None, *, required: bool) -> None:
    if value is None:
        if required:
            raise ValueError(f"{label} is required")
        return
    artifact_ref(label, value)
    typed = cast(artifact_reference_pb2.ArtifactRef, value)
    if typed.integrity_digest and _DIGEST.fullmatch(typed.integrity_digest) is None:
        raise ValueError(f"{label}.integrity_digest must be a canonical sha256 digest")


def _mutation_options(key: str, options: CallOptions | None) -> CallOptions | None:
    if not key or (options is not None and options.idempotency_key is not None):
        return options
    return replace(options, idempotency_key=key) if options else CallOptions(idempotency_key=key)


def _prepare_mutation[
    RequestT: (
        evaluation_service_pb2.CreateEvaluationRunRequest,
        evaluation_service_pb2.CancelEvaluationRunRequest,
        evaluation_service_pb2.CommitEvaluationResultRequest,
        evaluation_service_pb2.CreatePromotionDecisionRequest,
    )
](
    invoker: SyncInvoker | AsyncInvoker,
    request: RequestT,
    options: CallOptions | None,
    *,
    require_lease: bool = False,
) -> tuple[RequestT, PreparedCall]:
    materialized = copy.deepcopy(request)
    key = materialized.context.idempotency_key if materialized.HasField("context") else ""
    materialized.ClearField("context")
    selected = _mutation_options(key, options)
    if require_lease and (selected is None or selected.lease_token is None):
        raise ValueError("fenced evaluation result commit requires a lease_token")
    call = prepare_call(
        selected,
        default_timeout=invoker.config.default_timeout,
        require_idempotency=True,
    )
    materialized.context.CopyFrom(
        command_context(invoker.config, call, request_digest=canonical_digest(materialized))
    )
    return materialized, call


def _operation(response: Message, label: str) -> operation_pb2.Operation:
    operation = required_response_message(
        response, "operation", operation_pb2.Operation, label=label
    )
    required_text("operation ID", operation.operation_id)
    return operation


def _identity_violation(message: str) -> ProtocolError:
    return ProtocolError(message, status=grpc.StatusCode.DATA_LOSS)


def _validate_create(
    invoker: SyncInvoker | AsyncInvoker,
    request: evaluation_service_pb2.CreateEvaluationRunRequest,
) -> None:
    if not request.evaluation_run_id or "/" in request.evaluation_run_id:
        raise ValueError("evaluation_run_id is invalid")
    parent = _project(invoker)
    if request.parent not in ("", parent):
        raise ValueError("evaluation parent conflicts with client scope")
    request.parent = parent
    _validate_artifact(
        "evaluation suite", request.suite if request.HasField("suite") else None, required=True
    )
    _validate_artifact(
        "evaluation snapshot",
        request.snapshot if request.HasField("snapshot") else None,
        required=True,
    )
    _validate_artifact(
        "inference protocol",
        request.inference_protocol if request.HasField("inference_protocol") else None,
        required=True,
    )
    if not 1 <= len(request.datasets) <= 256:
        raise ValueError("evaluation requires between one and 256 datasets")
    for index, dataset in enumerate(request.datasets):
        _validate_artifact(f"dataset[{index}]", dataset, required=True)
    for field_name, label in (
        ("executable_plan", "executable plan"),
        ("provider_manifest", "provider manifest"),
        ("kernel_qualification", "kernel qualification"),
    ):
        _validate_artifact(
            label,
            getattr(request, field_name) if request.HasField(field_name) else None,
            required=False,
        )
    if not request.HasField("model_release"):
        raise ValueError("evaluation model release is required")
    _normalize_model_release(invoker, request.model_release)


def _normalize_fence(
    invoker: SyncInvoker | AsyncInvoker, fence: lease_fencing_pb2.LeaseFence
) -> None:
    if (
        not fence.job_id
        or not fence.run_id
        or not fence.attempt_id
        or fence.lease_epoch <= 0
        or not fence.HasField("deadline")
        or _DIGEST.fullmatch(fence.lease_token_digest) is None
    ):
        raise ValueError("evaluation lease fence is incomplete")
    try:
        deadline = fence.deadline.ToDatetime(tzinfo=UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError("evaluation lease deadline is invalid") from error
    if deadline <= datetime.now(UTC):
        raise ValueError("evaluation lease fence has expired")
    config = invoker.config
    if fence.tenant_id not in ("", config.tenant_id) or fence.project_id not in (
        "",
        config.project_id,
    ):
        raise ValueError("evaluation fence conflicts with client scope")
    fence.tenant_id = config.tenant_id
    fence.project_id = config.project_id


def _validate_commit(
    invoker: SyncInvoker | AsyncInvoker,
    request: evaluation_service_pb2.CommitEvaluationResultRequest,
) -> None:
    if (
        not request.HasField("evaluation_run")
        or not request.HasField("fence")
        or not request.HasField("result")
        or not request.etag.strip()
    ):
        raise ValueError("evaluation result commit requires run, fence, result, and ETag")
    _normalize_reference(
        invoker,
        request.evaluation_run,
        resource_type="evaluation_run",
        collection="evaluationRuns",
    )
    result = request.result
    _scoped_name(invoker, result.name, "evaluationResults")
    if not result.HasField("run"):
        raise ValueError("evaluation result run reference is required")
    _normalize_reference(
        invoker, result.run, resource_type="evaluation_run", collection="evaluationRuns"
    )
    if result.run.name != request.evaluation_run.name:
        raise ValueError("evaluation result and command must reference the same run")
    if (
        _DIGEST.fullmatch(result.run_digest) is None
        or _DIGEST.fullmatch(result.result_digest) is None
    ):
        raise ValueError("evaluation result requires canonical run and result digests")
    _normalize_fence(invoker, request.fence)


def _validate_decision(
    invoker: SyncInvoker | AsyncInvoker,
    request: evaluation_service_pb2.CreatePromotionDecisionRequest,
) -> None:
    if not request.HasField("promotion_decision"):
        raise ValueError("generated promotion decision is required")
    decision = request.promotion_decision
    _scoped_name(invoker, decision.name, "promotionDecisions")
    if (
        _DIGEST.fullmatch(decision.candidate_digest) is None
        or _DIGEST.fullmatch(decision.decision_digest) is None
    ):
        raise ValueError("promotion decision requires canonical evidence digests")
    if not decision.HasField("candidate_release"):
        raise ValueError("promotion candidate release is required")
    _normalize_model_release(invoker, decision.candidate_release)
    if not decision.evaluation_results:
        raise ValueError("promotion decision requires evaluation evidence")
    for result in decision.evaluation_results:
        _normalize_reference(
            invoker,
            result,
            resource_type="evaluation_result",
            collection="evaluationResults",
        )
    config = invoker.config
    for authorization in decision.policy_decisions:
        if authorization.tenant_id not in ("", config.tenant_id) or (
            authorization.project_id not in ("", config.project_id)
        ):
            raise ValueError("promotion policy decision conflicts with client scope")
        authorization.tenant_id = config.tenant_id
        authorization.project_id = config.project_id
    decision.decided_by_principal_ref = config.principal_id


class Evaluations(WithRawResponse):
    """Synchronous evaluation execution and evidence-governance API."""

    def __init__(self, invoker: SyncInvoker) -> None:
        self._invoker = invoker

    def create_run(
        self,
        request: evaluation_service_pb2.CreateEvaluationRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        _validate_create(self._invoker, materialized)
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        response = cast(
            evaluation_service_pb2.CreateEvaluationRunResponse,
            self._invoker.unary(CREATE_EVALUATION_RUN, materialized, call=call, retry_safe=True),
        )
        return _operation(response, "evaluation run creation")

    def get_run(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> evaluation_run_pb2.EvaluationRun:
        scoped = _scoped_name(self._invoker, name, "evaluationRuns")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.GetEvaluationRunResponse,
            self._invoker.unary(
                GET_EVALUATION_RUN,
                evaluation_service_pb2.GetEvaluationRunRequest(
                    name=scoped, if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        run = required_response_message(
            response,
            "evaluation_run",
            evaluation_run_pb2.EvaluationRun,
            label="evaluation run get",
        )
        if run.name != scoped:
            raise _identity_violation("evaluation run response changed resource identity")
        return run

    def list_runs(
        self,
        request: evaluation_service_pb2.ListEvaluationRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> Page[evaluation_run_pb2.EvaluationRun]:
        materialized = evaluation_service_pb2.ListEvaluationRunsRequest()
        if request is not None:
            materialized.CopyFrom(request)
        parent = _project(self._invoker)
        if materialized.parent not in ("", parent):
            raise ValueError("evaluation list parent conflicts with client scope")
        if materialized.HasField("page") and materialized.page.page_size > 200:
            raise ValueError("evaluation page size cannot exceed 200")
        materialized.parent = parent
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.ListEvaluationRunsResponse,
            self._invoker.unary(LIST_EVALUATION_RUNS, materialized, call=call, retry_safe=True),
        )

        def follow(page_token: str) -> Page[evaluation_run_pb2.EvaluationRun]:
            return self.list_runs(
                next_request(materialized, page_token), options=options, limits=limits
            )

        return sync_page(response, items_field="evaluation_runs", fetch=follow, limits=limits)

    def cancel_run(
        self,
        request: evaluation_service_pb2.CancelEvaluationRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        _scoped_name(self._invoker, materialized.name, "evaluationRuns")
        required_text("evaluation ETag", materialized.etag)
        required_text("evaluation cancellation reason", materialized.reason, maximum=1024)
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        response = cast(
            evaluation_service_pb2.CancelEvaluationRunResponse,
            self._invoker.unary(CANCEL_EVALUATION_RUN, materialized, call=call, retry_safe=True),
        )
        return _operation(response, "evaluation cancellation")

    def commit_result(
        self,
        request: evaluation_service_pb2.CommitEvaluationResultRequest,
        *,
        options: CallOptions,
    ) -> tuple[evaluation_result_pb2.EvaluationResult, evaluation_run_pb2.EvaluationRun]:
        materialized = copy.deepcopy(request)
        _validate_commit(self._invoker, materialized)
        materialized, call = _prepare_mutation(
            self._invoker, materialized, options, require_lease=True
        )
        response = cast(
            evaluation_service_pb2.CommitEvaluationResultResponse,
            self._invoker.unary(COMMIT_EVALUATION_RESULT, materialized, call=call, retry_safe=True),
        )
        result = required_response_message(
            response,
            "result",
            evaluation_result_pb2.EvaluationResult,
            label="evaluation result commit",
        )
        run = required_response_message(
            response,
            "evaluation_run",
            evaluation_run_pb2.EvaluationRun,
            label="evaluation result commit",
        )
        if result.name != materialized.result.name or run.name != materialized.evaluation_run.name:
            raise _identity_violation("evaluation result commit response changed durable identity")
        return result, run

    def get_result(
        self, name: str, *, options: CallOptions | None = None
    ) -> evaluation_result_pb2.EvaluationResult:
        scoped = _scoped_name(self._invoker, name, "evaluationResults")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.GetEvaluationResultResponse,
            self._invoker.unary(
                GET_EVALUATION_RESULT,
                evaluation_service_pb2.GetEvaluationResultRequest(name=scoped),
                call=call,
                retry_safe=True,
            ),
        )
        result = required_response_message(
            response,
            "result",
            evaluation_result_pb2.EvaluationResult,
            label="evaluation result get",
        )
        if result.name != scoped:
            raise _identity_violation("evaluation result response changed resource identity")
        return result

    def create_promotion_decision(
        self,
        request: evaluation_service_pb2.CreatePromotionDecisionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        _validate_decision(self._invoker, materialized)
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        response = cast(
            evaluation_service_pb2.CreatePromotionDecisionResponse,
            self._invoker.unary(
                CREATE_PROMOTION_DECISION, materialized, call=call, retry_safe=True
            ),
        )
        return _operation(response, "promotion decision creation")

    def get_promotion_decision(
        self, name: str, *, options: CallOptions | None = None
    ) -> promotion_decision_pb2.PromotionDecision:
        scoped = _scoped_name(self._invoker, name, "promotionDecisions")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.GetPromotionDecisionResponse,
            self._invoker.unary(
                GET_PROMOTION_DECISION,
                evaluation_service_pb2.GetPromotionDecisionRequest(name=scoped),
                call=call,
                retry_safe=True,
            ),
        )
        decision = required_response_message(
            response,
            "promotion_decision",
            promotion_decision_pb2.PromotionDecision,
            label="promotion decision get",
        )
        if decision.name != scoped:
            raise _identity_violation("promotion decision response changed resource identity")
        return decision


class AsyncEvaluations(AsyncWithRawResponse):
    """Asyncio-native evaluation execution and evidence-governance API."""

    def __init__(self, invoker: AsyncInvoker) -> None:
        self._invoker = invoker

    async def create_run(
        self,
        request: evaluation_service_pb2.CreateEvaluationRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        _validate_create(self._invoker, materialized)
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        response = cast(
            evaluation_service_pb2.CreateEvaluationRunResponse,
            await self._invoker.unary(
                CREATE_EVALUATION_RUN, materialized, call=call, retry_safe=True
            ),
        )
        return _operation(response, "evaluation run creation")

    async def get_run(
        self,
        name: str,
        *,
        if_none_match: str = "",
        options: CallOptions | None = None,
    ) -> evaluation_run_pb2.EvaluationRun:
        scoped = _scoped_name(self._invoker, name, "evaluationRuns")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.GetEvaluationRunResponse,
            await self._invoker.unary(
                GET_EVALUATION_RUN,
                evaluation_service_pb2.GetEvaluationRunRequest(
                    name=scoped, if_none_match=if_none_match.strip()
                ),
                call=call,
                retry_safe=True,
            ),
        )
        run = required_response_message(
            response,
            "evaluation_run",
            evaluation_run_pb2.EvaluationRun,
            label="evaluation run get",
        )
        if run.name != scoped:
            raise _identity_violation("evaluation run response changed resource identity")
        return run

    async def list_runs(
        self,
        request: evaluation_service_pb2.ListEvaluationRunsRequest | None = None,
        *,
        options: CallOptions | None = None,
        limits: PaginationLimits | None = None,
    ) -> AsyncPage[evaluation_run_pb2.EvaluationRun]:
        materialized = evaluation_service_pb2.ListEvaluationRunsRequest()
        if request is not None:
            materialized.CopyFrom(request)
        parent = _project(self._invoker)
        if materialized.parent not in ("", parent):
            raise ValueError("evaluation list parent conflicts with client scope")
        if materialized.HasField("page") and materialized.page.page_size > 200:
            raise ValueError("evaluation page size cannot exceed 200")
        materialized.parent = parent
        apply_default_page_size(materialized, limits)
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.ListEvaluationRunsResponse,
            await self._invoker.unary(
                LIST_EVALUATION_RUNS, materialized, call=call, retry_safe=True
            ),
        )

        async def follow(page_token: str) -> AsyncPage[evaluation_run_pb2.EvaluationRun]:
            return await self.list_runs(
                next_request(materialized, page_token), options=options, limits=limits
            )

        return async_page(response, items_field="evaluation_runs", fetch=follow, limits=limits)

    async def cancel_run(
        self,
        request: evaluation_service_pb2.CancelEvaluationRunRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        _scoped_name(self._invoker, materialized.name, "evaluationRuns")
        required_text("evaluation ETag", materialized.etag)
        required_text("evaluation cancellation reason", materialized.reason, maximum=1024)
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        response = cast(
            evaluation_service_pb2.CancelEvaluationRunResponse,
            await self._invoker.unary(
                CANCEL_EVALUATION_RUN, materialized, call=call, retry_safe=True
            ),
        )
        return _operation(response, "evaluation cancellation")

    async def commit_result(
        self,
        request: evaluation_service_pb2.CommitEvaluationResultRequest,
        *,
        options: CallOptions,
    ) -> tuple[evaluation_result_pb2.EvaluationResult, evaluation_run_pb2.EvaluationRun]:
        materialized = copy.deepcopy(request)
        _validate_commit(self._invoker, materialized)
        materialized, call = _prepare_mutation(
            self._invoker, materialized, options, require_lease=True
        )
        response = cast(
            evaluation_service_pb2.CommitEvaluationResultResponse,
            await self._invoker.unary(
                COMMIT_EVALUATION_RESULT, materialized, call=call, retry_safe=True
            ),
        )
        result = required_response_message(
            response,
            "result",
            evaluation_result_pb2.EvaluationResult,
            label="evaluation result commit",
        )
        run = required_response_message(
            response,
            "evaluation_run",
            evaluation_run_pb2.EvaluationRun,
            label="evaluation result commit",
        )
        if result.name != materialized.result.name or run.name != materialized.evaluation_run.name:
            raise _identity_violation("evaluation result commit response changed durable identity")
        return result, run

    async def get_result(
        self, name: str, *, options: CallOptions | None = None
    ) -> evaluation_result_pb2.EvaluationResult:
        scoped = _scoped_name(self._invoker, name, "evaluationResults")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.GetEvaluationResultResponse,
            await self._invoker.unary(
                GET_EVALUATION_RESULT,
                evaluation_service_pb2.GetEvaluationResultRequest(name=scoped),
                call=call,
                retry_safe=True,
            ),
        )
        result = required_response_message(
            response,
            "result",
            evaluation_result_pb2.EvaluationResult,
            label="evaluation result get",
        )
        if result.name != scoped:
            raise _identity_violation("evaluation result response changed resource identity")
        return result

    async def create_promotion_decision(
        self,
        request: evaluation_service_pb2.CreatePromotionDecisionRequest,
        *,
        options: CallOptions | None = None,
    ) -> operation_pb2.Operation:
        materialized = copy.deepcopy(request)
        _validate_decision(self._invoker, materialized)
        materialized, call = _prepare_mutation(self._invoker, materialized, options)
        response = cast(
            evaluation_service_pb2.CreatePromotionDecisionResponse,
            await self._invoker.unary(
                CREATE_PROMOTION_DECISION, materialized, call=call, retry_safe=True
            ),
        )
        return _operation(response, "promotion decision creation")

    async def get_promotion_decision(
        self, name: str, *, options: CallOptions | None = None
    ) -> promotion_decision_pb2.PromotionDecision:
        scoped = _scoped_name(self._invoker, name, "promotionDecisions")
        call = prepare_call(
            options,
            default_timeout=self._invoker.config.default_timeout,
            require_idempotency=False,
        )
        response = cast(
            evaluation_service_pb2.GetPromotionDecisionResponse,
            await self._invoker.unary(
                GET_PROMOTION_DECISION,
                evaluation_service_pb2.GetPromotionDecisionRequest(name=scoped),
                call=call,
                retry_safe=True,
            ),
        )
        decision = required_response_message(
            response,
            "promotion_decision",
            promotion_decision_pb2.PromotionDecision,
            label="promotion decision get",
        )
        if decision.name != scoped:
            raise _identity_violation("promotion decision response changed resource identity")
        return decision
