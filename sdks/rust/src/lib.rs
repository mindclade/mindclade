//! Private Mindclade Rust SDK over authoritative generated gRPC bindings.
//!
//! Generated messages remain the contract. Types defined here describe only
//! client behavior such as credentials, retry policy, request metadata, and
//! cancellation.

#![forbid(unsafe_code)]

mod admin;
mod agents;
mod approvals;
mod artifacts;
mod auth;
mod config;
mod cross_field_generated;
mod datasets;
mod error;
mod evaluations;
mod events;
mod experiments;
mod inference;
mod jobs;
mod models;
mod operations;
mod policies;
mod request;
mod retry;
mod runs;
pub mod testing;
mod training;
mod transport;
mod workflows;

#[cfg(test)]
mod agent_tests;
#[cfg(test)]
mod artifact_operation_gap_tests;
#[cfg(test)]
mod evaluation_tests;
#[cfg(test)]
mod experiment_tests;
#[cfg(test)]
mod job_run_tests;
#[cfg(test)]
mod policy_admin_tests;
#[cfg(test)]
mod training_tests;
#[cfg(test)]
mod workflow_tests;

pub use cross_field_generated::{
    CROSS_FIELD_RULES, CrossFieldError, CrossFieldRule, check as check_cross_field,
    rules_for as cross_field_rules_for,
};

pub use admin::Admin;
pub use agents::Agents;
pub use approvals::Approvals;
pub use artifacts::{ArtifactUploadOptions, Artifacts};
pub use auth::{AccessToken, GcpWorkloadIdentityProvider, TokenProvider};
pub use config::{
    Config, ConfigBuilder, Environment, Identity, RECOGNISED_ENVIRONMENT_VARIABLES, RetryPolicy,
    SDK_NAME, SDK_VERSION,
};
pub use datasets::Datasets;
pub use error::{
    Error, ErrorKind, FenceState, FinalCause, QuotaState, RetryAttemptSummary,
    retryable_status_code,
};
pub use evaluations::Evaluations;
pub use events::{EventRejectedError, JobRequestedDelivery, decode_job_requested_delivery};
pub use experiments::Experiments;
pub use inference::{Inference, InferenceWaitOptions, InferenceWatch};
pub use jobs::Jobs;
pub use models::Models;
pub use operations::{
    CancellationToken, OperationFailure, OperationWaitError, OperationWatch, Operations,
    WaitOptions, WatchNext, WatchOptions, WatchStream,
};
pub use policies::Policies;
pub use request::{
    CallOptions, DEFAULT_PAGE_SIZE, HARD_PAGE_SIZE_CEILING, InterceptContext, Interceptor,
    InterceptorMetadata, MAX_CUSTOM_METADATA_ENTRIES, Page, Pages, PaginationLimits,
    PaginationPage, Paginator, Response, SAFE_RESPONSE_METADATA, SafeMetadata, SubmitOptions,
    is_credential_bearing, paginate, validate_custom_metadata, validate_custom_metadata_key,
};
pub use retry::{
    AttemptEvent, CallEvent, JitterSource, LogLevel, LoggingObserver, Observer, RetryEvent,
    SystemJitter,
};
pub use runs::{AttemptLease, LeaseCredential, Runs};
pub use training::{
    Training, TrainingRunFailure, TrainingWaitError, TrainingWatch, TrainingWatchOptions,
};
pub use transport::{
    ArtifactStream, GeneratedClients, InferenceStream, OperationStream, RawDispatch, RawRequest,
    RecordedRpcCall, RecordingTransport, RpcTransport, TonicTransport, TrainingStream,
    WorkflowStream,
};
pub use workflows::{
    WorkflowRunFailure, WorkflowWaitError, WorkflowWatch, WorkflowWatchOptions, Workflows,
};

