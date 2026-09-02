from __future__ import annotations

import copy
import unittest
from datetime import UTC, datetime, timedelta

from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp
from mindclade.artifact.v1 import artifact_reference_pb2
from mindclade.common.v1 import pagination_pb2, resource_reference_pb2
from mindclade.evaluation.v1 import (
    evaluation_result_pb2,
    evaluation_run_pb2,
    promotion_decision_pb2,
)
from mindclade.internal.evaluation.v1 import evaluation_service_pb2
from mindclade.job.v1 import lease_fencing_pb2, operation_pb2
from mindclade_internal_sdk._invocation import AsyncInvoker, SyncInvoker, canonical_digest
from mindclade_internal_sdk.calls import CallOptions
from mindclade_internal_sdk.config import ClientConfig, Environment
from mindclade_internal_sdk.evaluations import AsyncEvaluations, Evaluations
from mindclade_internal_sdk.testing import FakeAsyncTransport, FakeSyncTransport
from mindclade_internal_sdk.transport import (
    CANCEL_EVALUATION_RUN,
    COMMIT_EVALUATION_RESULT,
    CREATE_EVALUATION_RUN,
    CREATE_PROMOTION_DECISION,
    GET_EVALUATION_RESULT,
    GET_EVALUATION_RUN,
    GET_PROMOTION_DECISION,
    LIST_EVALUATION_RUNS,
    Metadata,
)

PARENT = "tenants/tenant-1/projects/project-1"
RUN_NAME = f"{PARENT}/evaluationRuns/evaluation-1"
RESULT_NAME = f"{PARENT}/evaluationResults/result-1"
DECISION_NAME = f"{PARENT}/promotionDecisions/decision-1"
MODEL_RELEASE_NAME = f"{PARENT}/models/model-1/releases/v1"
METHODS = (
    CREATE_EVALUATION_RUN,
    GET_EVALUATION_RUN,
    LIST_EVALUATION_RUNS,
    CANCEL_EVALUATION_RUN,
    COMMIT_EVALUATION_RESULT,
    GET_EVALUATION_RESULT,
    CREATE_PROMOTION_DECISION,
    GET_PROMOTION_DECISION,
)


def config() -> ClientConfig:
    return ClientConfig(
        tenant_id="tenant-1",
        project_id="project-1",
        principal_id="principal-1",
        environment=Environment.LOCAL,
        endpoint="127.0.0.1:1",
        insecure_for_testing=True,
        default_timeout=1,
    )


def timestamp(value: datetime) -> Timestamp:
    result = Timestamp()
    result.FromDatetime(value)
    return result


def artifact(kind: str) -> artifact_reference_pb2.ArtifactRef:
    return artifact_reference_pb2.ArtifactRef(
        digest="sha256:" + "a" * 64,
        integrity_digest="sha256:" + "b" * 64,
        media_type="application/json",
        size_bytes=42,
        artifact_kind=kind,
    )


def model_release() -> resource_reference_pb2.ResourceRef:
    return resource_reference_pb2.ResourceRef(
        resource_type="model_release", resource_id="v1", name=MODEL_RELEASE_NAME
    )


def run_ref() -> resource_reference_pb2.ResourceRef:
    return resource_reference_pb2.ResourceRef(
        resource_type="evaluation_run", resource_id="evaluation-1", name=RUN_NAME
    )


def run() -> evaluation_run_pb2.EvaluationRun:
    return evaluation_run_pb2.EvaluationRun(
        name=RUN_NAME,
        uid="run-uid",
        revision=2,
        etag="etag-run",
        tenant_id="tenant-1",
        project_id="project-1",
        state=evaluation_run_pb2.EVALUATION_RUN_STATE_SUCCEEDED,
    )


def result() -> evaluation_result_pb2.EvaluationResult:
    return evaluation_result_pb2.EvaluationResult(
        name=RESULT_NAME,
        uid="result-uid",
        run=run_ref(),
        run_digest="sha256:" + "c" * 64,
        result_digest="sha256:" + "d" * 64,
        outcome=evaluation_result_pb2.EVALUATION_RESULT_OUTCOME_PASSED,
    )


