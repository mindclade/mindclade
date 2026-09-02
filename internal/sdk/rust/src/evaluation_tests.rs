use std::{
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    common::v1::{CommandContext, PageRequest, PageResponse, ResourceRef},
    evaluation::v1::{EvaluationResult, EvaluationRun, PromotionDecision},
    internal::evaluation::v1::{
        CancelEvaluationRunRequest, CancelEvaluationRunResponse, CommitEvaluationResultRequest,
        CommitEvaluationResultResponse, CreateEvaluationRunRequest, CreateEvaluationRunResponse,
        CreatePromotionDecisionRequest, CreatePromotionDecisionResponse,
        GetEvaluationResultRequest, GetEvaluationResultResponse, GetEvaluationRunRequest,
        GetEvaluationRunResponse, GetPromotionDecisionRequest, GetPromotionDecisionResponse,
        ListEvaluationRunsRequest, ListEvaluationRunsResponse,
    },
    job::v1::{LeaseFence, Operation},
};
use prost_types::Timestamp;
use tonic::{Request, Response, Status, codegen::async_trait};

use crate::{
    AccessToken, CallOptions, Client, Config, Environment, Evaluations, Identity,
    RecordingTransport, RpcTransport, SubmitOptions, TokenProvider,
};

const PARENT: &str = "tenants/t-1/projects/p-1";
const RUN: &str = "tenants/t-1/projects/p-1/evaluationRuns/evaluation-1";
const RESULT: &str = "tenants/t-1/projects/p-1/evaluationResults/result-1";
const DECISION: &str = "tenants/t-1/projects/p-1/promotionDecisions/decision-1";
const MODEL_RELEASE: &str = "tenants/t-1/projects/p-1/models/model-1/releases/v1";

#[derive(Default)]
struct EvaluationTransport {
    methods: Mutex<Vec<&'static str>>,
    contexts: Mutex<Vec<CommandContext>>,
    leases: Mutex<Vec<Option<String>>>,
}

impl EvaluationTransport {
    fn record<T>(
        &self,
        method: &'static str,
        request: &Request<T>,
        context: Option<&CommandContext>,
    ) {
        self.methods.lock().unwrap().push(method);
        if let Some(value) = context {
            self.contexts.lock().unwrap().push(value.clone());
        }
        self.leases.lock().unwrap().push(
            request
                .metadata()
                .get("x-mindclade-lease-token")
                .and_then(|value| value.to_str().ok())
                .map(str::to_owned),
        );
    }
}

fn operation() -> Operation {
    Operation {
        operation_id: "operations/evaluation-test".to_owned(),
        ..Operation::default()
    }
}