// Re-export authoritative contract types used by the ergonomic surface. These
// are aliases to generated types, never handwritten wire models.
pub use mindclade_protocols::admin::v1::{
    AuditExport, AuditQuery, AuditQueryPage, Project, Tenant,
};
pub use mindclade_protocols::agent::v1::{AgentDefinition, AgentRun, AgentStep, ToolReceipt};
pub use mindclade_protocols::artifact::v1::ArtifactRef;
pub use mindclade_protocols::common::v1::{
    ErrorCode, ErrorDetail, FieldViolation, PreconditionViolation, RetryClass,
};
pub use mindclade_protocols::dataset::v1::{
    CreateDatasetCommand, Dataset, DatasetRelease, PublishDatasetReleaseCommand,
    RevokeDatasetReleaseCommand, UpdateDatasetCommand,
};
pub use mindclade_protocols::evaluation::v1::{EvaluationResult, EvaluationRun, PromotionDecision};
pub use mindclade_protocols::experiment::v1::{
    CompleteTrialCommand, CreateExperimentCommand, CreateStudyCommand, CreateTrialCommand,
    Experiment, Study, TransitionExperimentCommand, TransitionStudyCommand, TransitionTrialCommand,
    Trial, UpdateExperimentCommand,
};
pub use mindclade_protocols::inference::v1::{
    InferenceRequest, InferenceResult, InferenceStreamCursor, InferenceStreamMessage,
};
pub use mindclade_protocols::internal::artifact::v1::{
    AcquireArtifactLeaseRequest, ArtifactStagingReceipt, ArtifactUploadSession,
    ArtifactUploadState, GetArtifactRequest, ListArtifactsRequest, ListArtifactsResponse,
    QuarantineArtifactRequest, ReleaseArtifactLeaseRequest,
};
pub use mindclade_protocols::internal::inference::v1::CommitInferenceResultRequest;
pub use mindclade_protocols::internal::job::v1::{
    AcquireAttemptLeaseRequest, CancelAttemptRequest, CancelAttemptResponse, CancelJobRequest,
    CommitAttemptRequest, CommitAttemptResponse, GetAttemptRequest, GetJobRequest, GetRunRequest,
    HeartbeatAttemptRequest, HeartbeatAttemptResponse, ListAttemptsRequest, ListAttemptsResponse,
    ListJobsRequest, ListJobsResponse, ListOperationsRequest, ListOperationsResponse,
    ListRunsRequest, ListRunsResponse, RenewAttemptLeaseRequest,
};
pub use mindclade_protocols::internal::training::v1::{
    ListCheckpointsRequest, ListCheckpointsResponse, ListTrainingRunsRequest,
    ListTrainingRunsResponse, WatchTrainingRunResponse,
};
pub use mindclade_protocols::job::v1::{
    Attempt, AttemptState, Job, JobState, LeaseFence, RequestJobCommand, Run, RunState,
};
pub use mindclade_protocols::model::v1::{
    Model, ModelRelease, PromoteModelReleaseCommand, RegisterModelCommand,
    RegisterModelReleaseCommand, RevokeModelReleaseCommand,
};
pub use mindclade_protocols::operation::v1::{Operation, OperationState};
pub use mindclade_protocols::policy::v1::{AuthorizationDecision, PolicyReference, UsePolicy};
pub use mindclade_protocols::training::v1::{
    CancelTrainingRunCommand, Checkpoint, CommitCheckpointCommand, CommitTrainingProgressCommand,
    CompleteTrainingRunCommand, CreateTrainingRunCommand, PrepareCheckpointCommand,
    ResumeTrainingAttemptCommand, StartTrainingAttemptCommand, TrainingProgress, TrainingRun,
    TrainingRunState, TrainingTerminalClassification,
};
pub use mindclade_protocols::workflow::v1::{
    ApprovalBinding, ApprovalDecisionValue, ApprovalReceipt, ApprovalRequest, WorkflowDefinition,
    WorkflowRun, WorkflowRunState,
};

