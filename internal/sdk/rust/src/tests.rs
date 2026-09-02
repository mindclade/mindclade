use std::{
    collections::VecDeque,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    time::{Duration, SystemTime},
};

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    common::v1::{CommandContext, PageRequest, PageResponse, ResourceRef},
    dataset::v1::{
        CreateDatasetCommand, Dataset, DatasetRelease, PublishDatasetReleaseCommand,
        RevokeDatasetReleaseCommand, UpdateDatasetCommand,
    },
    inference::v1::{
        InferenceFinalUpdate, InferenceHeartbeat, InferenceProgress, InferenceRequest,
        InferenceResult, InferenceStreamCursor, InferenceStreamMessage, inference_stream_message,
    },
    internal::{
        artifact::v1::{
            AbortArtifactUploadRequest, AbortArtifactUploadResponse, ArtifactStagingReceipt,
            ArtifactUploadSession, ArtifactUploadState, BeginArtifactUploadRequest,
            BeginArtifactUploadResponse, CommitArtifactRequest, CommitArtifactResponse,
            DownloadArtifactRequest, DownloadArtifactResponse, FinalizeArtifactUploadRequest,
            FinalizeArtifactUploadResponse, GetArtifactUploadRequest, GetArtifactUploadResponse,
            QuarantineArtifactUploadRequest, QuarantineArtifactUploadResponse,
            ResolveArtifactAliasRequest, ResolveArtifactAliasResponse, UploadArtifactChunkRequest,
            UploadArtifactChunkResponse,
        },
        dataset::v1::{
            CreateDatasetRequest, CreateDatasetResponse, GetDatasetReleaseRequest,
            GetDatasetReleaseResponse, GetDatasetRequest, GetDatasetResponse,
            ListDatasetReleasesRequest, ListDatasetReleasesResponse, ListDatasetsRequest,
            ListDatasetsResponse, PublishDatasetReleaseRequest, PublishDatasetReleaseResponse,
            RevokeDatasetReleaseRequest, RevokeDatasetReleaseResponse, UpdateDatasetRequest,
            UpdateDatasetResponse,
        },
        inference::v1::{
            CommitInferenceResultRequest, CommitInferenceResultResponse,
            GetInferenceRequestRequest, GetInferenceRequestResponse, GetInferenceResultRequest,
            GetInferenceResultResponse, SubmitInferenceRequest, SubmitInferenceResponse,
            WatchInferenceRequest, WatchInferenceResponse,
        },
        job::v1::{
            CancelOperationRequest, CancelOperationResponse, GetOperationRequest,
            GetOperationResponse, WatchOperationRequest, WatchOperationResponse,
        },
        model::v1::{
            GetModelReleaseRequest, GetModelReleaseResponse, GetModelRequest, GetModelResponse,
            ListModelReleasesRequest, ListModelReleasesResponse, ListModelsRequest,
            ListModelsResponse, PromoteModelReleaseRequest, PromoteModelReleaseResponse,
            RegisterModelReleaseRequest, RegisterModelReleaseResponse, RegisterModelRequest,
            RegisterModelResponse, RevokeModelReleaseRequest, RevokeModelReleaseResponse,
        },
        training::v1::{CreateTrainingRunRequest, CreateTrainingRunResponse},
    },
    job::v1::{LeaseFence, Operation, OperationState},
    model::v1::{
        Model, ModelRelease, PromoteModelReleaseCommand, RegisterModelCommand,
        RegisterModelReleaseCommand, RevokeModelReleaseCommand,
    },
    training::v1::CreateTrainingRunCommand,
};
use prost_types::Timestamp;
use sha2::{Digest, Sha256};
use tonic::{
    Code, Request, Response, Status,
    codegen::{async_trait, tokio_stream},
    metadata::MetadataValue,
};

use crate::{
    AccessToken, ArtifactStream, ArtifactUploadOptions, CallOptions, CancellationToken, Client,
    Config, Environment, Error, ErrorKind, GcpWorkloadIdentityProvider, Identity, InferenceStream,
    InferenceWaitOptions, OperationStream, PaginationLimits, PaginationPage, RecordingTransport,
    FenceState, FinalCause, JitterSource, QuotaState, RetryPolicy, RpcTransport, SubmitOptions,
    SystemJitter, TokenProvider, WaitOptions,
    auth::GcpIdentityTokenExchange,
    error::{
        FENCE_PRECONDITION_TYPE, QUOTA_PRECONDITION_TYPE, REVISION_PRECONDITION_TYPE,
        retryable_status_code,
    },
    paginate,
    retry::{CallSafety, Sleeper, never_retry_method, registered_method_safety},
    testing::ScriptedJitter,
};

struct FakeTokenProvider {
    calls: AtomicUsize,
    audiences: Mutex<Vec<String>>,
    lifetime: Duration,
}

struct HangingTokenProvider;

struct FakeGcpExchange {
    calls: AtomicUsize,
    audiences: Mutex<Vec<String>>,
    response: Mutex<String>,
}

#[async_trait]
impl GcpIdentityTokenExchange for FakeGcpExchange {
    async fn exchange(&self, audience: &str) -> Result<String, Error> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        self.audiences.lock().unwrap().push(audience.to_owned());
        tokio::task::yield_now().await;
        Ok(self.response.lock().unwrap().clone())
    }
}

#[async_trait]
impl TokenProvider for HangingTokenProvider {
    async fn token(&self, _audience: &str) -> Result<AccessToken, Error> {
        std::future::pending().await
    }
}

impl FakeTokenProvider {
    fn new(lifetime: Duration) -> Self {
        Self {
            calls: AtomicUsize::new(0),
            audiences: Mutex::new(Vec::new()),
            lifetime,
        }
    }
}

#[async_trait]
impl TokenProvider for FakeTokenProvider {
    async fn token(&self, audience: &str) -> Result<AccessToken, Error> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        self.audiences.lock().unwrap().push(audience.to_owned());
        AccessToken::new("test-short-lived-token", SystemTime::now() + self.lifetime)
    }
}

#[derive(Clone, Debug)]
struct ObservedMetadata {
    request_id: Option<String>,
    trace_id: Option<String>,
    idempotency_key: Option<String>,
    expected_tenant: Option<String>,
    expected_project: Option<String>,
    expected_principal: Option<String>,
    sdk: Option<String>,
    retry_count: Option<String>,
    timeout_ms: Option<String>,
    authorization_present: bool,
    authorization_sensitive: bool,
    deadline_present: bool,
}

impl ObservedMetadata {
    fn capture<T>(request: &Request<T>) -> Self {
        let authorization = request.metadata().get("authorization");
        Self {
            request_id: metadata(request, "x-request-id"),
            trace_id: metadata(request, "x-trace-id"),
            idempotency_key: metadata(request, "idempotency-key"),
            expected_tenant: metadata(request, "x-mindclade-expected-tenant"),
            expected_project: metadata(request, "x-mindclade-expected-project"),
            expected_principal: metadata(request, "x-mindclade-expected-principal"),
            sdk: metadata(request, "x-mindclade-sdk"),
            retry_count: metadata(request, "x-mindclade-retry-count"),
            timeout_ms: metadata(request, "x-mindclade-timeout-ms"),
            authorization_present: authorization.is_some(),
            authorization_sensitive: authorization.is_some_and(MetadataValue::is_sensitive),
            deadline_present: request.metadata().get("grpc-timeout").is_some(),
        }
    }
}

fn metadata<T>(request: &Request<T>, key: &str) -> Option<String> {
    request
        .metadata()
        .get(key)
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned)
}

#[derive(Default)]
struct FakeTransport {
    training: Mutex<VecDeque<Result<CreateTrainingRunResponse, Status>>>,
    operations: Mutex<VecDeque<Result<GetOperationResponse, Status>>>,
    cancellations: Mutex<VecDeque<Result<CancelOperationResponse, Status>>>,
    watches: Mutex<VecDeque<WatchScript>>,
    watch_after_sequences: Mutex<Vec<u64>>,
    aliases: Mutex<VecDeque<Result<ResolveArtifactAliasResponse, Status>>>,
    begin_uploads: Mutex<VecDeque<Result<BeginArtifactUploadResponse, Status>>>,
    upload_chunks: Mutex<VecDeque<Result<UploadArtifactChunkResponse, Status>>>,
    get_uploads: Mutex<VecDeque<Result<GetArtifactUploadResponse, Status>>>,
    finalize_uploads: Mutex<VecDeque<Result<FinalizeArtifactUploadResponse, Status>>>,
    abort_uploads: Mutex<VecDeque<Result<AbortArtifactUploadResponse, Status>>>,
    quarantine_uploads: Mutex<VecDeque<Result<QuarantineArtifactUploadResponse, Status>>>,
    commits: Mutex<VecDeque<Result<CommitArtifactResponse, Status>>>,
    downloads: Mutex<VecDeque<ArtifactDownloadScript>>,
    inference_submissions: Mutex<VecDeque<Result<SubmitInferenceResponse, Status>>>,
    inference_requests: Mutex<VecDeque<Result<GetInferenceRequestResponse, Status>>>,
    inference_results: Mutex<VecDeque<Result<GetInferenceResultResponse, Status>>>,
    inference_commits: Mutex<VecDeque<Result<CommitInferenceResultResponse, Status>>>,
    inference_watches: Mutex<VecDeque<InferenceWatchScript>>,
    submitted_inference: Mutex<Vec<InferenceRequest>>,
    committed_inference: Mutex<Vec<CommitInferenceResultRequest>>,
    inference_watch_cursors: Mutex<Vec<Option<InferenceStreamCursor>>>,
    create_datasets: Mutex<VecDeque<Result<CreateDatasetResponse, Status>>>,
    get_datasets: Mutex<VecDeque<Result<GetDatasetResponse, Status>>>,
    list_datasets: Mutex<VecDeque<Result<ListDatasetsResponse, Status>>>,
    update_datasets: Mutex<VecDeque<Result<UpdateDatasetResponse, Status>>>,
    publish_dataset_releases: Mutex<VecDeque<Result<PublishDatasetReleaseResponse, Status>>>,
    revoke_dataset_releases: Mutex<VecDeque<Result<RevokeDatasetReleaseResponse, Status>>>,
    get_dataset_releases: Mutex<VecDeque<Result<GetDatasetReleaseResponse, Status>>>,
    list_dataset_releases: Mutex<VecDeque<Result<ListDatasetReleasesResponse, Status>>>,
    register_models: Mutex<VecDeque<Result<RegisterModelResponse, Status>>>,
    get_models: Mutex<VecDeque<Result<GetModelResponse, Status>>>,
    list_models: Mutex<VecDeque<Result<ListModelsResponse, Status>>>,
    register_model_releases: Mutex<VecDeque<Result<RegisterModelReleaseResponse, Status>>>,
    get_model_releases: Mutex<VecDeque<Result<GetModelReleaseResponse, Status>>>,
    list_model_releases: Mutex<VecDeque<Result<ListModelReleasesResponse, Status>>>,
    promote_model_releases: Mutex<VecDeque<Result<PromoteModelReleaseResponse, Status>>>,
    revoke_model_releases: Mutex<VecDeque<Result<RevokeModelReleaseResponse, Status>>>,
    begin_upload_calls: AtomicUsize,
    uploaded_chunks: Mutex<Vec<UploadArtifactChunkRequest>>,
    observed: Mutex<Vec<ObservedMetadata>>,
    submitted_commands: Mutex<Vec<CreateTrainingRunCommand>>,
    lifecycle_contexts: Mutex<Vec<CommandContext>>,
    lifecycle_page_tokens: Mutex<Vec<String>>,
    hang_operations: AtomicBool,
    hang_downloads: AtomicBool,
}

type WatchScript = Result<Vec<Result<WatchOperationResponse, Status>>, Status>;
type ArtifactDownloadScript = Result<Vec<Result<DownloadArtifactResponse, Status>>, Status>;
type InferenceWatchScript = Result<Vec<Result<WatchInferenceResponse, Status>>, Status>;

impl FakeTransport {
    fn observe<T>(&self, request: &Request<T>) {
        self.observed
            .lock()
            .unwrap()
            .push(ObservedMetadata::capture(request));
    }

    fn pop<T>(queue: &Mutex<VecDeque<Result<T, Status>>>) -> Result<T, Status> {
        queue
            .lock()
            .unwrap()
            .pop_front()
            .unwrap_or_else(|| Err(Status::unimplemented("fake response was not configured")))
    }

    fn capture_context(&self, context: Option<&CommandContext>) {
        if let Some(context) = context {
            self.lifecycle_contexts
                .lock()
                .unwrap()
                .push(context.clone());
        }
    }

