use std::{
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    artifact::v1::{ArtifactRef, EvidenceRef},
    common::v1::{CommandContext, PageRequest, PageResponse, ResourceRef},
    internal::{
        artifact::v1::{
            AcquireArtifactLeaseRequest, AcquireArtifactLeaseResponse, GetArtifactRequest,
            GetArtifactResponse, ListArtifactsRequest, ListArtifactsResponse,
            QuarantineArtifactRequest, QuarantineArtifactResponse, ReleaseArtifactLeaseRequest,
            ReleaseArtifactLeaseResponse,
        },
        job::v1::{ListOperationsRequest, ListOperationsResponse},
    },
    operation::v1::{Operation, OperationState},
};
use prost_types::Timestamp;
use tonic::{Request, Response, Status, codegen::async_trait};

use crate::{
    AccessToken, CallOptions, Client, Config, Environment, Identity, RecordingTransport,
    RpcTransport, SubmitOptions, TokenProvider,
};

const PARENT: &str = "tenants/t-1/projects/p-1";
const DIGEST: &str = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const LEASE: &str = "tenants/t-1/projects/p-1/artifactLeases/lease-1";

#[derive(Clone, Debug)]
enum CapturedRequest {
    Get(GetArtifactRequest),
    ListArtifacts(ListArtifactsRequest),
    Quarantine(QuarantineArtifactRequest),
    Acquire(AcquireArtifactLeaseRequest),
    Release(ReleaseArtifactLeaseRequest),
    ListOperations(ListOperationsRequest),
}

#[derive(Default)]
struct GapTransport {
    requests: Mutex<Vec<CapturedRequest>>,
    mutation_metadata: Mutex<Vec<(String, bool)>>,
}

impl GapTransport {
    fn capture_mutation<T>(&self, request: &Request<T>, context: &CommandContext) {
        let key = request
            .metadata()
            .get("idempotency-key")
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_owned();
        self.mutation_metadata
            .lock()
            .unwrap()
            .push((key.clone(), context.idempotency_key == key));
    }
}

#[async_trait]
impl RpcTransport for GapTransport {
    async fn get_artifact(
        &self,
        request: Request<GetArtifactRequest>,
    ) -> Result<Response<GetArtifactResponse>, Status> {
        self.requests
            .lock()
            .unwrap()
            .push(CapturedRequest::Get(request.into_inner()));
        Ok(Response::new(GetArtifactResponse {
            artifact: Some(artifact()),
            observed_at: None,
        }))
    }

    async fn list_artifacts(
        &self,
        request: Request<ListArtifactsRequest>,
    ) -> Result<Response<ListArtifactsResponse>, Status> {
        self.requests
            .lock()
            .unwrap()
            .push(CapturedRequest::ListArtifacts(request.into_inner()));
        Ok(Response::new(ListArtifactsResponse {
            artifacts: vec![artifact()],
            page: Some(PageResponse {
                next_page_token: "artifact-next".to_owned(),
            }),
            read_time: None,
        }))
    }