use std::sync::Arc;

use retry::{Sleeper, TokioSleeper, registered_method_policy};

/// The internal SDK client. Cloning it is cheap and shares the channel,
/// credential provider, and immutable runtime policy.
#[derive(Clone)]
pub struct Client {
    core: Arc<ClientCore>,
}

struct ClientCore {
    config: Config,
    transport: Arc<dyn RpcTransport>,
    sleeper: Arc<dyn Sleeper>,
    generated_channel: Option<tonic::transport::Channel>,
}

impl Client {
    /// Connects generated Tonic clients using the validated secure transport
    /// policy in `config`.
    ///
    /// # Errors
    ///
    /// Returns an error if secure channel setup or connection fails.
    pub async fn connect(config: Config) -> Result<Self, Error> {
        let transport = Arc::new(TonicTransport::connect(&config).await?);
        let generated_channel = Some(transport.channel());
        Ok(Self::from_parts(
            config,
            transport,
            Arc::new(TokioSleeper),
            generated_channel,
        ))
    }

    /// Constructs a client around an injectable transport. Production callers
    /// normally use [`Client::connect`]; this constructor supports hermetic
    /// service fakes without weakening configuration or credential checks.
    pub fn with_transport(config: Config, transport: Arc<dyn RpcTransport>) -> Self {
        Self::from_parts(config, transport, Arc::new(TokioSleeper), None)
    }

    /// Returns the immutable identity scope enforced by this client.
    #[must_use]
    pub fn identity(&self) -> &Identity {
        self.core.config.identity()
    }

    fn from_parts(
        config: Config,
        transport: Arc<dyn RpcTransport>,
        sleeper: Arc<dyn Sleeper>,
        generated_channel: Option<tonic::transport::Channel>,
    ) -> Self {
        Self {
            core: Arc::new(ClientCore {
                config,
                transport,
                sleeper,
                generated_channel,
            }),
        }
    }

    /// Training-run submission helpers backed by generated training RPCs.
    #[must_use]
    pub fn training(&self) -> Training {
        Training::new(Arc::clone(&self.core))
    }

    /// Durable long-running-operation helpers backed by generated job RPCs.
    #[must_use]
    pub fn operations(&self) -> Operations {
        Operations::new(Arc::clone(&self.core))
    }

    /// Durable admitted-work helpers backed by generated `JobService` RPCs.
    #[must_use]
    pub fn jobs(&self) -> Jobs {
        Jobs::new(Arc::clone(&self.core))
    }

    /// Logical-run and fenced-attempt helpers backed by generated `RunService` RPCs.
    #[must_use]
    pub fn runs(&self) -> Runs {
        Runs::new(Arc::clone(&self.core))
    }

    /// Artifact catalog helpers backed by generated artifact RPCs.
    #[must_use]
    pub fn artifacts(&self) -> Artifacts {
        Artifacts::new(Arc::clone(&self.core))
    }

    /// Dataset and immutable-release lifecycle helpers.
    #[must_use]
    pub fn datasets(&self) -> Datasets {
        Datasets::new(Arc::clone(&self.core))
    }

    /// Model registry, release, promotion, and revocation helpers.
    #[must_use]
    pub fn models(&self) -> Models {
        Models::new(Arc::clone(&self.core))
    }

    /// Bounded inference submission, fenced publication, and resumable watch
    /// helpers backed directly by generated internal RPCs.
    #[must_use]
    pub fn inference(&self) -> Inference {
        Inference::new(Arc::clone(&self.core))
    }

    /// Evaluation execution, fenced result publication, and promotion evidence helpers.
    #[must_use]
    pub fn evaluations(&self) -> Evaluations {
        Evaluations::new(Arc::clone(&self.core))
    }

    /// Bounded experiment, study, and immutable trial-result lifecycle helpers.
    #[must_use]
    pub fn experiments(&self) -> Experiments {
        Experiments::new(Arc::clone(&self.core))
    }