    fn capture_page(&self, page: Option<&PageRequest>) {
        if let Some(page) = page {
            self.lifecycle_page_tokens
                .lock()
                .unwrap()
                .push(page.page_token.clone());
        }
    }
}

#[async_trait]
impl RpcTransport for FakeTransport {
    async fn create_training_run(
        &self,
        request: Request<CreateTrainingRunRequest>,
    ) -> Result<Response<CreateTrainingRunResponse>, Status> {
        self.observe(&request);
        if let Some(command) = request.into_inner().command {
            self.submitted_commands.lock().unwrap().push(command);
        }
        Self::pop(&self.training).map(Response::new)
    }

    async fn create_dataset(
        &self,
        request: Request<CreateDatasetRequest>,
    ) -> Result<Response<CreateDatasetResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.create_datasets).map(Response::new)
    }

    async fn get_dataset(
        &self,
        request: Request<GetDatasetRequest>,
    ) -> Result<Response<GetDatasetResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.get_datasets).map(Response::new)
    }

    async fn list_datasets(
        &self,
        request: Request<ListDatasetsRequest>,
    ) -> Result<Response<ListDatasetsResponse>, Status> {
        self.observe(&request);
        self.capture_page(request.get_ref().page.as_ref());
        Self::pop(&self.list_datasets).map(Response::new)
    }

    async fn update_dataset(
        &self,
        request: Request<UpdateDatasetRequest>,
    ) -> Result<Response<UpdateDatasetResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.update_datasets).map(Response::new)
    }

    async fn publish_dataset_release(
        &self,
        request: Request<PublishDatasetReleaseRequest>,
    ) -> Result<Response<PublishDatasetReleaseResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.publish_dataset_releases).map(Response::new)
    }

    async fn revoke_dataset_release(
        &self,
        request: Request<RevokeDatasetReleaseRequest>,
    ) -> Result<Response<RevokeDatasetReleaseResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.revoke_dataset_releases).map(Response::new)
    }

    async fn get_dataset_release(
        &self,
        request: Request<GetDatasetReleaseRequest>,
    ) -> Result<Response<GetDatasetReleaseResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.get_dataset_releases).map(Response::new)
    }

    async fn list_dataset_releases(
        &self,
        request: Request<ListDatasetReleasesRequest>,
    ) -> Result<Response<ListDatasetReleasesResponse>, Status> {
        self.observe(&request);
        self.capture_page(request.get_ref().page.as_ref());
        Self::pop(&self.list_dataset_releases).map(Response::new)
    }

    async fn register_model(
        &self,
        request: Request<RegisterModelRequest>,
    ) -> Result<Response<RegisterModelResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.register_models).map(Response::new)
    }

    async fn get_model(
        &self,
        request: Request<GetModelRequest>,
    ) -> Result<Response<GetModelResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.get_models).map(Response::new)
    }

    async fn list_models(
        &self,
        request: Request<ListModelsRequest>,
    ) -> Result<Response<ListModelsResponse>, Status> {
        self.observe(&request);
        self.capture_page(request.get_ref().page.as_ref());
        Self::pop(&self.list_models).map(Response::new)
    }

    async fn register_model_release(
        &self,
        request: Request<RegisterModelReleaseRequest>,
    ) -> Result<Response<RegisterModelReleaseResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.register_model_releases).map(Response::new)
    }

    async fn get_model_release(
        &self,
        request: Request<GetModelReleaseRequest>,
    ) -> Result<Response<GetModelReleaseResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.get_model_releases).map(Response::new)
    }

    async fn list_model_releases(
        &self,
        request: Request<ListModelReleasesRequest>,
    ) -> Result<Response<ListModelReleasesResponse>, Status> {
        self.observe(&request);
        self.capture_page(request.get_ref().page.as_ref());
        Self::pop(&self.list_model_releases).map(Response::new)
    }

    async fn promote_model_release(
        &self,
        request: Request<PromoteModelReleaseRequest>,
    ) -> Result<Response<PromoteModelReleaseResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.promote_model_releases).map(Response::new)
    }

    async fn revoke_model_release(
        &self,
        request: Request<RevokeModelReleaseRequest>,
    ) -> Result<Response<RevokeModelReleaseResponse>, Status> {
        self.observe(&request);
        self.capture_context(
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|command| command.context.as_ref()),
        );
        Self::pop(&self.revoke_model_releases).map(Response::new)
    }

    async fn get_operation(
        &self,
        request: Request<GetOperationRequest>,
    ) -> Result<Response<GetOperationResponse>, Status> {
        self.observe(&request);
        if self.hang_operations.load(Ordering::Relaxed) {
            return std::future::pending().await;
        }
        Self::pop(&self.operations).map(Response::new)
    }

    async fn cancel_operation(
        &self,
        request: Request<CancelOperationRequest>,
    ) -> Result<Response<CancelOperationResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.cancellations).map(Response::new)
    }

    async fn watch_operation(
        &self,
        request: Request<WatchOperationRequest>,
    ) -> Result<Response<OperationStream>, Status> {
        self.observe(&request);
        self.watch_after_sequences
            .lock()
            .unwrap()
            .push(request.get_ref().after_sequence);
        let updates = Self::pop(&self.watches)?;
        let stream: OperationStream = Box::pin(tokio_stream::iter(updates));
        Ok(Response::new(stream))
    }

    async fn resolve_artifact_alias(
        &self,
        request: Request<ResolveArtifactAliasRequest>,
    ) -> Result<Response<ResolveArtifactAliasResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.aliases).map(Response::new)
    }

    async fn begin_artifact_upload(
        &self,
        request: Request<BeginArtifactUploadRequest>,
    ) -> Result<Response<BeginArtifactUploadResponse>, Status> {
        self.observe(&request);
        self.begin_upload_calls.fetch_add(1, Ordering::Relaxed);
        Self::pop(&self.begin_uploads).map(Response::new)
    }

    async fn upload_artifact_chunk(
        &self,
        request: Request<UploadArtifactChunkRequest>,
    ) -> Result<Response<UploadArtifactChunkResponse>, Status> {
        self.observe(&request);
        self.uploaded_chunks
            .lock()
            .unwrap()
            .push(request.into_inner());
        Self::pop(&self.upload_chunks).map(Response::new)
    }

    async fn get_artifact_upload(
        &self,
        request: Request<GetArtifactUploadRequest>,
    ) -> Result<Response<GetArtifactUploadResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.get_uploads).map(Response::new)
    }

    async fn finalize_artifact_upload(
        &self,
        request: Request<FinalizeArtifactUploadRequest>,
    ) -> Result<Response<FinalizeArtifactUploadResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.finalize_uploads).map(Response::new)
    }

    async fn abort_artifact_upload(
        &self,
        request: Request<AbortArtifactUploadRequest>,
    ) -> Result<Response<AbortArtifactUploadResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.abort_uploads).map(Response::new)
    }

    async fn quarantine_artifact_upload(
        &self,
        request: Request<QuarantineArtifactUploadRequest>,
    ) -> Result<Response<QuarantineArtifactUploadResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.quarantine_uploads).map(Response::new)
    }

    async fn commit_artifact(
        &self,
        request: Request<CommitArtifactRequest>,
    ) -> Result<Response<CommitArtifactResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.commits).map(Response::new)
    }

    async fn download_artifact(
        &self,
        request: Request<DownloadArtifactRequest>,
    ) -> Result<Response<ArtifactStream>, Status> {
        self.observe(&request);
        if self.hang_downloads.load(Ordering::Relaxed) {
            std::future::pending::<()>().await;
        }
        let updates = Self::pop(&self.downloads)?;
        let stream: ArtifactStream = Box::pin(tokio_stream::iter(updates));
        Ok(Response::new(stream))
    }

    async fn submit_inference(
        &self,
        request: Request<SubmitInferenceRequest>,
    ) -> Result<Response<SubmitInferenceResponse>, Status> {
        self.observe(&request);
        if let Some(value) = request.into_inner().inference_request {
            self.submitted_inference.lock().unwrap().push(value);
        }
        Self::pop(&self.inference_submissions).map(Response::new)
    }

    async fn get_inference_request(
        &self,
        request: Request<GetInferenceRequestRequest>,
    ) -> Result<Response<GetInferenceRequestResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.inference_requests).map(Response::new)
    }

    async fn get_inference_result(
        &self,
        request: Request<GetInferenceResultRequest>,
    ) -> Result<Response<GetInferenceResultResponse>, Status> {
        self.observe(&request);
        Self::pop(&self.inference_results).map(Response::new)
    }

    async fn commit_inference_result(
        &self,
        request: Request<CommitInferenceResultRequest>,
    ) -> Result<Response<CommitInferenceResultResponse>, Status> {
        self.observe(&request);
        self.committed_inference
            .lock()
            .unwrap()
            .push(request.into_inner());
        Self::pop(&self.inference_commits).map(Response::new)
    }

    async fn watch_inference(
        &self,
        request: Request<WatchInferenceRequest>,
    ) -> Result<Response<InferenceStream>, Status> {
        self.observe(&request);
        self.inference_watch_cursors
            .lock()
            .unwrap()
            .push(request.get_ref().cursor.clone());
        let updates = Self::pop(&self.inference_watches)?;
        let stream: InferenceStream = Box::pin(tokio_stream::iter(updates));
        Ok(Response::new(stream))
    }
}

#[derive(Default)]
struct ImmediateSleeper {
    delays: Mutex<Vec<Duration>>,
}

#[async_trait]
impl Sleeper for ImmediateSleeper {
    async fn sleep(&self, duration: Duration) {
        self.delays.lock().unwrap().push(duration);
    }
}

fn test_config(provider: Arc<dyn TokenProvider>, attempts: u8, poll_interval: Duration) -> Config {
    let identity = Identity::new("tenants/t-1", "projects/p-1", "principals/worker-1").unwrap();
    Config::builder(Environment::Development, identity, provider)
        .retry_policy(
            RetryPolicy::new(attempts, Duration::from_millis(1), Duration::from_millis(8)).unwrap(),
        )
        .poll_interval(poll_interval)
        // Every delay assertion in this module is exact, so the default
        // full-jitter window is pinned to its maximum unless a test scripts
        // its own fractions.
        .jitter_source(Arc::new(ScriptedJitter::max()))
        .build()
        .unwrap()
}

fn operation(id: &str, done: bool) -> Operation {
    Operation {
        operation_id: id.to_owned(),
        state: if done {
            OperationState::Succeeded as i32
        } else {
            OperationState::Running as i32
        },
        done,
        ..Operation::default()
    }
}

fn artifact_for(content: &[u8]) -> ArtifactRef {
    ArtifactRef {
        digest: format!("sha256:{:x}", Sha256::digest(content)),
        media_type: "application/octet-stream".to_owned(),
        size_bytes: i64::try_from(content.len()).unwrap(),
        artifact_kind: "test-fixture".to_owned(),
        integrity_digest: format!("sha256:{:x}", Sha256::digest(content)),
        ..ArtifactRef::default()
    }
}

fn upload_session(
    artifact: &ArtifactRef,
    offset: i64,
    next_chunk_index: i64,
    revision: i64,
    state: ArtifactUploadState,
) -> ArtifactUploadSession {
    ArtifactUploadSession {
        name: "tenants/t-1/projects/p-1/artifactUploads/resume-1".to_owned(),
        artifact: Some(artifact.clone()),
        state: state as i32,
        committed_offset: offset,
        next_chunk_index,
        create_time: Some(Timestamp {
            seconds: 1_780_000_000,
            nanos: 0,
        }),
        update_time: Some(Timestamp {
            seconds: 1_780_000_000 + revision,
            nanos: 0,
        }),
        expire_time: Some(Timestamp {
            seconds: 1_780_007_200,
            nanos: 0,
        }),
        revision,
        etag: format!("etag-{revision}"),
        ..ArtifactUploadSession::default()
    }
}

fn staging_receipt(artifact: &ArtifactRef) -> ArtifactStagingReceipt {
    ArtifactStagingReceipt {
        receipt_digest: format!("sha256:{:064x}", 7),
        artifact: Some(artifact.clone()),
        verified_at: Some(Timestamp {
            seconds: 1_780_000_010,
            nanos: 0,
        }),
        expire_time: Some(Timestamp {
            seconds: 1_780_086_400,
            nanos: 0,
        }),
    }
}

fn unavailable_with_request_id() -> Status {
    let mut status = Status::unavailable("sensitive request payload must not escape");
    status.metadata_mut().insert(
        "x-request-id",
        MetadataValue::try_from("server-request-7").unwrap(),
    );
    status
        .metadata_mut()
        .insert("retry-after-ms", MetadataValue::try_from("2").unwrap());
    status
}