#[async_trait]
impl RpcTransport for EvaluationTransport {
    async fn create_evaluation_run(
        &self,
        request: Request<CreateEvaluationRunRequest>,
    ) -> Result<Response<CreateEvaluationRunResponse>, Status> {
        self.record(
            "CreateEvaluationRun",
            &request,
            request.get_ref().context.as_ref(),
        );
        assert_eq!(request.get_ref().parent, PARENT);
        Ok(Response::new(CreateEvaluationRunResponse {
            operation: Some(operation()),
        }))
    }
    async fn get_evaluation_run(
        &self,
        request: Request<GetEvaluationRunRequest>,
    ) -> Result<Response<GetEvaluationRunResponse>, Status> {
        self.record("GetEvaluationRun", &request, None);
        Ok(Response::new(GetEvaluationRunResponse {
            evaluation_run: Some(EvaluationRun {
                name: request.into_inner().name,
                ..EvaluationRun::default()
            }),
        }))
    }
    async fn list_evaluation_runs(
        &self,
        request: Request<ListEvaluationRunsRequest>,
    ) -> Result<Response<ListEvaluationRunsResponse>, Status> {
        self.record("ListEvaluationRuns", &request, None);
        assert_eq!(
            request.get_ref().page.as_ref().unwrap().page_token,
            "opaque"
        );
        Ok(Response::new(ListEvaluationRunsResponse {
            page: Some(PageResponse {
                next_page_token: "next".to_owned(),
            }),
            ..ListEvaluationRunsResponse::default()
        }))
    }
    async fn cancel_evaluation_run(
        &self,
        request: Request<CancelEvaluationRunRequest>,
    ) -> Result<Response<CancelEvaluationRunResponse>, Status> {
        self.record(
            "CancelEvaluationRun",
            &request,
            request.get_ref().context.as_ref(),
        );
        Ok(Response::new(CancelEvaluationRunResponse {
            operation: Some(operation()),
        }))
    }
    async fn commit_evaluation_result(
        &self,
        request: Request<CommitEvaluationResultRequest>,
    ) -> Result<Response<CommitEvaluationResultResponse>, Status> {
        self.record(
            "CommitEvaluationResult",
            &request,
            request.get_ref().context.as_ref(),
        );
        Ok(Response::new(CommitEvaluationResultResponse {
            result: Some(result()),
            evaluation_run: Some(run()),
        }))
    }
    async fn get_evaluation_result(
        &self,
        request: Request<GetEvaluationResultRequest>,
    ) -> Result<Response<GetEvaluationResultResponse>, Status> {
        self.record("GetEvaluationResult", &request, None);
        Ok(Response::new(GetEvaluationResultResponse {
            result: Some(EvaluationResult {
                name: request.into_inner().name,
                ..EvaluationResult::default()
            }),
        }))
    }
    async fn create_promotion_decision(
        &self,
        request: Request<CreatePromotionDecisionRequest>,
    ) -> Result<Response<CreatePromotionDecisionResponse>, Status> {
        self.record(
            "CreatePromotionDecision",
            &request,
            request.get_ref().context.as_ref(),
        );
        assert_eq!(
            request
                .get_ref()
                .promotion_decision
                .as_ref()
                .unwrap()
                .decided_by_principal_ref,
            "worker-1"
        );
        Ok(Response::new(CreatePromotionDecisionResponse {
            operation: Some(operation()),
        }))
    }
    async fn get_promotion_decision(
        &self,
        request: Request<GetPromotionDecisionRequest>,
    ) -> Result<Response<GetPromotionDecisionResponse>, Status> {
        self.record("GetPromotionDecision", &request, None);
        Ok(Response::new(GetPromotionDecisionResponse {
            promotion_decision: Some(PromotionDecision {
                name: request.into_inner().name,
                ..PromotionDecision::default()
            }),
        }))
    }
}

struct TestTokenProvider;
#[async_trait]
impl TokenProvider for TestTokenProvider {
    async fn token(&self, _audience: &str) -> Result<AccessToken, crate::Error> {
        AccessToken::new(
            "short-lived-test-token",
            SystemTime::now() + Duration::from_mins(5),
        )
    }
}

fn client(transport: Arc<dyn RpcTransport>) -> Client {
    let identity = Identity::new("t-1", "p-1", "worker-1").unwrap();
    let provider: Arc<dyn TokenProvider> = Arc::new(TestTokenProvider);
    Client::with_transport(
        Config::builder(Environment::Development, identity, provider)
            .build()
            .unwrap(),
        transport,
    )
}

fn submit(key: &str) -> SubmitOptions {
    SubmitOptions::new(key).unwrap()
}
fn fenced_submit(key: &str) -> SubmitOptions {
    submit(key).with_call_options(
        CallOptions::new()
            .with_lease_token("opaque-lease-capability")
            .unwrap(),
    )
}
fn digest(byte: char) -> String {
    format!("sha256:{}", byte.to_string().repeat(64))
}
fn artifact(kind: &str) -> ArtifactRef {
    ArtifactRef {
        digest: digest('a'),
        integrity_digest: digest('b'),
        media_type: "application/json".to_owned(),
        size_bytes: 42,
        artifact_kind: kind.to_owned(),
        ..ArtifactRef::default()
    }
}
fn reference(resource_type: &str, id: &str, name: &str) -> ResourceRef {
    ResourceRef {
        resource_type: resource_type.to_owned(),
        resource_id: id.to_owned(),
        name: name.to_owned(),
        ..ResourceRef::default()
    }
}
fn run() -> EvaluationRun {
    EvaluationRun {
        name: RUN.to_owned(),
        ..EvaluationRun::default()
    }
}
fn result() -> EvaluationResult {
    EvaluationResult {
        name: RESULT.to_owned(),
        run: Some(reference("evaluation_run", "evaluation-1", RUN)),
        run_digest: digest('c'),
        result_digest: digest('d'),
        ..EvaluationResult::default()
    }
}
fn decision() -> PromotionDecision {
    PromotionDecision {
        name: DECISION.to_owned(),
        candidate_release: Some(reference("model_release", "v1", MODEL_RELEASE)),
        candidate_digest: digest('e'),
        evaluation_results: vec![reference("evaluation_result", "result-1", RESULT)],
        decision_digest: digest('f'),
        ..PromotionDecision::default()
    }
}
fn fence() -> LeaseFence {
    let deadline = SystemTime::now().duration_since(UNIX_EPOCH).unwrap() + Duration::from_mins(5);
    LeaseFence {
        job_id: "jobs/j-1".to_owned(),
        run_id: "runs/r-1".to_owned(),
        attempt_id: "attempts/a-1".to_owned(),
        lease_epoch: 1,
        deadline: Some(Timestamp {
            seconds: i64::try_from(deadline.as_secs()).unwrap(),
            nanos: i32::try_from(deadline.subsec_nanos()).unwrap(),
        }),
        lease_token_digest: digest('1'),
        ..LeaseFence::default()
    }
}