    async fn quarantine_artifact(
        &self,
        request: Request<QuarantineArtifactRequest>,
    ) -> Result<Response<QuarantineArtifactResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap().clone();
        self.capture_mutation(&request, &context);
        self.requests
            .lock()
            .unwrap()
            .push(CapturedRequest::Quarantine(request.into_inner()));
        Ok(Response::new(QuarantineArtifactResponse {
            operation: Some(operation("operations/quarantine-1")),
        }))
    }

    async fn acquire_artifact_lease(
        &self,
        request: Request<AcquireArtifactLeaseRequest>,
    ) -> Result<Response<AcquireArtifactLeaseResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap().clone();
        self.capture_mutation(&request, &context);
        self.requests
            .lock()
            .unwrap()
            .push(CapturedRequest::Acquire(request.into_inner()));
        Ok(Response::new(AcquireArtifactLeaseResponse {
            lease: Some(lease()),
        }))
    }

    async fn release_artifact_lease(
        &self,
        request: Request<ReleaseArtifactLeaseRequest>,
    ) -> Result<Response<ReleaseArtifactLeaseResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap().clone();
        self.capture_mutation(&request, &context);
        self.requests
            .lock()
            .unwrap()
            .push(CapturedRequest::Release(request.into_inner()));
        Ok(Response::new(ReleaseArtifactLeaseResponse {}))
    }

    async fn list_operations(
        &self,
        request: Request<ListOperationsRequest>,
    ) -> Result<Response<ListOperationsResponse>, Status> {
        self.requests
            .lock()
            .unwrap()
            .push(CapturedRequest::ListOperations(request.into_inner()));
        Ok(Response::new(ListOperationsResponse {
            operations: vec![operation("operations/listed-1")],
            page: Some(PageResponse {
                next_page_token: "operation-next".to_owned(),
            }),
            read_time: None,
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
    let provider: Arc<dyn TokenProvider> = Arc::new(TestTokenProvider);
    Client::with_transport(
        Config::builder(
            Environment::Development,
            Identity::new("t-1", "p-1", "worker-1").unwrap(),
            provider,
        )
        .build()
        .unwrap(),
        transport,
    )
}

fn submit(key: &str) -> SubmitOptions {
    SubmitOptions::new(key).unwrap()
}

fn artifact() -> ArtifactRef {
    ArtifactRef {
        digest: DIGEST.to_owned(),
        integrity_digest: DIGEST.to_owned(),
        media_type: "application/octet-stream".to_owned(),
        size_bytes: 42,
        artifact_kind: "test-fixture".to_owned(),
        ..ArtifactRef::default()
    }
}

fn lease() -> ResourceRef {
    ResourceRef {
        resource_type: "artifact_lease".to_owned(),
        resource_id: "lease-1".to_owned(),
        tenant_id: "t-1".to_owned(),
        project_id: "p-1".to_owned(),
        resource_version: 1,
        name: LEASE.to_owned(),
        etag: "etag-1".to_owned(),
    }
}

fn operation(id: &str) -> Operation {
    Operation {
        operation_id: id.to_owned(),
        tenant_id: "t-1".to_owned(),
        project_id: "p-1".to_owned(),
        state: OperationState::Pending as i32,
        resource_version: 1,
        done: false,
        etag: "etag-1".to_owned(),
        ..Operation::default()
    }
}

fn future_timestamp() -> Timestamp {
    let value = SystemTime::now().duration_since(UNIX_EPOCH).unwrap() + Duration::from_hours(1);
    Timestamp {
        seconds: i64::try_from(value.as_secs()).unwrap(),
        nanos: i32::try_from(value.subsec_nanos()).unwrap(),
    }
}

async fn exercise_artifact_gap_methods(sdk: &Client) {
    sdk.artifacts()
        .get(
            GetArtifactRequest {
                digest: DIGEST.to_owned(),
                ..GetArtifactRequest::default()
            },
            CallOptions::new(),
        )
        .await
        .unwrap();
    let artifact_page = sdk
        .artifacts()
        .list(
            ListArtifactsRequest {
                page: Some(PageRequest {
                    page_size: 100,
                    page_token: "artifact-token".to_owned(),
                }),
                ..ListArtifactsRequest::default()
            },
            CallOptions::new(),
        )
        .await
        .unwrap();
    assert_eq!(artifact_page.page.unwrap().next_page_token, "artifact-next");

    let forged = CommandContext {
        tenant_id: "attacker".to_owned(),
        principal_id: "attacker".to_owned(),
        canonical_request_digest: "attacker".to_owned(),
        ..CommandContext::default()
    };
    let quarantine_input = QuarantineArtifactRequest {
        context: Some(forged.clone()),
        artifact: Some(artifact()),
        reason_code: "POLICY_VIOLATION".to_owned(),
        evidence: vec![EvidenceRef {
            digest: DIGEST.to_owned(),
            subject_digest: DIGEST.to_owned(),
            evidence_kind: "policy-evaluation".to_owned(),
            policy_digest: DIGEST.to_owned(),
        }],
    };
    let unchanged_quarantine = quarantine_input.clone();
    sdk.artifacts()
        .quarantine(quarantine_input, submit("quarantine-1"))
        .await
        .unwrap();
    assert_eq!(unchanged_quarantine.context.unwrap(), forged);

    sdk.artifacts()
        .acquire_lease(
            AcquireArtifactLeaseRequest {
                context: Some(CommandContext {
                    tenant_id: "attacker".to_owned(),
                    ..CommandContext::default()
                }),
                artifact: Some(artifact()),
                expire_time: Some(future_timestamp()),
            },
            submit("acquire-1"),
        )
        .await
        .unwrap();
    sdk.artifacts()
        .release_lease(
            ReleaseArtifactLeaseRequest {
                context: Some(CommandContext {
                    tenant_id: "attacker".to_owned(),
                    ..CommandContext::default()
                }),
                lease: Some(lease()),
                etag: "etag-1".to_owned(),
            },
            submit("release-1"),
        )
        .await
        .unwrap();
}

async fn exercise_operation_gap_method(sdk: &Client) {
    let operation_page = sdk
        .operations()
        .list(
            ListOperationsRequest {
                page: Some(PageRequest {
                    page_size: 200,
                    page_token: "operation-token".to_owned(),
                }),
                ..ListOperationsRequest::default()
            },
            CallOptions::new(),
        )
        .await
        .unwrap();
    assert_eq!(
        operation_page.page.unwrap().next_page_token,
        "operation-next"
    );
}

fn assert_recorded_methods(recording: &RecordingTransport<GapTransport>) {
    let calls = recording.calls();
    assert_eq!(
        calls.iter().map(|call| call.method).collect::<Vec<_>>(),
        vec![
            "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact",
            "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts",
            "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact",
            "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease",
            "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease",
            "/mindclade.internal.job.v1.OperationService/ListOperations",
        ]
    );
    for call in &calls {
        assert!(call.metadata_keys.iter().any(|key| key == "authorization"));
        assert!(
            call.metadata_keys
                .iter()
                .any(|key| key == "x-mindclade-expected-tenant")
        );
    }
}

fn assert_trusted_requests(inner: &GapTransport) {
    let requests = inner.requests.lock().unwrap();
    assert_eq!(requests.len(), 6);
    match &requests[0] {
        CapturedRequest::Get(request) => assert_eq!(request.digest, DIGEST),
        request => panic!("unexpected request: {request:?}"),
    }
    match &requests[1] {
        CapturedRequest::ListArtifacts(request) => {
            assert_eq!(request.parent, PARENT);
            assert_eq!(request.page.as_ref().unwrap().page_token, "artifact-token");
        }
        request => panic!("unexpected request: {request:?}"),
    }
    for request in &requests[2..5] {
        let context = match request {
            CapturedRequest::Quarantine(value) => value.context.as_ref().unwrap(),
            CapturedRequest::Acquire(value) => value.context.as_ref().unwrap(),
            CapturedRequest::Release(value) => value.context.as_ref().unwrap(),
            request => panic!("unexpected mutation: {request:?}"),
        };
        assert_eq!(context.tenant_id, "t-1");
        assert_eq!(context.project_id, "p-1");
        assert_eq!(context.principal_id, "worker-1");
        assert!(context.canonical_request_digest.starts_with("sha256:"));
        assert_eq!(context.canonical_request_digest.len(), 71);
    }
    match &requests[5] {
        CapturedRequest::ListOperations(request) => {
            assert_eq!(request.parent, PARENT);
            assert_eq!(request.page.as_ref().unwrap().page_token, "operation-token");
        }
        request => panic!("unexpected request: {request:?}"),
    }
    assert_eq!(
        *inner.mutation_metadata.lock().unwrap(),
        vec![
            ("quarantine-1".to_owned(), true),
            ("acquire-1".to_owned(), true),
            ("release-1".to_owned(), true),
        ]
    );
}

#[tokio::test]
async fn generated_gap_methods_record_exact_rpcs_and_trusted_requests() {
    let inner = Arc::new(GapTransport::default());
    let recording = Arc::new(RecordingTransport::new(Arc::clone(&inner)));
    let sdk = client(recording.clone());

    exercise_artifact_gap_methods(&sdk).await;
    exercise_operation_gap_method(&sdk).await;
    assert_recorded_methods(&recording);
    assert_trusted_requests(&inner);
}