#[test]
fn config_is_tls_secure_by_default_and_plaintext_is_test_scoped() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let identity = Identity::new("tenant", "project", "principal").unwrap();
    let config = Config::builder(
        Environment::Production,
        identity.clone(),
        Arc::clone(&provider),
    )
    .build()
    .unwrap();
    assert!(config.endpoint().starts_with("https://"));

    let production_plaintext = Config::builder(
        Environment::Production,
        identity.clone(),
        Arc::clone(&provider),
    )
    .endpoint("http://127.0.0.1:9443")
    .insecure_loopback_for_testing()
    .build();
    assert!(production_plaintext.is_err());

    let implicit_plaintext =
        Config::builder(Environment::Local, identity.clone(), Arc::clone(&provider))
            .endpoint("http://127.0.0.1:9443")
            .build();
    assert!(implicit_plaintext.is_err());

    let credentialed_local =
        Config::builder(Environment::Local, identity.clone(), Arc::clone(&provider))
            .endpoint("http://127.0.0.1:9443")
            .insecure_loopback_for_testing()
            .build();
    assert!(credentialed_local.is_err());

    let local = Config::local_insecure_builder(identity.clone())
        .build()
        .unwrap();
    assert_eq!(local.endpoint(), "http://127.0.0.1:9443");
    assert!(local.token_provider.is_none());

    let path_endpoint = Config::builder(Environment::Development, identity, provider)
        .endpoint("https://control-plane.example/v1")
        .build();
    assert!(path_endpoint.is_err());
}

#[tokio::test]
async fn gcp_workload_identity_validates_caches_singleflights_and_redacts() {
    let expires_at = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 3_600;
    let payload = base64url(
        format!("{{\"aud\":\"https://control-plane.example\",\"exp\":{expires_at}}}").as_bytes(),
    );
    let exchange = Arc::new(FakeGcpExchange {
        calls: AtomicUsize::new(0),
        audiences: Mutex::new(Vec::new()),
        response: Mutex::new(format!("e30.{payload}.signature")),
    });
    let exchange_trait: Arc<dyn GcpIdentityTokenExchange> = exchange.clone();
    let provider =
        GcpWorkloadIdentityProvider::with_test_exchange(Duration::from_millis(100), exchange_trait)
            .unwrap();

    let (first, second) = tokio::join!(
        provider.token("https://control-plane.example"),
        provider.token("https://control-plane.example")
    );
    let first = first.unwrap();
    let second = second.unwrap();
    assert_eq!(
        first.authorization_value(SystemTime::now()).unwrap(),
        second.authorization_value(SystemTime::now()).unwrap()
    );
    assert_eq!(exchange.calls.load(Ordering::Relaxed), 1);
    provider
        .token("https://control-plane.example")
        .await
        .unwrap();
    assert_eq!(exchange.calls.load(Ordering::Relaxed), 1);
    assert!(provider.token("bad audience\n").await.is_err());

    let wrong_audience_payload =
        base64url(format!("{{\"aud\":\"https://wrong.example\",\"exp\":{expires_at}}}").as_bytes());
    *exchange.response.lock().unwrap() = format!("e30.{wrong_audience_payload}.signature");
    let error = provider.token("https://other.example").await.unwrap_err();
    assert!(!error.to_string().contains("secret"));
}

#[test]
fn identity_and_tokens_reject_injection_and_redact_secrets() {
    assert!(Identity::new("tenant\nforged", "project", "principal").is_err());
    assert!(SubmitOptions::new("idempotency\nforged").is_err());
    assert!(
        AccessToken::new(
            "token with spaces",
            SystemTime::now() + Duration::from_mins(1)
        )
        .is_err()
    );
    let token = AccessToken::new(
        "highly-sensitive-token",
        SystemTime::now() + Duration::from_hours(1),
    )
    .unwrap();
    let debug = format!("{token:?}");
    assert!(debug.contains("<redacted>"));
    assert!(!debug.contains("highly-sensitive-token"));
    assert!(
        AccessToken::new("long-lived", SystemTime::now() + Duration::from_hours(2))
            .unwrap()
            .authorization_value(SystemTime::now())
            .is_err()
    );
}