    /// Fail-closed authorization and use-policy lifecycle helpers.
    #[must_use]
    pub fn policies(&self) -> Policies {
        Policies::new(Arc::clone(&self.core))
    }

    /// Tenant, project, and payload-minimized audit administration helpers.
    #[must_use]
    pub fn admin(&self) -> Admin {
        Admin::new(Arc::clone(&self.core))
    }

    /// Bounded agent definition, run, step, and execution-receipt helpers.
    #[must_use]
    pub fn agents(&self) -> Agents {
        Agents::new(Arc::clone(&self.core))
    }

    /// Durable workflow definition/run helpers over generated internal RPCs.
    #[must_use]
    pub fn workflows(&self) -> Workflows {
        Workflows::new(Arc::clone(&self.core))
    }

    /// Exact-intent approval and immutable-receipt helpers.
    #[must_use]
    pub fn approvals(&self) -> Approvals {
        Approvals::new(Arc::clone(&self.core))
    }

    /// Returns every generated Tonic client for uncommon internal workflows.
    /// The returned clients use an interceptor that enforces the same
    /// short-lived workload identity, expected tenant/project/principal,
    /// bounded default deadline, request identity, and trace metadata as the
    /// ergonomic services. The explicit Local plaintext mode omits
    /// authorization. An authenticated client set must be reacquired after its
    /// cached credential enters the refresh window.
    ///
    /// Injected fake transports intentionally do not expose a live channel.
    ///
    /// # Errors
    ///
    /// Returns an error when the client was built with an injected transport.
    pub async fn generated_clients(&self) -> Result<GeneratedClients, Error> {
        let channel = self.core.generated_channel.clone().ok_or_else(|| {
            Error::configuration("generated clients require a live Tonic channel")
        })?;
        GeneratedClients::authorized(channel, &self.core.config).await
    }

    /// Applies workload identity, bounded deadline, tenant/project
    /// expectations, request ID, and trace metadata to a generated request.
    ///
    /// # Errors
    ///
    /// Returns an error for expired credentials, invalid metadata, or deadline
    /// exhaustion.
    pub async fn authorized_request<T>(
        &self,
        message: T,
        options: &CallOptions,
        idempotency_key: Option<&str>,
    ) -> Result<tonic::Request<T>, Error> {
        let prepared = options.prepare(&self.core.config);
        self.core
            .request(message, &prepared, idempotency_key, 0, "")
            .await
    }

    /// Sends a generated request through the same identity, deadline, retry,
    /// and sanitization policy as the ergonomic facades, returning the raw
    /// response alongside its correlation identity and allowlisted metadata.
    ///
    /// This is the escape hatch for the handful of internal RPCs that have no
    /// ergonomic facade. It does not weaken policy: the route's registered
    /// safety class still decides retry eligibility, an idempotent command
    /// still requires an idempotency key, and a never-retry route is still
    /// pinned to a single attempt.
    ///
    /// # Errors
    ///
    /// Returns an error for a missing idempotency key on an idempotent route,
    /// credential acquisition failure, deadline exhaustion, or a remote
    /// status.
    pub async fn send_with_metadata<T: RawRequest>(
        &self,
        message: T,
        options: &CallOptions,
        idempotency_key: Option<&str>,
    ) -> Result<Response<T::Response>, Error> {
        let prepared = options.prepare(&self.core.config);
        self.core
            .unary(
                message,
                &prepared,
                registered_method_policy(T::METHOD),
                idempotency_key,
                T::dispatch,
            )
            .await
    }

    #[cfg(test)]
    fn with_test_sleeper(
        config: Config,
        transport: Arc<dyn RpcTransport>,
        sleeper: Arc<dyn Sleeper>,
    ) -> Self {
        Self::from_parts(config, transport, sleeper, None)
    }
}

#[cfg(test)]
mod tests;