def decision() -> promotion_decision_pb2.PromotionDecision:
    return promotion_decision_pb2.PromotionDecision(
        name=DECISION_NAME,
        uid="decision-uid",
        candidate_release=model_release(),
        candidate_digest="sha256:" + "e" * 64,
        target_profile="staging",
        evaluation_results=[
            resource_reference_pb2.ResourceRef(
                resource_type="evaluation_result",
                resource_id="result-1",
                name=RESULT_NAME,
            )
        ],
        outcome=promotion_decision_pb2.PROMOTION_OUTCOME_APPROVE,
        reason_code="QUALIFIED",
        decided_by_principal_ref="forged",
        decided_at=timestamp(datetime.now(UTC)),
        source_revision="revision-1",
        decision_digest="sha256:" + "f" * 64,
    )


def create_request() -> evaluation_service_pb2.CreateEvaluationRunRequest:
    return evaluation_service_pb2.CreateEvaluationRunRequest(
        evaluation_run_id="evaluation-1",
        suite=artifact("evaluation-suite"),
        datasets=[artifact("dataset-manifest")],
        snapshot=artifact("model-snapshot"),
        model_release=model_release(),
        inference_protocol=artifact("inference-protocol"),
    )


def commit_request() -> evaluation_service_pb2.CommitEvaluationResultRequest:
    return evaluation_service_pb2.CommitEvaluationResultRequest(
        evaluation_run=run_ref(),
        fence=lease_fencing_pb2.LeaseFence(
            job_id="jobs/job-1",
            run_id="runs/run-1",
            attempt_id="attempts/attempt-1",
            lease_epoch=1,
            deadline=timestamp(datetime.now(UTC) + timedelta(minutes=1)),
            lease_token_digest="sha256:" + "1" * 64,
        ),
        result=result(),
        etag="etag-run",
    )


def response(request: Message) -> Message:
    if isinstance(request, evaluation_service_pb2.CreateEvaluationRunRequest):
        return evaluation_service_pb2.CreateEvaluationRunResponse(
            operation=operation_pb2.Operation(operation_id="operations/evaluation-create")
        )
    if isinstance(request, evaluation_service_pb2.GetEvaluationRunRequest):
        return evaluation_service_pb2.GetEvaluationRunResponse(evaluation_run=run())
    if isinstance(request, evaluation_service_pb2.ListEvaluationRunsRequest):
        return evaluation_service_pb2.ListEvaluationRunsResponse(
            evaluation_runs=[run()],
            page=pagination_pb2.PageResponse(next_page_token=request.page.page_token + "-next"),
        )
    if isinstance(request, evaluation_service_pb2.CancelEvaluationRunRequest):
        return evaluation_service_pb2.CancelEvaluationRunResponse(
            operation=operation_pb2.Operation(operation_id="operations/evaluation-cancel")
        )
    if isinstance(request, evaluation_service_pb2.CommitEvaluationResultRequest):
        return evaluation_service_pb2.CommitEvaluationResultResponse(
            result=result(), evaluation_run=run()
        )
    if isinstance(request, evaluation_service_pb2.GetEvaluationResultRequest):
        return evaluation_service_pb2.GetEvaluationResultResponse(result=result())
    if isinstance(request, evaluation_service_pb2.CreatePromotionDecisionRequest):
        return evaluation_service_pb2.CreatePromotionDecisionResponse(
            operation=operation_pb2.Operation(operation_id="operations/promotion-decision")
        )
    if isinstance(request, evaluation_service_pb2.GetPromotionDecisionRequest):
        return evaluation_service_pb2.GetPromotionDecisionResponse(promotion_decision=decision())
    raise AssertionError(type(request))


def exercise_sync(
    facade: Evaluations,
) -> tuple[list[Message], list[Metadata]]:
    created = create_request()
    original = copy.deepcopy(created)
    assert facade.create_run(
        created, options=CallOptions(idempotency_key="evaluation-create")
    ).operation_id
    assert created == original
    assert facade.get_run(RUN_NAME).name == RUN_NAME
    assert (
        facade.list_runs(
            evaluation_service_pb2.ListEvaluationRunsRequest(
                page=pagination_pb2.PageRequest(page_size=10, page_token="opaque")
            )
        ).page.next_page_token
        == "opaque-next"
    )
    assert facade.cancel_run(
        evaluation_service_pb2.CancelEvaluationRunRequest(
            name=RUN_NAME, etag="etag-run", reason="operator request"
        ),
        options=CallOptions(idempotency_key="evaluation-cancel"),
    ).operation_id
    with unittest.TestCase().assertRaisesRegex(ValueError, "lease_token"):
        facade.commit_result(
            commit_request(), options=CallOptions(idempotency_key="evaluation-commit")
        )
    committed, completed = facade.commit_result(
        commit_request(),
        options=CallOptions(
            idempotency_key="evaluation-commit", lease_token="opaque-lease-capability"
        ),
    )
    assert committed.name == RESULT_NAME and completed.name == RUN_NAME
    assert facade.get_result(RESULT_NAME).name == RESULT_NAME
    assert facade.create_promotion_decision(
        evaluation_service_pb2.CreatePromotionDecisionRequest(promotion_decision=decision()),
        options=CallOptions(idempotency_key="promotion-decision"),
    ).operation_id
    assert facade.get_promotion_decision(DECISION_NAME).name == DECISION_NAME
    return [], []