#[tokio::test]
async fn training_submit_retries_idempotently_and_binds_generated_context() {
    let provider = Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let provider_trait: Arc<dyn TokenProvider> = provider.clone();
    let config = test_config(provider_trait, 3, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    transport.training.lock().unwrap().extend([
        Err(unavailable_with_request_id()),
        Ok(CreateTrainingRunResponse {
            operation: Some(operation("operations/op-1", false)),
        }),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let transport_trait: Arc<dyn RpcTransport> = transport.clone();
    let sleeper_trait: Arc<dyn Sleeper> = sleeper.clone();
    let client = Client::with_test_sleeper(config, transport_trait, sleeper_trait);

    let call = CallOptions::new()
        .with_request_id("client-request-1")
        .unwrap()
        .with_trace_id("trace-1")
        .unwrap();
    let options = SubmitOptions::new("idem-1")
        .unwrap()
        .with_call_options(call)
        .with_correlation_id("correlation-1")
        .unwrap();
    let command = CreateTrainingRunCommand {
        context: Some(CommandContext {
            tenant_id: "forged-tenant".to_owned(),
            ..CommandContext::default()
        }),
        training_run_id: "run-1".to_owned(),
        ..CreateTrainingRunCommand::default()
    };

    let result = client.training().submit(command, options).await.unwrap();
    assert_eq!(result.operation_id, "operations/op-1");
    assert_eq!(provider.calls.load(Ordering::Relaxed), 2);
    assert_eq!(
        sleeper.delays.lock().unwrap().as_slice(),
        [Duration::from_millis(2)]
    );

    let observed = transport.observed.lock().unwrap();
    assert_eq!(observed.len(), 2);
    for value in observed.iter() {
        assert_eq!(value.request_id.as_deref(), Some("client-request-1"));
        assert_eq!(value.trace_id.as_deref(), Some("trace-1"));
        assert_eq!(value.idempotency_key.as_deref(), Some("idem-1"));
        assert_eq!(value.expected_tenant.as_deref(), Some("tenants/t-1"));
        assert_eq!(value.expected_project.as_deref(), Some("projects/p-1"));
        assert_eq!(
            value.expected_principal.as_deref(),
            Some("principals/worker-1")
        );
        assert!(
            value
                .sdk
                .as_deref()
                .is_some_and(|sdk| sdk.starts_with("mindclade-internal-rust-sdk/"))
        );
        assert!(value.authorization_present);
        assert!(value.authorization_sensitive);
        assert!(value.deadline_present);
    }
    drop(observed);

    let commands = transport.submitted_commands.lock().unwrap();
    assert_eq!(commands.len(), 2);
    let context = commands[0].context.as_ref().unwrap();
    assert_eq!(context.tenant_id, "tenants/t-1");
    assert_eq!(context.project_id, "projects/p-1");
    assert_eq!(context.principal_id, "principals/worker-1");
    assert_eq!(context.idempotency_key, "idem-1");
    assert!(context.canonical_request_digest.starts_with("sha256:"));
    assert_eq!(context.canonical_request_digest.len(), 71);
    assert_eq!(
        commands[1]
            .context
            .as_ref()
            .unwrap()
            .canonical_request_digest,
        context.canonical_request_digest
    );
    assert_eq!(context.correlation_id, "correlation-1");
    assert!(context.deadline.is_some());
    assert_eq!(
        provider.audiences.lock().unwrap().as_slice(),
        [
            "https://control-plane.development.mindclade.internal",
            "https://control-plane.development.mindclade.internal"
        ]
    );
}

#[tokio::test]
async fn normalized_errors_preserve_code_request_id_and_retryability_without_payload() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 1, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    transport
        .operations
        .lock()
        .unwrap()
        .push_back(Err(unavailable_with_request_id()));
    let client = Client::with_transport(config, transport);

    let error = client
        .operations()
        .get("operations/op-1", CallOptions::new())
        .await
        .unwrap_err();
    assert_eq!(error.kind(), ErrorKind::RetryableService);
    assert_eq!(error.stable_code(), "mindclade.service_unavailable");
    assert_eq!(error.code(), Some(Code::Unavailable));
    assert_eq!(error.request_id(), Some("server-request-7"));
    assert!(error.is_retryable());
    assert_eq!(error.retry_after(), Some(Duration::from_millis(2)));
    assert!(!error.to_string().contains("sensitive request payload"));
}

#[tokio::test]
async fn operation_polling_reaches_terminal_state_and_honors_cancellation() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 1, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    transport.operations.lock().unwrap().extend([
        Ok(GetOperationResponse {
            operation: Some(operation("operations/op-2", false)),
        }),
        Ok(GetOperationResponse {
            operation: Some(operation("operations/op-2", true)),
        }),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(config, transport.clone(), sleeper.clone());
    let result = client
        .operations()
        .wait(
            "operations/op-2",
            WaitOptions::new()
                .with_timeout(Duration::from_secs(1))
                .unwrap(),
            CancellationToken::new(),
        )
        .await
        .unwrap();
    assert!(result.done);
    assert_eq!(sleeper.delays.lock().unwrap().len(), 1);

    let cancelled = CancellationToken::new();
    cancelled.cancel();
    let error = client
        .operations()
        .wait("operations/op-3", WaitOptions::new(), cancelled)
        .await
        .unwrap_err();
    assert_eq!(error.sdk_error().unwrap().kind(), ErrorKind::Cancelled);
}

#[tokio::test]
async fn failed_operation_returns_typed_generated_failure() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 1, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    transport
        .operations
        .lock()
        .unwrap()
        .push_back(Ok(GetOperationResponse {
            operation: Some(Operation {
                operation_id: "operations/failed".to_owned(),
                state: OperationState::Failed as i32,
                done: true,
                ..Operation::default()
            }),
        }));
    let client = Client::with_transport(config, transport);
    let error = client
        .operations()
        .wait(
            "operations/failed",
            WaitOptions::new(),
            CancellationToken::new(),
        )
        .await
        .unwrap_err();
    let failure = error.operation_failure().unwrap();
    assert_eq!(failure.operation().operation_id, "operations/failed");
    assert!(!format!("{failure:?}").contains("ErrorDetail"));
}

#[tokio::test]
async fn watch_is_resumable_monotonic_and_cancellation_aware() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 3, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    transport.watches.lock().unwrap().extend([
        Ok(vec![
            Ok(WatchOperationResponse {
                operation: Some(operation("operations/op-4", false)),
                sequence: 2,
                observed_at: None,
            }),
            Ok(WatchOperationResponse {
                operation: Some(operation("operations/op-4", false)),
                sequence: 3,
                observed_at: None,
            }),
            Err(Status::unavailable("stream interrupted with secret detail")),
        ]),
        Ok(vec![
            Ok(WatchOperationResponse {
                operation: Some(operation("operations/op-4", false)),
                sequence: 3,
                observed_at: None,
            }),
            Ok(WatchOperationResponse {
                operation: Some(operation("operations/op-4", true)),
                sequence: 4,
                observed_at: None,
            }),
        ]),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(config, transport.clone(), sleeper.clone());
    let cancellation = CancellationToken::new();
    let mut watch = client
        .operations()
        .watch(
            "operations/op-4",
            2,
            &CallOptions::new(),
            cancellation.clone(),
        )
        .unwrap();
    let update = watch.next().await.unwrap().unwrap();
    assert_eq!(update.sequence, 3);
    let terminal = watch.next().await.unwrap().unwrap();
    assert_eq!(terminal.sequence, 4);
    assert_eq!(watch.last_sequence(), 4);
    assert_eq!(
        transport.watch_after_sequences.lock().unwrap().as_slice(),
        [2, 3]
    );
    assert_eq!(
        sleeper.delays.lock().unwrap().as_slice(),
        [Duration::from_millis(1)]
    );
    assert!(watch.next().await.unwrap().is_none());

    let mut cancelled_watch = client
        .operations()
        .watch(
            "operations/op-cancelled",
            0,
            &CallOptions::new(),
            cancellation.clone(),
        )
        .unwrap();
    cancellation.cancel();
    let error = cancelled_watch.next().await.unwrap_err();
    assert_eq!(error.kind(), ErrorKind::Cancelled);
}

#[tokio::test]
async fn operation_watch_rejects_missing_or_cross_resource_identity() {
    for operation_id in ["", "operations/wrong"] {
        let provider: Arc<dyn TokenProvider> =
            Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
        let config = test_config(provider, 1, Duration::from_millis(1));
        let transport = Arc::new(FakeTransport::default());
        transport
            .watches
            .lock()
            .unwrap()
            .push_back(Ok(vec![Ok(WatchOperationResponse {
                operation: Some(operation(operation_id, false)),
                sequence: 1,
                observed_at: None,
            })]));
        let client = Client::with_transport(config, transport);
        let mut watch = client
            .operations()
            .watch(
                "operations/expected",
                0,
                &CallOptions::new(),
                CancellationToken::new(),
            )
            .unwrap();
        let error = watch.next().await.unwrap_err();
        assert_eq!(error.kind(), ErrorKind::Protocol);
    }
}

#[tokio::test]
async fn local_plaintext_never_acquires_or_transmits_credentials() {
    let identity = Identity::new("tenant", "project", "principal").unwrap();
    let config = Config::local_insecure_builder(identity).build().unwrap();
    let transport = Arc::new(FakeTransport::default());
    transport
        .operations
        .lock()
        .unwrap()
        .push_back(Ok(GetOperationResponse {
            operation: Some(operation("operations/local", true)),
        }));
    let client = Client::with_transport(config, transport.clone());
    client
        .operations()
        .get("operations/local", CallOptions::new())
        .await
        .unwrap();
    assert!(!transport.observed.lock().unwrap()[0].authorization_present);
}

#[tokio::test]
async fn recording_transport_covers_the_generated_facade_without_payloads() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 1, Duration::from_millis(1));
    let delegate = Arc::new(FakeTransport::default());
    delegate
        .operations
        .lock()
        .unwrap()
        .push_back(Ok(GetOperationResponse {
            operation: Some(operation("operations/recorded", true)),
        }));
    let recorder = Arc::new(RecordingTransport::new(delegate));
    let transport: Arc<dyn RpcTransport> = recorder.clone();
    let client = Client::with_transport(config, transport);
    client
        .operations()
        .get("operations/recorded", CallOptions::new())
        .await
        .unwrap();
    let calls = recorder.calls();
    assert_eq!(calls.len(), 1);
    assert_eq!(
        calls[0].method,
        "/mindclade.internal.job.v1.OperationService/GetOperation"
    );
    assert!(
        calls[0]
            .metadata_keys
            .iter()
            .any(|key| key == "authorization")
    );
    assert!(!format!("{:?}", calls[0]).contains("short-lived-test-token"));
}

#[test]
fn unregistered_methods_are_never_retryable_by_metadata() {
    assert_eq!(
        registered_method_safety("/unknown/Mutation"),
        CallSafety::Unsafe
    );
}

#[tokio::test]
#[allow(clippy::too_many_lines)] // One table-style flow intentionally proves all sixteen RPCs.
async fn dataset_and_model_facades_cover_every_generated_rpc_and_bind_sdk_identity() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 1, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    let project = "tenants/t-1/projects/p-1";
    let dataset_name = format!("{project}/datasets/dataset-1");
    let dataset_release_name = format!("{dataset_name}/releases/release-1");
    let model_name = format!("{project}/models/model-1");
    let model_release_name = format!("{model_name}/releases/release-1");

    transport
        .create_datasets
        .lock()
        .unwrap()
        .push_back(Ok(CreateDatasetResponse {
            operation: Some(operation("operations/dataset-create", false)),
        }));
    transport
        .get_datasets
        .lock()
        .unwrap()
        .push_back(Ok(GetDatasetResponse {
            dataset: Some(Dataset {
                name: dataset_name.clone(),
                ..Dataset::default()
            }),
        }));
    transport
        .list_datasets
        .lock()
        .unwrap()
        .push_back(Ok(ListDatasetsResponse {
            datasets: vec![Dataset {
                name: dataset_name.clone(),
                ..Dataset::default()
            }],
            page: Some(PageResponse {
                next_page_token: "opaque-dataset-next".to_owned(),
            }),
            read_time: None,
        }));
    transport
        .update_datasets
        .lock()
        .unwrap()
        .push_back(Ok(UpdateDatasetResponse {
            operation: Some(operation("operations/dataset-update", false)),
        }));
    transport
        .publish_dataset_releases
        .lock()
        .unwrap()
        .push_back(Ok(PublishDatasetReleaseResponse {
            operation: Some(operation("operations/dataset-publish", false)),
        }));
    transport
        .revoke_dataset_releases
        .lock()
        .unwrap()
        .push_back(Ok(RevokeDatasetReleaseResponse {
            operation: Some(operation("operations/dataset-revoke", false)),
        }));
    transport
        .get_dataset_releases
        .lock()
        .unwrap()
        .push_back(Ok(GetDatasetReleaseResponse {
            dataset_release: Some(DatasetRelease {
                name: dataset_release_name.clone(),
                ..DatasetRelease::default()
            }),
        }));
    transport
        .list_dataset_releases
        .lock()
        .unwrap()
        .push_back(Ok(ListDatasetReleasesResponse {
            dataset_releases: vec![DatasetRelease {
                name: dataset_release_name.clone(),
                ..DatasetRelease::default()
            }],
            page: Some(PageResponse {
                next_page_token: "opaque-dataset-release-next".to_owned(),
            }),
            read_time: None,
        }));

    transport
        .register_models
        .lock()
        .unwrap()
        .push_back(Ok(RegisterModelResponse {
            operation: Some(operation("operations/model-register", false)),
        }));
    transport
        .get_models
        .lock()
        .unwrap()
        .push_back(Ok(GetModelResponse {
            model: Some(Model {
                name: model_name.clone(),
                ..Model::default()
            }),
        }));
    transport
        .list_models
        .lock()
        .unwrap()
        .push_back(Ok(ListModelsResponse {
            models: vec![Model {
                name: model_name.clone(),
                ..Model::default()
            }],
            page: Some(PageResponse {
                next_page_token: "opaque-model-next".to_owned(),
            }),
            read_time: None,
        }));
    transport
        .register_model_releases
        .lock()
        .unwrap()
        .push_back(Ok(RegisterModelReleaseResponse {
            operation: Some(operation("operations/model-release-register", false)),
        }));
    transport
        .get_model_releases
        .lock()
        .unwrap()
        .push_back(Ok(GetModelReleaseResponse {
            model_release: Some(ModelRelease {
                name: model_release_name.clone(),
                ..ModelRelease::default()
            }),
        }));
    transport
        .list_model_releases
        .lock()
        .unwrap()
        .push_back(Ok(ListModelReleasesResponse {
            model_releases: vec![ModelRelease {
                name: model_release_name.clone(),
                ..ModelRelease::default()
            }],
            page: Some(PageResponse {
                next_page_token: "opaque-model-release-next".to_owned(),
            }),
            read_time: None,
        }));
    transport
        .promote_model_releases
        .lock()
        .unwrap()
        .push_back(Ok(PromoteModelReleaseResponse {
            operation: Some(operation("operations/model-release-promote", false)),
        }));
    transport
        .revoke_model_releases
        .lock()
        .unwrap()
        .push_back(Ok(RevokeModelReleaseResponse {
            operation: Some(operation("operations/model-release-revoke", false)),
        }));

    let transport_trait: Arc<dyn RpcTransport> = transport.clone();
    let client = Client::with_transport(config, transport_trait);
    let submit = |key: &str| SubmitOptions::new(key).unwrap();

    assert_eq!(
        client
            .datasets()
            .create(
                CreateDatasetCommand {
                    context: Some(CommandContext {
                        tenant_id: "forged".to_owned(),
                        ..CommandContext::default()
                    }),
                    dataset_id: "dataset-1".to_owned(),
                    ..CreateDatasetCommand::default()
                },
                submit("dataset-create"),
            )
            .await
            .unwrap()
            .operation_id,
        "operations/dataset-create"
    );
    assert_eq!(
        client
            .datasets()
            .get(&dataset_name, "etag-1", CallOptions::new())
            .await
            .unwrap()
            .name,
        dataset_name
    );
    let datasets = client
        .datasets()
        .list(
            ListDatasetsRequest {
                page: Some(PageRequest {
                    page_token: "opaque-dataset".to_owned(),
                    page_size: 25,
                }),
                ..ListDatasetsRequest::default()
            },
            CallOptions::new(),
        )
        .await
        .unwrap();
    assert_eq!(datasets.datasets.len(), 1);
    assert_eq!(
        datasets.page.unwrap().next_page_token,
        "opaque-dataset-next"
    );
    client
        .datasets()
        .update(
            UpdateDatasetCommand {
                dataset: Some(Dataset {
                    name: dataset_name.clone(),
                    ..Dataset::default()
                }),
                etag: "etag-1".to_owned(),
                ..UpdateDatasetCommand::default()
            },
            submit("dataset-update"),
        )
        .await
        .unwrap();
    client
        .datasets()
        .publish_release(
            PublishDatasetReleaseCommand {
                dataset: Some(ResourceRef {
                    name: dataset_name.clone(),
                    ..ResourceRef::default()
                }),
                release_id: "release-1".to_owned(),
                ..PublishDatasetReleaseCommand::default()
            },
            submit("dataset-publish"),
        )
        .await
        .unwrap();
    client
        .datasets()
        .revoke_release(
            RevokeDatasetReleaseCommand {
                dataset_release: Some(ResourceRef {
                    name: dataset_release_name.clone(),
                    ..ResourceRef::default()
                }),
                etag: "etag-2".to_owned(),
                reason: "superseded".to_owned(),
                ..RevokeDatasetReleaseCommand::default()
            },
            submit("dataset-revoke"),
        )
        .await
        .unwrap();
    assert_eq!(
        client
            .datasets()
            .get_release(&dataset_release_name, CallOptions::new())
            .await
            .unwrap()
            .name,
        dataset_release_name
    );
    let releases = client
        .datasets()
        .list_releases(
            ListDatasetReleasesRequest {
                parent: dataset_name.clone(),
                page: Some(PageRequest {
                    page_token: "opaque-dataset-release".to_owned(),
                    page_size: 10,
                }),
                ..ListDatasetReleasesRequest::default()
            },
            CallOptions::new(),
        )
        .await
        .unwrap();
    assert_eq!(releases.dataset_releases.len(), 1);

    client
        .models()
        .register(
            RegisterModelCommand {
                context: Some(CommandContext {
                    principal_id: "forged".to_owned(),
                    ..CommandContext::default()
                }),
                model_id: "model-1".to_owned(),
                ..RegisterModelCommand::default()
            },
            submit("model-register"),
        )
        .await
        .unwrap();
    assert_eq!(
        client
            .models()
            .get(&model_name, "etag-3", CallOptions::new())
            .await
            .unwrap()
            .name,
        model_name
    );
    let models = client
        .models()
        .list(
            ListModelsRequest {
                page: Some(PageRequest {
                    page_token: "opaque-model".to_owned(),
                    page_size: 25,
                }),
                ..ListModelsRequest::default()
            },
            CallOptions::new(),
        )
        .await
        .unwrap();
    assert_eq!(models.models.len(), 1);
    client
        .models()
        .register_release(
            RegisterModelReleaseCommand {
                model: Some(ResourceRef {
                    name: model_name.clone(),
                    ..ResourceRef::default()
                }),
                release_id: "release-1".to_owned(),
                ..RegisterModelReleaseCommand::default()
            },
            submit("model-release-register"),
        )
        .await
        .unwrap();
    assert_eq!(
        client
            .models()
            .get_release(&model_release_name, CallOptions::new())
            .await
            .unwrap()
            .name,
        model_release_name
    );
    let model_releases = client
        .models()
        .list_releases(
            ListModelReleasesRequest {
                parent: model_name.clone(),
                page: Some(PageRequest {
                    page_token: "opaque-model-release".to_owned(),
                    page_size: 10,
                }),
                ..ListModelReleasesRequest::default()
            },
            CallOptions::new(),
        )
        .await
        .unwrap();
    assert_eq!(model_releases.model_releases.len(), 1);
    client
        .models()
        .promote_release(
            PromoteModelReleaseCommand {
                model_release: Some(ResourceRef {
                    name: model_release_name.clone(),
                    ..ResourceRef::default()
                }),
                etag: "etag-4".to_owned(),
                ..PromoteModelReleaseCommand::default()
            },
            submit("model-release-promote"),
        )
        .await
        .unwrap();
    client
        .models()
        .revoke_release(
            RevokeModelReleaseCommand {
                model_release: Some(ResourceRef {
                    name: model_release_name,
                    ..ResourceRef::default()
                }),
                etag: "etag-5".to_owned(),
                reason: "superseded".to_owned(),
                ..RevokeModelReleaseCommand::default()
            },
            submit("model-release-revoke"),
        )
        .await
        .unwrap();

    let contexts = transport.lifecycle_contexts.lock().unwrap();
    assert_eq!(contexts.len(), 8);
    for context in contexts.iter() {
        assert_eq!(context.tenant_id, "tenants/t-1");
        assert_eq!(context.project_id, "projects/p-1");
        assert_eq!(context.principal_id, "principals/worker-1");
        assert!(!context.idempotency_key.is_empty());
        // Rust/Prost map encoding is not canonical across processes. The
        // authoritative Go service computes and persists the deterministic
        // digest after validating this SDK-owned identity context.
        assert!(context.canonical_request_digest.is_empty());
        assert!(context.deadline.is_some());
    }
    drop(contexts);
    assert_eq!(
        transport.lifecycle_page_tokens.lock().unwrap().as_slice(),
        [
            "opaque-dataset",
            "opaque-dataset-release",
            "opaque-model",
            "opaque-model-release"
        ]
    );
    let observed = transport.observed.lock().unwrap();
    assert_eq!(observed.len(), 16);
    assert_eq!(
        observed
            .iter()
            .filter(|entry| entry.idempotency_key.is_some())
            .count(),
        8
    );
    assert!(observed.iter().all(|entry| entry.deadline_present));
}