async fn exercise_run_lifecycle(evaluations: &Evaluations) {
    evaluations
        .create_run(
            CreateEvaluationRunRequest {
                evaluation_run_id: "evaluation-1".to_owned(),
                suite: Some(artifact("suite")),
                datasets: vec![artifact("dataset")],
                snapshot: Some(artifact("snapshot")),
                model_release: Some(reference("model_release", "v1", MODEL_RELEASE)),
                inference_protocol: Some(artifact("protocol")),
                ..CreateEvaluationRunRequest::default()
            },
            submit("create-evaluation"),
        )
        .await
        .unwrap();

    assert_eq!(
        evaluations
            .get_run(RUN, "", CallOptions::new())
            .await
            .unwrap()
            .name,
        RUN
    );
    assert_eq!(
        evaluations
            .list_runs(
                ListEvaluationRunsRequest {
                    page: Some(PageRequest {
                        page_size: 10,
                        page_token: "opaque".to_owned()
                    }),
                    ..ListEvaluationRunsRequest::default()
                },
                CallOptions::new()
            )
            .unwrap()
            .next_page()
            .await
            .unwrap()
            .unwrap()
            .next_page_token(),
        "next"
    );
    evaluations
        .cancel_run(
            CancelEvaluationRunRequest {
                name: RUN.to_owned(),
                etag: "etag".to_owned(),
                reason: "operator request".to_owned(),
                ..CancelEvaluationRunRequest::default()
            },
            submit("cancel-evaluation"),
        )
        .await
        .unwrap();
}

async fn exercise_result_and_decision_lifecycle(evaluations: &Evaluations) {
    Box::pin(evaluations.commit_result(
        CommitEvaluationResultRequest {
            evaluation_run: Some(reference("evaluation_run", "evaluation-1", RUN)),
            fence: Some(fence()),
            result: Some(result()),
            etag: "etag".to_owned(),
            ..CommitEvaluationResultRequest::default()
        },
        fenced_submit("commit-evaluation"),
    ))
    .await
    .unwrap();
    assert_eq!(
        evaluations
            .get_result(RESULT, CallOptions::new())
            .await
            .unwrap()
            .name,
        RESULT
    );
    evaluations
        .create_promotion_decision(
            CreatePromotionDecisionRequest {
                promotion_decision: Some(decision()),
                ..CreatePromotionDecisionRequest::default()
            },
            submit("create-decision"),
        )
        .await
        .unwrap();
    assert_eq!(
        evaluations
            .get_promotion_decision(DECISION, CallOptions::new())
            .await
            .unwrap()
            .name,
        DECISION
    );
}

#[tokio::test]
async fn evaluation_facade_covers_all_rpcs_and_fenced_metadata() {
    let inner = Arc::new(EvaluationTransport::default());
    let recording = Arc::new(RecordingTransport::new(Arc::clone(&inner)));
    let evaluations = client(recording.clone()).evaluations();

    exercise_run_lifecycle(&evaluations).await;
    exercise_result_and_decision_lifecycle(&evaluations).await;

    assert_eq!(recording.calls().len(), 8);
    let contexts = inner.contexts.lock().unwrap();
    assert_eq!(contexts.len(), 4);
    assert!(contexts.iter().all(|value| value.tenant_id == "t-1"
        && value.project_id == "p-1"
        && value.principal_id == "worker-1"
        && !value.idempotency_key.is_empty()
        && !value.canonical_request_digest.is_empty()));
    assert_eq!(
        inner.leases.lock().unwrap()[4].as_deref(),
        Some("opaque-lease-capability")
    );
}