class EvaluationFacadeTest(unittest.TestCase):
    def test_all_generated_rpcs_bind_context_scope_and_lease_metadata(self) -> None:
        transport = FakeSyncTransport()
        requests: list[Message] = []
        metadata_values: list[Metadata] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout
            requests.append(copy.deepcopy(request))
            metadata_values.append(metadata)
            return response(request)

        for method in METHODS:
            transport.unary_handlers[method] = handler
        exercise_sync(Evaluations(SyncInvoker(config(), transport)))
        self.assertEqual(len(requests), 8)
        create = requests[0]
        self.assertIsInstance(create, evaluation_service_pb2.CreateEvaluationRunRequest)
        assert isinstance(create, evaluation_service_pb2.CreateEvaluationRunRequest)
        self.assertEqual(create.parent, PARENT)
        self.assertEqual(create.context.tenant_id, "tenant-1")
        self.assertEqual(create.context.project_id, "project-1")
        self.assertEqual(create.context.principal_id, "principal-1")
        canonical = copy.deepcopy(create)
        canonical.ClearField("context")
        self.assertEqual(create.context.canonical_request_digest, canonical_digest(canonical))
        commit = requests[4]
        assert isinstance(commit, evaluation_service_pb2.CommitEvaluationResultRequest)
        self.assertEqual(commit.fence.tenant_id, "tenant-1")
        self.assertEqual(commit.fence.project_id, "project-1")
        self.assertIn(("x-mindclade-lease-token", "opaque-lease-capability"), metadata_values[4])
        promotion = requests[6]
        assert isinstance(promotion, evaluation_service_pb2.CreatePromotionDecisionRequest)
        self.assertEqual(promotion.promotion_decision.decided_by_principal_ref, "principal-1")


class AsyncEvaluationFacadeTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_surface_covers_all_generated_rpcs(self) -> None:
        transport = FakeAsyncTransport()
        requests: list[Message] = []

        def handler(request: Message, timeout: float, metadata: Metadata) -> Message:
            del timeout, metadata
            requests.append(copy.deepcopy(request))
            return response(request)

        for method in METHODS:
            transport.unary_handlers[method] = handler
        facade = AsyncEvaluations(AsyncInvoker(config(), transport))
        self.assertTrue(
            (
                await facade.create_run(
                    create_request(),
                    options=CallOptions(idempotency_key="async-evaluation-create"),
                )
            ).operation_id
        )
        self.assertEqual((await facade.get_run(RUN_NAME)).name, RUN_NAME)
        self.assertEqual(
            (
                await facade.list_runs(
                    evaluation_service_pb2.ListEvaluationRunsRequest(
                        page=pagination_pb2.PageRequest(page_token="opaque")
                    )
                )
            ).page.next_page_token,
            "opaque-next",
        )
        self.assertTrue(
            (
                await facade.cancel_run(
                    evaluation_service_pb2.CancelEvaluationRunRequest(
                        name=RUN_NAME, etag="etag-run", reason="operator request"
                    ),
                    options=CallOptions(idempotency_key="async-evaluation-cancel"),
                )
            ).operation_id
        )
        committed, completed = await facade.commit_result(
            commit_request(),
            options=CallOptions(
                idempotency_key="async-evaluation-commit",
                lease_token="opaque-async-lease-capability",
            ),
        )
        self.assertEqual((committed.name, completed.name), (RESULT_NAME, RUN_NAME))
        self.assertEqual((await facade.get_result(RESULT_NAME)).name, RESULT_NAME)
        self.assertTrue(
            (
                await facade.create_promotion_decision(
                    evaluation_service_pb2.CreatePromotionDecisionRequest(
                        promotion_decision=decision()
                    ),
                    options=CallOptions(idempotency_key="async-promotion-decision"),
                )
            ).operation_id
        )
        self.assertEqual((await facade.get_promotion_decision(DECISION_NAME)).name, DECISION_NAME)
        self.assertEqual(len(requests), 8)


if __name__ == "__main__":
    unittest.main()