#[test]
fn dataset_and_model_retry_registry_is_complete_and_fail_closed() {
    let idempotent = [
        "/mindclade.internal.dataset.v1.DatasetService/CreateDataset",
        "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset",
        "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease",
        "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease",
        "/mindclade.internal.model.v1.ModelService/RegisterModel",
        "/mindclade.internal.model.v1.ModelService/RegisterModelRelease",
        "/mindclade.internal.model.v1.ModelService/PromoteModelRelease",
        "/mindclade.internal.model.v1.ModelService/RevokeModelRelease",
    ];
    let safe = [
        "/mindclade.internal.dataset.v1.DatasetService/GetDataset",
        "/mindclade.internal.dataset.v1.DatasetService/ListDatasets",
        "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease",
        "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases",
        "/mindclade.internal.model.v1.ModelService/GetModel",
        "/mindclade.internal.model.v1.ModelService/ListModels",
        "/mindclade.internal.model.v1.ModelService/GetModelRelease",
        "/mindclade.internal.model.v1.ModelService/ListModelReleases",
    ];
    assert!(
        idempotent
            .iter()
            .all(|method| registered_method_safety(method) == CallSafety::Idempotent)
    );
    assert!(
        safe.iter()
            .all(|method| registered_method_safety(method) == CallSafety::Safe)
    );
    assert_eq!(
        registered_method_safety("/mindclade.internal.model.v1.ModelService/UnknownMutation"),
        CallSafety::Unsafe
    );
}

#[tokio::test]
async fn artifact_alias_resolution_uses_generated_reference_and_rejects_missing_payload() {
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 1, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    transport.aliases.lock().unwrap().extend([
        Ok(ResolveArtifactAliasResponse {
            artifact: Some(ArtifactRef {
                digest: "sha256:artifact".to_owned(),
                ..ArtifactRef::default()
            }),
        }),
        Ok(ResolveArtifactAliasResponse { artifact: None }),
    ]);
    let client = Client::with_transport(config, transport);
    let artifact = client
        .artifacts()
        .resolve_alias("projects/p-1", "latest", CallOptions::new())
        .await
        .unwrap();
    assert_eq!(artifact.digest, "sha256:artifact");

    let error = client
        .artifacts()
        .resolve_alias("projects/p-1", "missing", CallOptions::new())
        .await
        .unwrap_err();
    assert_eq!(error.kind(), ErrorKind::Protocol);
}

#[tokio::test]
#[allow(clippy::too_many_lines)]
async fn artifact_upload_resumes_in_a_fresh_client_and_verifies_generated_transfer() {
    let content = b"abcdef";
    let artifact = artifact_for(content);
    let open = upload_session(&artifact, 0, 0, 1, ArtifactUploadState::Open);
    let partial = upload_session(&artifact, 3, 1, 2, ArtifactUploadState::Open);
    let complete = upload_session(&artifact, 6, 2, 3, ArtifactUploadState::Open);
    let receipt = staging_receipt(&artifact);
    let mut finalized = upload_session(&artifact, 6, 2, 4, ArtifactUploadState::Finalized);
    finalized.staging_receipt = Some(receipt.clone());

    let transport = Arc::new(FakeTransport::default());
    transport.get_uploads.lock().unwrap().extend([
        Err(Status::not_found("new session")),
        Ok(GetArtifactUploadResponse {
            upload: Some(partial.clone()),
        }),
    ]);
    transport
        .begin_uploads
        .lock()
        .unwrap()
        .push_back(Ok(BeginArtifactUploadResponse { upload: Some(open) }));
    transport.upload_chunks.lock().unwrap().extend([
        Ok(UploadArtifactChunkResponse {
            upload: Some(partial),
        }),
        Err(Status::aborted("simulated process loss")),
        Ok(UploadArtifactChunkResponse {
            upload: Some(complete),
        }),
    ]);
    transport
        .finalize_uploads
        .lock()
        .unwrap()
        .push_back(Ok(FinalizeArtifactUploadResponse {
            upload: Some(finalized),
            staging_receipt: Some(receipt.clone()),
        }));
    transport
        .commits
        .lock()
        .unwrap()
        .push_back(Ok(CommitArtifactResponse {
            artifact: Some(artifact.clone()),
        }));
    transport
        .downloads
        .lock()
        .unwrap()
        .push_back(Ok(vec![Ok(DownloadArtifactResponse {
            artifact: Some(artifact.clone()),
            offset: 0,
            data: content.to_vec(),
            chunk_digest: format!("sha256:{:x}", Sha256::digest(content)),
            complete: true,
        })]));

    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = test_config(provider, 1, Duration::from_millis(1));
    let options = ArtifactUploadOptions::new("resume-1")
        .unwrap()
        .with_chunk_bytes(3)
        .unwrap();
    let first = Client::with_transport(config.clone(), transport.clone());
    let mut first_source = &content[..];
    let error = first
        .artifacts()
        .upload(artifact.clone(), &mut first_source, options.clone())
        .await
        .unwrap_err();
    assert_eq!(error.code(), Some(Code::Aborted));

    let second = Client::with_transport(config, transport.clone());
    let mut resumed_source = &content[..];
    let resumed_receipt = second
        .artifacts()
        .upload(artifact.clone(), &mut resumed_source, options)
        .await
        .unwrap();
    assert_eq!(resumed_receipt, receipt);
    assert_eq!(transport.begin_upload_calls.load(Ordering::Relaxed), 1);
    {
        let chunks = transport.uploaded_chunks.lock().unwrap();
        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].data, b"abc");
        assert_eq!(chunks[1].data, b"def");
        assert_eq!(chunks[2].data, b"def");
        assert!(chunks.iter().all(|request| {
            request.context.as_ref().is_some_and(|context| {
                context.canonical_request_digest.starts_with("sha256:")
                    && !context.idempotency_key.is_empty()
            })
        }));
    }

    let committed = second
        .artifacts()
        .commit(
            resumed_receipt,
            SubmitOptions::new("commit-resume-1").unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(committed, artifact);
    let mut destination = Vec::new();
    let downloaded = second
        .artifacts()
        .download(&artifact, &mut destination, CallOptions::new())
        .await
        .unwrap();
    assert_eq!(downloaded, 6);
    assert_eq!(destination, content);
}

fn artifact_download_test_directory() -> std::path::PathBuf {
    let directory = std::env::temp_dir().join(format!(
        "mindclade-sdk-artifact-{}",
        crate::request::generate_request_id()
    ));
    std::fs::create_dir(&directory).unwrap();
    directory
}

#[tokio::test]
async fn artifact_download_file_is_atomic_verified_and_no_clobber() {
    let content = b"atomic-artifact";
    let artifact = artifact_for(content);
    let download = |corrupt: bool| {
        Ok(vec![Ok(DownloadArtifactResponse {
            artifact: Some(artifact.clone()),
            offset: 0,
            data: content.to_vec(),
            chunk_digest: if corrupt {
                format!("sha256:{}", "0".repeat(64))
            } else {
                format!("sha256:{:x}", Sha256::digest(content))
            },
            complete: true,
        })])
    };
    let transport = Arc::new(FakeTransport::default());
    transport.downloads.lock().unwrap().extend([
        download(false),
        download(false),
        download(true),
        download(false),
        download(false),
    ]);
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let client = Client::with_transport(
        test_config(provider, 1, Duration::from_millis(1)),
        transport.clone(),
    );
    let artifacts = client.artifacts();
    let directory = artifact_download_test_directory();

    let destination = directory.join("artifact.bin");
    assert_eq!(
        artifacts
            .download_file(&artifact, &destination, CallOptions::new())
            .await
            .unwrap(),
        u64::try_from(content.len()).unwrap()
    );
    assert_eq!(std::fs::read(&destination).unwrap(), content);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        assert_eq!(
            std::fs::metadata(&destination)
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o600
        );
    }

    let existing_error = artifacts
        .download_file(&artifact, &destination, CallOptions::new())
        .await
        .unwrap_err();
    assert_eq!(existing_error.kind(), ErrorKind::AlreadyExists);
    assert_eq!(std::fs::read(&destination).unwrap(), content);

    let corrupt_destination = directory.join("corrupt.bin");
    let corrupt_error = artifacts
        .download_file(&artifact, &corrupt_destination, CallOptions::new())
        .await
        .unwrap_err();
    assert_eq!(corrupt_error.kind(), ErrorKind::Protocol);
    assert!(!corrupt_destination.exists());

    let race_destination = directory.join("race.bin");
    let left_artifacts = artifacts.clone();
    let right_artifacts = artifacts.clone();
    let (left, right) = tokio::join!(
        left_artifacts.download_file(&artifact, &race_destination, CallOptions::new()),
        right_artifacts.download_file(&artifact, &race_destination, CallOptions::new())
    );
    assert!(matches!(
        (&left, &right),
        (Ok(_), Err(error)) | (Err(error), Ok(_))
            if error.kind() == ErrorKind::AlreadyExists
    ));
    assert_eq!(std::fs::read(&race_destination).unwrap(), content);

    transport.hang_downloads.store(true, Ordering::Relaxed);
    let cancelled_destination = directory.join("cancelled.bin");
    assert!(
        tokio::time::timeout(
            Duration::from_millis(10),
            artifacts.download_file(&artifact, &cancelled_destination, CallOptions::new())
        )
        .await
        .is_err()
    );
    transport.hang_downloads.store(false, Ordering::Relaxed);
    assert!(!cancelled_destination.exists());
    assert!(std::fs::read_dir(&directory).unwrap().all(|entry| {
        !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".mindclade-download-")
    }));
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn artifact_abort_and_quarantine_require_declared_terminal_states() {
    let content = b"abc";
    let artifact = artifact_for(content);
    let aborted = upload_session(&artifact, 0, 0, 2, ArtifactUploadState::Aborted);
    let quarantined = upload_session(&artifact, 0, 0, 2, ArtifactUploadState::Quarantined);
    let transport = Arc::new(FakeTransport::default());
    transport
        .abort_uploads
        .lock()
        .unwrap()
        .push_back(Ok(AbortArtifactUploadResponse {
            upload: Some(aborted.clone()),
        }));
    transport
        .quarantine_uploads
        .lock()
        .unwrap()
        .push_back(Ok(QuarantineArtifactUploadResponse {
            upload: Some(quarantined.clone()),
        }));
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let client = Client::with_transport(
        test_config(provider, 1, Duration::from_millis(1)),
        transport,
    );
    let aborted_result = client
        .artifacts()
        .abort_upload(
            aborted.name.clone(),
            "etag-1",
            "CLIENT_CANCELLED",
            SubmitOptions::new("abort-resume-1").unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(aborted_result.state, ArtifactUploadState::Aborted as i32);
    let quarantined_result = client
        .artifacts()
        .quarantine_upload(
            quarantined.name.clone(),
            "etag-1",
            "DIGEST_MISMATCH",
            SubmitOptions::new("quarantine-resume-1").unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(
        quarantined_result.state,
        ArtifactUploadState::Quarantined as i32
    );
}

#[tokio::test]
async fn inference_submit_and_commit_materialize_authenticated_context() {
    let transport = Arc::new(FakeTransport::default());
    transport
        .inference_submissions
        .lock()
        .unwrap()
        .push_back(Ok(SubmitInferenceResponse {
            operation: Some(Operation {
                operation_id: "operations/inference-1".to_owned(),
                ..Operation::default()
            }),
        }));
    let terminal = Operation {
        operation_id: "operations/inference-1".to_owned(),
        done: true,
        state: OperationState::Succeeded as i32,
        ..Operation::default()
    };
    let result = InferenceResult {
        name: "inferenceResults/result-1".to_owned(),
        ..InferenceResult::default()
    };
    transport
        .inference_commits
        .lock()
        .unwrap()
        .push_back(Ok(CommitInferenceResultResponse {
            result: Some(result.clone()),
            operation: Some(terminal.clone()),
        }));
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let client = Client::with_transport(
        test_config(provider, 3, Duration::from_millis(1)),
        transport.clone(),
    );

    let submitted = client
        .inference()
        .submit(
            InferenceRequest {
                name: "inferenceRequests/request-1".to_owned(),
                tenant_id: "caller-tenant".to_owned(),
                project_id: "caller-project".to_owned(),
                context: Some(CommandContext {
                    principal_id: "caller-principal".to_owned(),
                    ..CommandContext::default()
                }),
                ..InferenceRequest::default()
            },
            SubmitOptions::new("submit-inference-1").unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(submitted.operation_id, "operations/inference-1");
    {
        let captured = transport.submitted_inference.lock().unwrap();
        let submitted_request = captured.first().unwrap();
        assert_eq!(submitted_request.tenant_id, "tenants/t-1");
        assert_eq!(submitted_request.project_id, "projects/p-1");
        let context = submitted_request.context.as_ref().unwrap();
        assert_eq!(context.principal_id, "principals/worker-1");
        assert_eq!(context.idempotency_key, "submit-inference-1");
        assert!(context.canonical_request_digest.starts_with("sha256:"));
    }

    let (committed, operation) = Box::pin(client.inference().commit_result(
        CommitInferenceResultRequest {
            inference_request: Some(ResourceRef {
                name: "inferenceRequests/request-1".to_owned(),
                ..ResourceRef::default()
            }),
            fence: Some(LeaseFence::default()),
            result: Some(result.clone()),
            request_digest: "sha256:request".to_owned(),
            ..CommitInferenceResultRequest::default()
        },
        SubmitOptions::new("commit-inference-1").unwrap(),
    ))
    .await
    .unwrap();
    assert_eq!(committed, result);
    assert_eq!(operation, terminal);
    let commits = transport.committed_inference.lock().unwrap();
    let context = commits.first().unwrap().context.as_ref().unwrap();
    assert_eq!(context.idempotency_key, "commit-inference-1");
    assert_eq!(context.principal_id, "principals/worker-1");
    assert!(context.canonical_request_digest.starts_with("sha256:"));
}

#[tokio::test]
async fn inference_watch_reconnects_from_exact_durable_cursor_and_waits_for_result() {
    let request_name = "inferenceRequests/request-2";
    let progress = WatchInferenceResponse {
        message: Some(InferenceStreamMessage {
            request_name: request_name.to_owned(),
            sequence: 1,
            resume_token: "cursor-1".to_owned(),
            update: Some(inference_stream_message::Update::Progress(
                InferenceProgress::default(),
            )),
            ..InferenceStreamMessage::default()
        }),
    };
    let heartbeat = WatchInferenceResponse {
        message: Some(InferenceStreamMessage {
            request_name: request_name.to_owned(),
            sequence: 1,
            resume_token: "cursor-1".to_owned(),
            update: Some(inference_stream_message::Update::Heartbeat(
                InferenceHeartbeat::default(),
            )),
            ..InferenceStreamMessage::default()
        }),
    };
    let final_update = WatchInferenceResponse {
        message: Some(InferenceStreamMessage {
            request_name: request_name.to_owned(),
            sequence: 2,
            resume_token: "cursor-2".to_owned(),
            update: Some(inference_stream_message::Update::FinalResult(
                InferenceFinalUpdate::default(),
            )),
            ..InferenceStreamMessage::default()
        }),
    };
    let transport = Arc::new(FakeTransport::default());
    transport
        .inference_watches
        .lock()
        .unwrap()
        .push_back(Ok(vec![
            Ok(progress),
            Err(Status::unavailable("transient disconnect")),
        ]));
    transport
        .inference_watches
        .lock()
        .unwrap()
        .push_back(Ok(vec![Ok(heartbeat), Ok(final_update)]));
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let client = Client::with_transport(
        test_config(provider, 3, Duration::from_millis(1)),
        transport.clone(),
    );
    let mut watch = client
        .inference()
        .watch(
            "operations/inference-2",
            None,
            &InferenceWaitOptions::new(),
            CancellationToken::new(),
        )
        .unwrap();
    assert_eq!(watch.next().await.unwrap().unwrap().sequence, 1);
    assert!(matches!(
        watch.next().await.unwrap().unwrap().update,
        Some(inference_stream_message::Update::Heartbeat(_))
    ));
    assert_eq!(watch.next().await.unwrap().unwrap().sequence, 2);
    assert!(watch.next().await.unwrap().is_none());
    assert_eq!(watch.cursor().unwrap().after_sequence, 2);
    let cursors = transport.inference_watch_cursors.lock().unwrap();
    assert!(cursors[0].is_none());
    assert_eq!(cursors[1].as_ref().unwrap().after_sequence, 1);
}

#[tokio::test]
async fn inference_wait_reads_immutable_terminal_result() {
    let result = InferenceResult {
        name: "inferenceResults/result-3".to_owned(),
        ..InferenceResult::default()
    };
    let operation = Operation {
        operation_id: "operations/inference-3".to_owned(),
        done: true,
        state: OperationState::Succeeded as i32,
        ..Operation::default()
    };
    let transport = Arc::new(FakeTransport::default());
    transport
        .inference_watches
        .lock()
        .unwrap()
        .push_back(Ok(vec![Ok(WatchInferenceResponse {
            message: Some(InferenceStreamMessage {
                request_name: "inferenceRequests/request-3".to_owned(),
                sequence: 1,
                resume_token: "cursor-terminal".to_owned(),
                update: Some(inference_stream_message::Update::FinalResult(
                    InferenceFinalUpdate::default(),
                )),
                ..InferenceStreamMessage::default()
            }),
        })]));
    transport
        .inference_results
        .lock()
        .unwrap()
        .push_back(Ok(GetInferenceResultResponse {
            result: Some(result.clone()),
            operation: Some(operation.clone()),
        }));
    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let client = Client::with_transport(
        test_config(provider, 3, Duration::from_millis(1)),
        transport,
    );
    let terminal = client
        .inference()
        .wait(
            "operations/inference-3",
            None,
            InferenceWaitOptions::new(),
            CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(terminal, (result, operation));
}

#[tokio::test]
async fn non_retryable_status_is_not_retried() {
    let provider = Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let provider_trait: Arc<dyn TokenProvider> = provider.clone();
    let config = test_config(provider_trait, 4, Duration::from_millis(1));
    let transport = Arc::new(FakeTransport::default());
    transport
        .operations
        .lock()
        .unwrap()
        .push_back(Err(Status::permission_denied("secret details")));
    let client = Client::with_transport(config, transport);
    let error = client
        .operations()
        .get("operations/op-5", CallOptions::new())
        .await
        .unwrap_err();
    assert_eq!(error.code(), Some(Code::PermissionDenied));
    assert!(!error.is_retryable());
    assert_eq!(provider.calls.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn credential_and_transport_futures_share_the_total_call_deadline() {
    let identity = Identity::new("tenant", "project", "principal").unwrap();
    let hanging_provider: Arc<dyn TokenProvider> = Arc::new(HangingTokenProvider);
    let config = Config::builder(Environment::Development, identity.clone(), hanging_provider)
        .build()
        .unwrap();
    let client = Client::with_transport(config, Arc::new(FakeTransport::default()));
    let short_call = CallOptions::new()
        .with_timeout(Duration::from_millis(1))
        .unwrap();
    let error = client
        .operations()
        .get("operations/token-timeout", short_call)
        .await
        .unwrap_err();
    assert_eq!(error.kind(), ErrorKind::DeadlineExceeded);

    let provider: Arc<dyn TokenProvider> =
        Arc::new(FakeTokenProvider::new(Duration::from_hours(1)));
    let config = Config::builder(Environment::Development, identity, provider)
        .build()
        .unwrap();
    let transport = Arc::new(FakeTransport::default());
    transport.hang_operations.store(true, Ordering::Relaxed);
    let client = Client::with_transport(config, transport);
    let short_call = CallOptions::new()
        .with_timeout(Duration::from_millis(1))
        .unwrap();
    let error = client
        .operations()
        .get("operations/transport-timeout", short_call)
        .await
        .unwrap_err();
    assert_eq!(error.kind(), ErrorKind::DeadlineExceeded);
}

#[tokio::test]
async fn bounded_pagination_preserves_opaque_tokens_and_fails_closed() {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let captured = Arc::clone(&seen);
    let mut paginator = paginate(
        move |token: String| {
            let captured = Arc::clone(&captured);
            async move {
                captured.lock().unwrap().push(token.clone());
                if token == " initial token " {
                    Ok(PaginationPage::new(vec![1, 2], " next token "))
                } else {
                    Ok(PaginationPage::new(vec![3], ""))
                }
            }
        },
        " initial token ",
        PaginationLimits::default(),
    );
    let mut values = Vec::new();
    while let Some(value) = paginator.try_next().await.unwrap() {
        values.push(value);
    }
    assert_eq!(values, vec![1, 2, 3]);
    assert_eq!(
        *seen.lock().unwrap(),
        vec![" initial token ".to_owned(), " next token ".to_owned()]
    );

    let mut repeated = paginate(
        |token: String| async move { Ok(PaginationPage::new(vec![1], token)) },
        "opaque",
        PaginationLimits::default(),
    );
    let error = repeated.try_next().await.unwrap_err();
    assert_eq!(error.kind(), ErrorKind::Protocol);
    assert!(repeated.try_next().await.unwrap().is_none());

    let mut bounded = paginate(
        |_token: String| async { Ok(PaginationPage::new(vec![1, 2, 3], "more")) },
        "",
        PaginationLimits::new(2, 2).unwrap(),
    );
    assert_eq!(bounded.try_next().await.unwrap(), Some(1));
    assert_eq!(bounded.try_next().await.unwrap(), Some(2));
    let error = bounded.try_next().await.unwrap_err();
    assert_eq!(error.kind(), ErrorKind::PaginationLimit);
    assert_eq!(error.code(), Some(Code::ResourceExhausted));
}

fn base64url(value: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut encoded = String::new();
    for chunk in value.chunks(3) {
        let first = chunk[0];
        let second = chunk.get(1).copied().unwrap_or(0);
        let third = chunk.get(2).copied().unwrap_or(0);
        encoded.push(char::from(TABLE[usize::from(first >> 2)]));
        encoded.push(char::from(
            TABLE[usize::from(((first & 0x03) << 4) | (second >> 4))],
        ));
        if chunk.len() > 1 {
            encoded.push(char::from(
                TABLE[usize::from(((second & 0x0f) << 2) | (third >> 6))],
            ));
        }
        if chunk.len() > 2 {
            encoded.push(char::from(TABLE[usize::from(third & 0x3f)]));
        }
    }
    encoded
}

// ---------------------------------------------------------------------------
// WS2.1 retry/timeout policy and WS2.2 error hierarchy.
// ---------------------------------------------------------------------------

fn tuned_config(
    provider: Arc<dyn TokenProvider>,
    attempts: u8,
    initial_backoff: Duration,
    max_backoff: Duration,
    jitter: Arc<dyn JitterSource>,
) -> Config {
    let identity = Identity::new("tenants/t-1", "projects/p-1", "principals/worker-1").unwrap();
    Config::builder(Environment::Development, identity, provider)
        .retry_policy(RetryPolicy::new(attempts, initial_backoff, max_backoff).unwrap())
        .jitter_source(jitter)
        .build()
        .unwrap()
}

fn test_provider() -> Arc<dyn TokenProvider> {
    Arc::new(FakeTokenProvider::new(Duration::from_hours(1)))
}

fn status_with(code: Code, trailers: &[(&'static str, &str)]) -> Status {
    let mut status = Status::new(code, "server text that must never escape the SDK");
    for (key, value) in trailers {
        status
            .metadata_mut()
            .insert(*key, MetadataValue::try_from(*value).unwrap());
    }
    status
}

/// Minimal `google.rpc.Status` encoder used only to build a realistic
/// `grpc-status-details-bin` fixture for the decoder under test.
#[derive(Clone, PartialEq, ::prost::Message)]
struct TestRpcStatus {
    #[prost(int32, tag = "1")]
    code: i32,
    #[prost(string, tag = "2")]
    message: String,
    #[prost(message, repeated, tag = "3")]
    details: Vec<prost_types::Any>,
}

fn error_detail_fixture() -> mindclade_protocols::common::v1::ErrorDetail {
    use mindclade_protocols::common::v1::{
        ErrorCode, ErrorDetail, FieldViolation, PreconditionViolation, RetryClass,
    };
    ErrorDetail {
        code: ErrorCode::ResourceExhausted as i32,
        message: "SQLSTATE 53400 pq: configuration limit exceeded\nstack trace".to_owned(),
        retry_class: RetryClass::Never as i32,
        subject: Some(ResourceRef {
            resource_type: "operation".to_owned(),
            resource_id: "op-9".to_owned(),
            name: "operations/op-9".to_owned(),
            etag: "revision-42".to_owned(),
            resource_version: 42,
            ..ResourceRef::default()
        }),
        field_violations: vec![
            FieldViolation {
                field: "page_size".to_owned(),
                description: "must be positive".to_owned(),
            },
            FieldViolation {
                field: "parent".to_owned(),
                // A multi-line provider dump is dropped, never truncated.
                description: "line one\nline two".to_owned(),
            },
        ],
        precondition_violations: vec![
            PreconditionViolation {
                r#type: QUOTA_PRECONDITION_TYPE.to_owned(),
                subject: "projects/p-1/concurrentRuns".to_owned(),
                description: "durable ceiling reached".to_owned(),
            },
            PreconditionViolation {
                r#type: FENCE_PRECONDITION_TYPE.to_owned(),
                subject: "attempts/a-1".to_owned(),
                description: "lease epoch is stale".to_owned(),
            },
            PreconditionViolation {
                r#type: REVISION_PRECONDITION_TYPE.to_owned(),
                subject: "operations/op-9".to_owned(),
                description: "resource version moved".to_owned(),
            },
        ],
        retry_after: Some(prost_types::Duration {
            seconds: 1,
            nanos: 500_000_000,
        }),
        error_id: "diagnostics/abc-123".to_owned(),
    }
}

#[tokio::test]
async fn full_jitter_draws_uniformly_within_the_capped_exponential_window() {
    let transport = Arc::new(FakeTransport::default());
    transport.operations.lock().unwrap().extend([
        Err(status_with(Code::Unavailable, &[])),
        Err(status_with(Code::Unavailable, &[])),
        Err(status_with(Code::Unavailable, &[])),
        Ok(GetOperationResponse {
            operation: Some(operation("operations/jitter", true)),
        }),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let config = tuned_config(
        test_provider(),
        4,
        Duration::from_millis(1),
        Duration::from_millis(8),
        Arc::new(ScriptedJitter::scripted(vec![0.0, 0.5, 1.0])),
    );
    let client = Client::with_test_sleeper(config, transport, sleeper.clone());
    client
        .operations()
        .get("operations/jitter", CallOptions::new())
        .await
        .unwrap();

    // Windows are min(cap, base * 2^n) = 1ms, 2ms, 4ms; the scripted
    // fractions select the bottom, middle, and top of each window.
    assert_eq!(
        sleeper.delays.lock().unwrap().as_slice(),
        [
            Duration::ZERO,
            Duration::from_millis(1),
            Duration::from_millis(4),
        ]
    );
}

#[test]
fn system_jitter_stays_inside_the_window_and_varies_between_draws() {
    let jitter = SystemJitter::new();
    assert_eq!(jitter.jitter_micros(0), 0);
    let draws: Vec<u64> = (0..64).map(|_| jitter.jitter_micros(4_000)).collect();
    assert!(draws.iter().all(|value| *value <= 4_000));
    assert!(draws.windows(2).any(|pair| pair[0] != pair[1]));
    assert!(jitter.jitter_micros(u64::MAX) <= u64::MAX);
}

#[tokio::test]
async fn retry_after_ms_trailer_overrides_backoff_and_is_clamped_to_max_backoff() {
    let transport = Arc::new(FakeTransport::default());
    transport.operations.lock().unwrap().extend([
        Err(status_with(
            Code::Unavailable,
            &[("retry-after-ms", "60000")],
        )),
        Ok(GetOperationResponse {
            operation: Some(operation("operations/clamped", true)),
        }),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let config = tuned_config(
        test_provider(),
        4,
        Duration::from_millis(1),
        Duration::from_millis(8),
        Arc::new(ScriptedJitter::max()),
    );
    let client = Client::with_test_sleeper(config, transport, sleeper.clone());
    client
        .operations()
        .get("operations/clamped", CallOptions::new())
        .await
        .unwrap();
    assert_eq!(
        sleeper.delays.lock().unwrap().as_slice(),
        [Duration::from_millis(8)]
    );
}

#[tokio::test]
async fn should_retry_trailer_forces_retry_of_a_terminal_status() {
    let transport = Arc::new(FakeTransport::default());
    transport.operations.lock().unwrap().extend([
        Err(status_with(
            Code::InvalidArgument,
            &[("x-mindclade-should-retry", "true")],
        )),
        Ok(GetOperationResponse {
            operation: Some(operation("operations/forced", true)),
        }),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(
        test_config(test_provider(), 4, Duration::from_millis(1)),
        transport.clone(),
        sleeper,
    );
    client
        .operations()
        .get("operations/forced", CallOptions::new())
        .await
        .unwrap();
    assert_eq!(transport.observed.lock().unwrap().len(), 2);
}

#[tokio::test]
async fn should_retry_trailer_suppresses_retry_of_a_retryable_status() {
    let transport = Arc::new(FakeTransport::default());
    transport
        .operations
        .lock()
        .unwrap()
        .push_back(Err(status_with(
            Code::Unavailable,
            &[("x-mindclade-should-retry", "false")],
        )));
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(
        test_config(test_provider(), 4, Duration::from_millis(1)),
        transport.clone(),
        sleeper.clone(),
    );
    let error = client
        .operations()
        .get("operations/opted-out", CallOptions::new())
        .await
        .unwrap_err();
    assert!(!error.is_retryable());
    assert_eq!(error.server_retry_override(), Some(false));
    assert_eq!(
        error.retry_attempts().final_cause(),
        FinalCause::ServerRetryOptOut
    );
    assert_eq!(error.retry_attempts().attempts(), 1);
    assert_eq!(transport.observed.lock().unwrap().len(), 1);
    assert!(sleeper.delays.lock().unwrap().is_empty());
}

#[tokio::test]
async fn retry_count_and_timeout_ms_are_sent_on_every_attempt() {
    let transport = Arc::new(FakeTransport::default());
    transport.operations.lock().unwrap().extend([
        Err(status_with(Code::Unavailable, &[])),
        Ok(GetOperationResponse {
            operation: Some(operation("operations/counted", true)),
        }),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(
        test_config(test_provider(), 4, Duration::from_millis(1)),
        transport.clone(),
        sleeper,
    );
    let call = CallOptions::new()
        .with_timeout(Duration::from_secs(5))
        .unwrap();
    client
        .operations()
        .get("operations/counted", call)
        .await
        .unwrap();

    let observed = transport.observed.lock().unwrap();
    let counts: Vec<Option<&str>> = observed
        .iter()
        .map(|value| value.retry_count.as_deref())
        .collect();
    assert_eq!(counts, [Some("0"), Some("1")]);
    let budgets: Vec<u64> = observed
        .iter()
        .map(|value| value.timeout_ms.as_deref().unwrap().parse::<u64>().unwrap())
        .collect();
    assert_eq!(budgets.len(), 2);
    assert!(budgets[0] <= 5_000);
    // The timeout is a total budget, so a later attempt never sees more of it.
    assert!(budgets[1] <= budgets[0]);
}

#[tokio::test]
async fn per_request_max_attempts_overrides_the_configured_policy() {
    let transport = Arc::new(FakeTransport::default());
    transport.operations.lock().unwrap().extend([
        Err(status_with(Code::Unavailable, &[])),
        Err(status_with(Code::Unavailable, &[])),
        Err(status_with(Code::Unavailable, &[])),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(
        test_config(test_provider(), 4, Duration::from_millis(1)),
        transport.clone(),
        sleeper,
    );
    let call = CallOptions::new().with_max_attempts(2).unwrap();
    let error = client
        .operations()
        .get("operations/bounded", call)
        .await
        .unwrap_err();
    assert_eq!(error.retry_attempts().attempts(), 2);
    assert_eq!(
        error.retry_attempts().final_cause(),
        FinalCause::AttemptsExhausted
    );
    assert_eq!(transport.observed.lock().unwrap().len(), 2);
    assert!(CallOptions::new().with_max_attempts(0).is_err());
    assert!(CallOptions::new().with_max_attempts(9).is_err());
}

#[tokio::test]
async fn named_unsafe_override_is_required_to_retry_a_non_idempotent_rpc() {
    let config = test_config(test_provider(), 4, Duration::from_millis(1));
    let client = Client::with_transport(config.clone(), Arc::new(FakeTransport::default()));
    let core = &client.core;

    let plain = CallOptions::new().prepare(&config);
    assert_eq!(
        core.attempt_budget(&plain, CallSafety::Unsafe).unwrap(),
        1,
        "an unregistered mutation must never be retried implicitly"
    );

    let acknowledged = CallOptions::new()
        .with_unsafe_retry_of_non_idempotent_rpc(3)
        .unwrap()
        .prepare(&config);
    assert_eq!(
        core.attempt_budget(&acknowledged, CallSafety::Unsafe)
            .unwrap(),
        3
    );

    // The named override is not a general attempt knob: it is refused on an
    // RPC the SDK already classifies as retryable.
    assert!(
        core.attempt_budget(&acknowledged, CallSafety::Safe)
            .is_err()
    );
    assert!(
        core.attempt_budget(&acknowledged, CallSafety::Idempotent)
            .is_err()
    );

    // Nothing the caller can name makes a never-retry route retryable.
    assert_eq!(
        core.attempt_budget(&plain, CallSafety::NeverRetry).unwrap(),
        1
    );
    assert!(
        core.attempt_budget(&acknowledged, CallSafety::NeverRetry)
            .is_err()
    );
    let widened = CallOptions::new().with_max_attempts(4).unwrap().prepare(&config);
    assert!(
        core.attempt_budget(&widened, CallSafety::NeverRetry)
            .is_err()
    );
}

#[test]
fn expire_attempt_leases_is_never_retryable() {
    const ROUTE: &str = "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases";
    assert!(never_retry_method(ROUTE));
    assert_eq!(registered_method_safety(ROUTE), CallSafety::NeverRetry);
    assert!(!never_retry_method(
        "/mindclade.internal.job.v1.RunService/RenewAttemptLease"
    ));
}

#[tokio::test]
async fn total_timeout_budget_spans_credential_acquisition_and_every_retry() {
    // A backoff that cannot fit inside the remaining budget ends the call
    // rather than overrunning the caller's total deadline.
    let transport = Arc::new(FakeTransport::default());
    transport.operations.lock().unwrap().extend([
        Err(status_with(Code::Unavailable, &[])),
        Err(status_with(Code::Unavailable, &[])),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let config = tuned_config(
        test_provider(),
        4,
        Duration::from_millis(8),
        Duration::from_millis(8),
        Arc::new(ScriptedJitter::max()),
    );
    let client = Client::with_test_sleeper(config, transport.clone(), sleeper.clone());
    let call = CallOptions::new()
        .with_timeout(Duration::from_millis(5))
        .unwrap();
    let error = client
        .operations()
        .get("operations/budget", call)
        .await
        .unwrap_err();
    assert_eq!(error.kind(), ErrorKind::DeadlineExceeded);
    assert_eq!(
        error.retry_attempts().final_cause(),
        FinalCause::DeadlineExceeded
    );
    assert_eq!(error.retry_attempts().attempts(), 1);
    assert!(sleeper.delays.lock().unwrap().is_empty());
    assert_eq!(transport.observed.lock().unwrap().len(), 1);

    // Credential acquisition is inside the same budget, so it is charged to
    // the call rather than added on top of it.
    let identity = Identity::new("tenant", "project", "principal").unwrap();
    let hanging: Arc<dyn TokenProvider> = Arc::new(HangingTokenProvider);
    let config = Config::builder(Environment::Development, identity, hanging)
        .build()
        .unwrap();
    let client = Client::with_transport(config, Arc::new(FakeTransport::default()));
    let error = client
        .operations()
        .get(
            "operations/credential-budget",
            CallOptions::new()
                .with_timeout(Duration::from_millis(1))
                .unwrap(),
        )
        .await
        .unwrap_err();
    assert_eq!(error.kind(), ErrorKind::DeadlineExceeded);
    assert_eq!(
        error.retry_attempts().final_cause(),
        FinalCause::DeadlineExceeded
    );
    assert_eq!(error.retry_attempts().attempts(), 0);
}

#[tokio::test]
async fn errors_report_attempt_count_cumulative_delay_and_final_cause() {
    let transport = Arc::new(FakeTransport::default());
    for _ in 0..4 {
        transport
            .operations
            .lock()
            .unwrap()
            .push_back(Err(status_with(Code::Unavailable, &[])));
    }
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(
        test_config(test_provider(), 4, Duration::from_millis(1)),
        transport,
        sleeper.clone(),
    );
    let error = client
        .operations()
        .get("operations/exhausted", CallOptions::new())
        .await
        .unwrap_err();
    let summary = error.retry_attempts();
    assert_eq!(summary.attempts(), 4);
    assert_eq!(summary.cumulative_delay(), Duration::from_millis(7));
    assert_eq!(summary.final_cause(), FinalCause::AttemptsExhausted);
    assert_eq!(
        sleeper.delays.lock().unwrap().as_slice(),
        [
            Duration::from_millis(1),
            Duration::from_millis(2),
            Duration::from_millis(4),
        ]
    );

    let terminal = Error::from_status(&status_with(Code::NotFound, &[]));
    assert_eq!(terminal.retry_attempts(), Default::default());
    assert_eq!(
        terminal.retry_attempts().final_cause(),
        FinalCause::NotRetried
    );
}

#[test]
fn error_kind_maps_every_documented_status_class() {
    for (code, kind, stable, retryable) in [
        (Code::Ok, ErrorKind::Remote, "mindclade.remote_failure", false),
        (
            Code::Cancelled,
            ErrorKind::Cancelled,
            "mindclade.cancelled",
            false,
        ),
        (
            Code::Unknown,
            ErrorKind::Remote,
            "mindclade.remote_failure",
            false,
        ),
        (
            Code::InvalidArgument,
            ErrorKind::Validation,
            "mindclade.validation_failed",
            false,
        ),
        (
            Code::DeadlineExceeded,
            ErrorKind::DeadlineExceeded,
            "mindclade.deadline_exceeded",
            true,
        ),
        (
            Code::NotFound,
            ErrorKind::NotFound,
            "mindclade.not_found",
            false,
        ),
        (
            Code::AlreadyExists,
            ErrorKind::AlreadyExists,
            "mindclade.already_exists",
            false,
        ),
        (
            Code::PermissionDenied,
            ErrorKind::Authorization,
            "mindclade.authorization_denied",
            false,
        ),
        (
            Code::ResourceExhausted,
            ErrorKind::RateLimit,
            "mindclade.rate_limited",
            true,
        ),
        (
            Code::FailedPrecondition,
            ErrorKind::Conflict,
            "mindclade.conflict",
            false,
        ),
        (Code::Aborted, ErrorKind::Conflict, "mindclade.conflict", true),
        (
            Code::OutOfRange,
            ErrorKind::Validation,
            "mindclade.validation_failed",
            false,
        ),
        (
            Code::Unimplemented,
            ErrorKind::Remote,
            "mindclade.remote_failure",
            false,
        ),
        (
            Code::Internal,
            ErrorKind::Remote,
            "mindclade.remote_failure",
            false,
        ),
        (
            Code::Unavailable,
            ErrorKind::RetryableService,
            "mindclade.service_unavailable",
            true,
        ),
        (
            Code::DataLoss,
            ErrorKind::Remote,
            "mindclade.remote_failure",
            false,
        ),
        (
            Code::Unauthenticated,
            ErrorKind::Authentication,
            "mindclade.authentication_failed",
            false,
        ),
    ] {
        let error = Error::from_status(&status_with(code, &[]));
        assert_eq!(error.kind(), kind, "kind for {code:?}");
        assert_eq!(error.stable_code(), stable, "stable code for {code:?}");
        assert_eq!(error.is_retryable(), retryable, "retryability for {code:?}");
        assert_eq!(retryable_status_code(code), retryable, "predicate {code:?}");
        assert!(
            !error.to_string().contains("server text"),
            "server text leaked for {code:?}"
        );
    }
}

#[test]
fn locally_raised_errors_keep_their_stable_classification() {
    assert_eq!(
        Error::invalid_argument("bad").stable_code(),
        "mindclade.validation_failed"
    );
    assert_eq!(
        Error::configuration("bad").stable_code(),
        "mindclade.configuration_invalid"
    );
    assert_eq!(
        Error::pagination_limit("bounded").kind(),
        ErrorKind::PaginationLimit
    );
    assert_eq!(
        Error::protocol("bad").stable_code(),
        "mindclade.protocol_violation"
    );
    assert_eq!(Error::transport().kind(), ErrorKind::Transport);
    assert_eq!(Error::cancelled().stable_code(), "mindclade.cancelled");
}

#[test]
fn structured_error_detail_populates_typed_fields_without_server_text() {
    use prost::Message as _;

    let detail = error_detail_fixture();
    let envelope = TestRpcStatus {
        code: Code::ResourceExhausted as i32,
        message: "SQLSTATE 53400 pq: configuration limit exceeded".to_owned(),
        details: vec![prost_types::Any {
            type_url: "type.googleapis.com/mindclade.common.v1.ErrorDetail".to_owned(),
            value: detail.encode_to_vec(),
        }],
    };
    for bytes in [envelope.encode_to_vec(), detail.encode_to_vec()] {
        let status = Status::with_details(
            Code::ResourceExhausted,
            "server text that must never escape the SDK",
            tonic::codegen::Bytes::from(bytes),
        );
        let error = Error::from_status(&status);

        // RETRY_CLASS_NEVER narrows an otherwise retryable status, and the
        // exhaustion is durable rather than a rate limit.
        assert_eq!(error.kind(), ErrorKind::Quota);
        assert_eq!(error.stable_code(), "mindclade.quota_exhausted");
        assert!(!error.is_retryable());
        assert_eq!(error.retry_after(), Some(Duration::from_millis(1_500)));
        assert_eq!(error.operation_id(), Some("operations/op-9"));
        assert_eq!(error.conflict_revision(), Some("revision-42"));
        assert_eq!(error.diagnostic_reference(), Some("diagnostics/abc-123"));

        assert_eq!(error.field_violations().len(), 2);
        assert_eq!(error.field_violations()[0].field, "page_size");
        assert_eq!(error.field_violations()[0].description, "must be positive");
        // A multi-line provider dump is dropped rather than truncated.
        assert_eq!(error.field_violations()[1].description, "");

        assert_eq!(error.precondition_violations().len(), 3);
        assert_eq!(
            error.quota_state().map(QuotaState::subject),
            Some("projects/p-1/concurrentRuns")
        );
        assert_eq!(
            error.quota_state().map(QuotaState::description),
            Some("durable ceiling reached")
        );
        assert_eq!(
            error.fence_state().map(FenceState::subject),
            Some("attempts/a-1")
        );
        assert_eq!(
            error.fence_state().map(FenceState::description),
            Some("lease epoch is stale")
        );

        // The server's own message is never copied into the error surface.
        let rendered = format!("{error} {error:?}");
        assert!(!rendered.contains("SQLSTATE"));
        assert!(!rendered.contains("stack trace"));
        assert!(!rendered.contains("server text"));
    }
}

#[test]
fn unrecognized_or_absent_structured_detail_never_widens_the_failure() {
    use mindclade_protocols::common::v1::ErrorDetail;
    use prost::Message as _;

    // An unspecified code carries no typed fields and no retryability.
    let unspecified = ErrorDetail {
        code: 0,
        precondition_violations: vec![mindclade_protocols::common::v1::PreconditionViolation {
            r#type: QUOTA_PRECONDITION_TYPE.to_owned(),
            subject: "ignored".to_owned(),
            description: "ignored".to_owned(),
        }],
        ..ErrorDetail::default()
    };
    let status = Status::with_details(
        Code::PermissionDenied,
        "denied",
        tonic::codegen::Bytes::from(unspecified.encode_to_vec()),
    );
    let error = Error::from_status(&status);
    assert_eq!(error.kind(), ErrorKind::Authorization);
    assert!(error.precondition_violations().is_empty());
    assert!(error.quota_state().is_none());
    assert!(!error.is_retryable());

    // An unknown enum value is equally inert.
    let unknown = ErrorDetail {
        code: 9_999,
        ..ErrorDetail::default()
    };
    let status = Status::with_details(
        Code::Aborted,
        "aborted",
        tonic::codegen::Bytes::from(unknown.encode_to_vec()),
    );
    let error = Error::from_status(&status);
    assert_eq!(error.kind(), ErrorKind::Conflict);
    assert!(error.diagnostic_reference().is_none());
    assert!(error.is_retryable());

    // Opaque bytes that are not a detail message are ignored, not guessed at.
    let status = Status::with_details(
        Code::Internal,
        "internal",
        tonic::codegen::Bytes::from_static(b"\xff\xff not protobuf"),
    );
    let error = Error::from_status(&status);
    assert_eq!(error.kind(), ErrorKind::Remote);
    assert!(error.field_violations().is_empty());
}

#[tokio::test]
async fn operation_failure_projects_structured_detail_onto_the_error_hierarchy() {
    let transport = Arc::new(FakeTransport::default());
    transport
        .operations
        .lock()
        .unwrap()
        .push_back(Ok(GetOperationResponse {
            operation: Some(Operation {
                operation_id: "operations/op-9".to_owned(),
                state: OperationState::Failed as i32,
                done: true,
                error: Some(error_detail_fixture()),
                ..Operation::default()
            }),
        }));
    let client = Client::with_transport(
        test_config(test_provider(), 1, Duration::from_millis(1)),
        transport,
    );
    let wait_error = client
        .operations()
        .wait(
            "operations/op-9",
            WaitOptions::new(),
            CancellationToken::new(),
        )
        .await
        .unwrap_err();
    let failure = wait_error.operation_failure().unwrap();
    let error = failure.as_error();
    assert_eq!(error.kind(), ErrorKind::OperationFailed);
    assert_eq!(error.stable_code(), "mindclade.operation_failed");
    assert!(!error.is_retryable());
    assert_eq!(error.operation_id(), Some("operations/op-9"));
    assert_eq!(error.diagnostic_reference(), Some("diagnostics/abc-123"));
    assert_eq!(
        error.quota_state().map(QuotaState::subject),
        Some("projects/p-1/concurrentRuns")
    );
    let rendered = format!("{error} {error:?}");
    assert!(!rendered.contains("SQLSTATE"));
}

#[tokio::test]
async fn the_unary_loop_and_the_watchers_share_one_retryability_predicate() {
    // `Aborted` is retryable by status, but a server opt-out trailer must end
    // both the unary loop and a resumable watch at a single attempt.
    let transport = Arc::new(FakeTransport::default());
    transport
        .operations
        .lock()
        .unwrap()
        .push_back(Err(status_with(
            Code::Aborted,
            &[("x-mindclade-should-retry", "false")],
        )));
    transport
        .watches
        .lock()
        .unwrap()
        .push_back(Ok(vec![Err(status_with(
            Code::Aborted,
            &[("x-mindclade-should-retry", "false")],
        ))]));
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(
        test_config(test_provider(), 4, Duration::from_millis(1)),
        transport.clone(),
        sleeper.clone(),
    );

    let error = client
        .operations()
        .get("operations/shared", CallOptions::new())
        .await
        .unwrap_err();
    assert!(!error.is_retryable());
    assert_eq!(error.retry_attempts().attempts(), 1);

    let mut watch = client
        .operations()
        .watch(
            "operations/shared",
            0,
            &CallOptions::new(),
            CancellationToken::new(),
        )
        .unwrap();
    let error = watch.next().await.unwrap_err();
    assert!(!error.is_retryable());
    assert_eq!(transport.watch_after_sequences.lock().unwrap().len(), 1);
    assert!(sleeper.delays.lock().unwrap().is_empty());
}

#[tokio::test]
async fn watch_reconnect_backoff_honours_the_clamped_retry_after_trailer() {
    let transport = Arc::new(FakeTransport::default());
    transport.watches.lock().unwrap().extend([
        Ok(vec![Err(status_with(
            Code::Unavailable,
            &[("retry-after-ms", "60000")],
        ))]),
        Ok(vec![Ok(WatchOperationResponse {
            operation: Some(operation("operations/clamped-watch", true)),
            sequence: 1,
            observed_at: None,
        })]),
    ]);
    let sleeper = Arc::new(ImmediateSleeper::default());
    let client = Client::with_test_sleeper(
        test_config(test_provider(), 4, Duration::from_millis(1)),
        transport,
        sleeper.clone(),
    );
    let mut watch = client
        .operations()
        .watch(
            "operations/clamped-watch",
            0,
            &CallOptions::new(),
            CancellationToken::new(),
        )
        .unwrap();
    let update = watch.next().await.unwrap().unwrap();
    assert_eq!(update.sequence, 1);
    assert_eq!(
        sleeper.delays.lock().unwrap().as_slice(),
        [Duration::from_millis(8)]
    );
}
