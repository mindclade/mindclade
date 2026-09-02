use std::{
    collections::hash_map::RandomState,
    fmt,
    future::Future,
    hash::{BuildHasher, Hash, Hasher},
    io::Write,
    pin::Pin,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use sha2::{Digest, Sha256};
use tonic::{
    Code, Request, Response as TonicResponse, Status,
    codegen::async_trait,
    metadata::{AsciiMetadataKey, KeyRef, MetadataValue},
};

use crate::{
    ClientCore, Error, ErrorKind, RpcTransport,
    config::sdk_metadata_value,
    error::{FinalCause, RETRY_COUNT_METADATA, RetryAttemptSummary, TIMEOUT_MS_METADATA},
    request::{InterceptContext, InterceptorMetadata, PreparedCall, Response},
};

/// Bounded rejection-sampling attempts before an unbiased draw is abandoned in
/// favour of a negligibly biased one. The loop can therefore never hang.
const MAX_JITTER_DRAWS: u8 = 8;

/// Retry accounting carried alongside the attempt loop so every terminal
/// failure reports the same observable outcome.
#[derive(Clone, Copy, Debug, Default)]
struct RetryProgress {
    attempts: u32,
    cumulative_delay: Duration,
    cause: FinalCause,
}

impl RetryProgress {
    fn summary(self) -> RetryAttemptSummary {
        RetryAttemptSummary::new(self.attempts, self.cumulative_delay, self.cause)
    }
}

/// Why one attempt could not be issued or settled at all.
struct AttemptFailure {
    error: Error,
    cause: FinalCause,
    status: Option<Code>,
    /// Whether the attempt actually reached the transport. A failure during
    /// request assembly or credential acquisition never counts as an attempt.
    issued: bool,
}

/// The settled result of one attempt: either a transport outcome to classify,
/// or a failure that ends the call outright.
type AttemptOutcome<R> = Result<Result<TonicResponse<R>, Status>, AttemptFailure>;

pub(crate) type RpcFuture<R> =
    Pin<Box<dyn Future<Output = Result<TonicResponse<R>, Status>> + Send + 'static>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CallSafety {
    Safe,
    Idempotent,
    Unsafe,
    /// A raw-only reconciler command that must never be retried implicitly,
    /// and that no named override can make retryable.
    NeverRetry,
}

/// The registered route together with its retry-safety class.
///
/// Facades resolve this once from their own route constant and hand it to
/// [`ClientCore::unary`], so the retry loop, the interceptor seam, and the
/// observer seam all see the same method name without the route string
/// having to be threaded through every call site separately.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct CallPolicy {
    route: &'static str,
    safety: CallSafety,
}

impl CallPolicy {
    pub(crate) fn route(self) -> &'static str {
        self.route
    }

    pub(crate) fn safety(self) -> CallSafety {
        self.safety
    }
}

/// Routes that must never be retried, whatever the caller asks for.
///
/// `RunService.ExpireAttemptLeases` is a raw-only reconciler command using
/// server time; a second delivery would fence a different batch of attempts.
pub(crate) fn never_retry_method(method: &str) -> bool {
    method == "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases"
}

/// Central policy for ergonomic methods. Unknown methods fail closed to one
/// attempt; transport metadata can never make an unregistered mutation safe.
pub(crate) fn registered_method_policy(method: &'static str) -> CallPolicy {
    let safety = if never_retry_method(method) {
        CallSafety::NeverRetry
    } else if idempotent_method(method) {
        CallSafety::Idempotent
    } else if safe_method(method) {
        CallSafety::Safe
    } else {
        CallSafety::Unsafe
    };
    CallPolicy {
        route: method,
        safety,
    }
}

fn idempotent_method(method: &str) -> bool {
    matches!(
        method,
        "/mindclade.internal.artifact.v1.ArtifactService/AbortArtifactUpload"
            | "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease"
            | "/mindclade.internal.artifact.v1.ArtifactService/BeginArtifactUpload"
            | "/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact"
            | "/mindclade.internal.artifact.v1.ArtifactService/FinalizeArtifactUpload"
            | "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifactUpload"
            | "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact"
            | "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease"
            | "/mindclade.internal.artifact.v1.ArtifactService/UploadArtifactChunk"
            | "/mindclade.internal.job.v1.OperationService/CancelOperation"
            | "/mindclade.internal.job.v1.JobService/RequestJob"
            | "/mindclade.internal.job.v1.JobService/CancelJob"
            | "/mindclade.internal.job.v1.RunService/AcquireAttemptLease"
            | "/mindclade.internal.job.v1.RunService/RenewAttemptLease"
            | "/mindclade.internal.job.v1.RunService/HeartbeatAttempt"
            | "/mindclade.internal.job.v1.RunService/CancelAttempt"
            | "/mindclade.internal.job.v1.RunService/CommitAttempt"
            | "/mindclade.internal.dataset.v1.DatasetService/CreateDataset"
            | "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset"
            | "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease"
            | "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease"
            | "/mindclade.internal.model.v1.ModelService/RegisterModel"
            | "/mindclade.internal.model.v1.ModelService/RegisterModelRelease"
            | "/mindclade.internal.model.v1.ModelService/PromoteModelRelease"
            | "/mindclade.internal.model.v1.ModelService/RevokeModelRelease"
            | "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization"
            | "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy"
            | "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy"
            | "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy"
            | "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy"
            | "/mindclade.internal.admin.v1.AdminService/UpdateTenant"
            | "/mindclade.internal.admin.v1.AdminService/CreateProject"
            | "/mindclade.internal.admin.v1.AdminService/UpdateProject"
            | "/mindclade.internal.admin.v1.AdminService/ExportAuditRecords"
            | "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition"
            | "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition"
            | "/mindclade.internal.agent.v1.AgentService/StartAgentRun"
            | "/mindclade.internal.agent.v1.AgentService/CancelAgentRun"
            | "/mindclade.internal.agent.v1.AgentService/CommitAgentStep"
            | "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt"
            | "/mindclade.internal.inference.v1.InferenceService/SubmitInference"
            | "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult"
            | "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun"
            | "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun"
            | "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult"
            | "/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision"
            | "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment"
            | "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment"
            | "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment"
            | "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy"
            | "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy"
            | "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial"
            | "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial"
            | "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial"
            | "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun"
            | "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt"
            | "/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt"
            | "/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress"
            | "/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint"
            | "/mindclade.internal.training.v1.TrainingService/CommitCheckpoint"
            | "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun"
            | "/mindclade.internal.training.v1.TrainingService/CancelTrainingRun"
            | "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition"
            | "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition"
            | "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun"
            | "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun"
            | "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition"
            | "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval"
            | "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval"
            | "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval"
    )
}

fn safe_method(method: &str) -> bool {
    matches!(
        method,
        "/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact"
            | "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact"
            | "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts"
            | "/mindclade.internal.artifact.v1.ArtifactService/GetArtifactUpload"
            | "/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias"
            | "/mindclade.internal.job.v1.OperationService/GetOperation"
            | "/mindclade.internal.job.v1.OperationService/ListOperations"
            | "/mindclade.internal.job.v1.OperationService/WatchOperation"
            | "/mindclade.internal.job.v1.JobService/GetJob"
            | "/mindclade.internal.job.v1.JobService/ListJobs"
            | "/mindclade.internal.job.v1.RunService/GetRun"
            | "/mindclade.internal.job.v1.RunService/ListRuns"
            | "/mindclade.internal.job.v1.RunService/GetAttempt"
            | "/mindclade.internal.job.v1.RunService/ListAttempts"
            | "/mindclade.internal.training.v1.TrainingService/GetTrainingRun"
            | "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment"
            | "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments"
            | "/mindclade.internal.experiment.v1.ExperimentService/GetStudy"
            | "/mindclade.internal.experiment.v1.ExperimentService/ListStudies"
            | "/mindclade.internal.experiment.v1.ExperimentService/GetTrial"
            | "/mindclade.internal.experiment.v1.ExperimentService/ListTrials"
            | "/mindclade.internal.training.v1.TrainingService/ListTrainingRuns"
            | "/mindclade.internal.training.v1.TrainingService/GetCheckpoint"
            | "/mindclade.internal.training.v1.TrainingService/ListCheckpoints"
            | "/mindclade.internal.training.v1.TrainingService/WatchTrainingRun"
            | "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest"
            | "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult"
            | "/mindclade.internal.inference.v1.InferenceService/WatchInference"
            | "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun"
            | "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns"
            | "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult"
            | "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision"
            | "/mindclade.internal.dataset.v1.DatasetService/GetDataset"
            | "/mindclade.internal.dataset.v1.DatasetService/ListDatasets"
            | "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease"
            | "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases"
            | "/mindclade.internal.model.v1.ModelService/GetModel"
            | "/mindclade.internal.model.v1.ModelService/ListModels"
            | "/mindclade.internal.model.v1.ModelService/GetModelRelease"
            | "/mindclade.internal.model.v1.ModelService/ListModelReleases"
            | "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy"
            | "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies"
            | "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot"
            | "/mindclade.internal.admin.v1.AdminService/GetTenant"
            | "/mindclade.internal.admin.v1.AdminService/GetProject"
            | "/mindclade.internal.admin.v1.AdminService/ListProjects"
            | "/mindclade.internal.admin.v1.AdminService/QueryAuditRecords"
            | "/mindclade.internal.admin.v1.AdminService/GetAuditExport"
            | "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition"
            | "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions"
            | "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun"
            | "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns"
            | "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun"
            | "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest"
            | "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests"
            | "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition"
            | "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions"
            | "/mindclade.internal.agent.v1.AgentService/GetAgentRun"
            | "/mindclade.internal.agent.v1.AgentService/ListAgentRuns"
            | "/mindclade.internal.agent.v1.AgentService/GetAgentStep"
            | "/mindclade.internal.agent.v1.AgentService/ListAgentSteps"
    )
}

#[async_trait]
pub(crate) trait Sleeper: Send + Sync {
    async fn sleep(&self, duration: Duration);
}

pub(crate) struct TokioSleeper;

#[async_trait]
impl Sleeper for TokioSleeper {
    async fn sleep(&self, duration: Duration) {
        tokio::time::sleep(duration).await;
    }
}

/// Source of retry jitter.
///
/// Production draws from a cryptographically seeded generator; tests inject
/// [`crate::testing::ScriptedJitter`] so every delay is scripted exactly.
pub trait JitterSource: Send + Sync + fmt::Debug {
    /// Returns a value uniformly distributed in `[0, upper_bound_micros]`.
    fn jitter_micros(&self, upper_bound_micros: u64) -> u64;
}

/// Counter-based jitter keyed from operating-system entropy.
///
/// The key is drawn once through the standard library's OS-seeded random
/// state; each draw is a SHA-256 evaluation over `(key, counter)`, rejection
/// sampled so the result is unbiased. No unsafe code and no extra dependency.
pub struct SystemJitter {
    key: [u8; 32],
    counter: AtomicU64,
}

impl SystemJitter {
    #[must_use]
    pub fn new() -> Self {
        let state = RandomState::new();
        let mut key = [0_u8; 32];
        for (index, chunk) in key.chunks_mut(8).enumerate() {
            let mut hasher = state.build_hasher();
            index.hash(&mut hasher);
            std::process::id().hash(&mut hasher);
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_or(0, |value| value.as_nanos())
                .hash(&mut hasher);
            chunk.copy_from_slice(&hasher.finish().to_le_bytes());
        }
        Self {
            key,
            counter: AtomicU64::new(0),
        }
    }

    fn draw(&self) -> u64 {
        let counter = self.counter.fetch_add(1, Ordering::Relaxed);
        let mut hasher = Sha256::new();
        hasher.update(self.key);
        hasher.update(counter.to_le_bytes());
        let digest = hasher.finalize();
        let mut bytes = [0_u8; 8];
        bytes.copy_from_slice(&digest[..8]);
        u64::from_le_bytes(bytes)
    }
}

impl Default for SystemJitter {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Debug for SystemJitter {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SystemJitter")
            .finish_non_exhaustive()
    }
}

impl JitterSource for SystemJitter {
    fn jitter_micros(&self, upper_bound_micros: u64) -> u64 {
        let Some(bound) = upper_bound_micros.checked_add(1) else {
            return self.draw();
        };
        if bound <= 1 {
            return 0;
        }
        let limit = (u64::MAX / bound) * bound;
        for _ in 0..MAX_JITTER_DRAWS {
            let draw = self.draw();
            if draw < limit {
                return draw % bound;
            }
        }
        self.draw() % bound
    }
}

/// Diagnostic verbosity for SDK-emitted telemetry.
///
/// The value comes from `MINDCLADE_LOG` through [`crate::Config::from_env`],
/// or from [`crate::ConfigBuilder::log_level`]. Nothing is emitted at
/// [`LogLevel::Off`].
#[derive(Clone, Copy, Debug, Default, Eq, Ord, PartialEq, PartialOrd)]
pub enum LogLevel {
    #[default]
    Off,
    Error,
    Warn,
    Info,
    Debug,
    Trace,
}

impl LogLevel {
    /// Parses a `MINDCLADE_LOG` value, case-insensitively.
    ///
    /// # Errors
    ///
    /// Returns an error for an unrecognized level.
    pub fn parse(value: &str) -> Result<Self, Error> {
        match value.trim().to_ascii_lowercase().as_str() {
            "off" | "none" | "" => Ok(Self::Off),
            "error" => Ok(Self::Error),
            "warn" | "warning" => Ok(Self::Warn),
            "info" => Ok(Self::Info),
            "debug" => Ok(Self::Debug),
            "trace" => Ok(Self::Trace),
            _ => Err(Error::configuration(
                "MINDCLADE_LOG must be off, error, warn, info, debug, or trace",
            )),
        }
    }

    #[must_use]
    pub fn label(self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::Error => "error",
            Self::Warn => "warn",
            Self::Info => "info",
            Self::Debug => "debug",
            Self::Trace => "trace",
        }
    }
}

/// One issued attempt of a call.
#[derive(Clone, Copy, Debug)]
#[non_exhaustive]
pub struct AttemptEvent<'a> {
    /// Fully qualified gRPC route.
    pub method: &'a str,
    /// One-based attempt number.
    pub attempt: u8,
    /// Time spent on this attempt alone.
    pub elapsed: Duration,
    /// Terminal status of the attempt; `None` while it is still in flight.
    pub status: Option<Code>,
    pub request_id: &'a str,
    pub trace_id: &'a str,
    /// Outbound metadata KEY NAMES. Values are never carried.
    pub metadata_keys: &'a [&'a str],
}

/// A retry that the SDK decided to take, reported before it sleeps.
#[derive(Clone, Copy, Debug)]
#[non_exhaustive]
pub struct RetryEvent<'a> {
    pub method: &'a str,
    /// The attempt number that just failed.
    pub attempt: u8,
    /// Delay before the next attempt.
    pub delay: Duration,
    pub status: Option<Code>,
    pub request_id: &'a str,
}

/// The terminal outcome of a call, success or failure.
#[derive(Clone, Copy, Debug)]
#[non_exhaustive]
pub struct CallEvent<'a> {
    pub method: &'a str,
    /// Attempts actually issued.
    pub attempts: u32,
    /// Wall time across every attempt and every backoff.
    pub elapsed: Duration,
    /// Total time spent sleeping between attempts.
    pub cumulative_delay: Duration,
    pub status: Option<Code>,
    pub final_cause: FinalCause,
    pub request_id: &'a str,
    pub trace_id: &'a str,
}

/// Structured call telemetry.
///
/// Events carry method, attempt, elapsed time, status, correlation identity,
/// and metadata KEY NAMES only. They never carry a request or response
/// payload, a credential, a lease token, or any metadata value.
pub trait Observer: Send + Sync + fmt::Debug {
    /// Called once per issued attempt, after it settles.
    fn on_attempt(&self, event: &AttemptEvent<'_>) {
        let _ = event;
    }

    /// Called once per retry decision, before the backoff sleep.
    fn on_retry(&self, event: &RetryEvent<'_>) {
        let _ = event;
    }

    /// Called exactly once per call, on success or terminal failure.
    fn on_call_complete(&self, event: &CallEvent<'_>) {
        let _ = event;
    }
}

/// Writes every observer event to standard error as one bounded line.
///
/// This is the SDK's built-in `MINDCLADE_LOG` sink. It honours the same
/// no-payload, no-token, key-names-only contract as any other observer.
#[derive(Clone, Copy, Debug, Default)]
pub struct LoggingObserver {
    level: LogLevel,
}

impl LoggingObserver {
    #[must_use]
    pub fn new(level: LogLevel) -> Self {
        Self { level }
    }

    #[must_use]
    pub fn level(self) -> LogLevel {
        self.level
    }

    fn emit(self, level: LogLevel, fields: &str) {
        if self.level == LogLevel::Off || level > self.level {
            return;
        }
        let mut stderr = std::io::stderr().lock();
        let _ = writeln!(stderr, "mindclade-sdk {} {fields}", level.label());
    }
}

impl Observer for LoggingObserver {
    fn on_attempt(&self, event: &AttemptEvent<'_>) {
        self.emit(
            LogLevel::Debug,
            &format!(
                "attempt method={} attempt={} elapsed_ms={} status={} request_id={} trace_id={} metadata_keys=[{}]",
                event.method,
                event.attempt,
                event.elapsed.as_millis(),
                status_label(event.status),
                event.request_id,
                event.trace_id,
                event.metadata_keys.join(","),
            ),
        );
    }

    fn on_retry(&self, event: &RetryEvent<'_>) {
        self.emit(
            LogLevel::Warn,
            &format!(
                "retry method={} attempt={} delay_ms={} status={} request_id={}",
                event.method,
                event.attempt,
                event.delay.as_millis(),
                status_label(event.status),
                event.request_id,
            ),
        );
    }

    fn on_call_complete(&self, event: &CallEvent<'_>) {
        let level = if event.status == Some(Code::Ok) {
            LogLevel::Info
        } else {
            LogLevel::Error
        };
        self.emit(
            level,
            &format!(
                "call method={} attempts={} elapsed_ms={} cumulative_delay_ms={} status={} final_cause={:?} request_id={} trace_id={}",
                event.method,
                event.attempts,
                event.elapsed.as_millis(),
                event.cumulative_delay.as_millis(),
                status_label(event.status),
                event.final_cause,
                event.request_id,
                event.trace_id,
            ),
        );
    }
}

fn status_label(status: Option<Code>) -> &'static str {
    status.map_or("none", |code| code.description())
}

impl ClientCore {
    /// Fans one attempt event out to every configured observer.
    pub(crate) fn observe_attempt(&self, event: &AttemptEvent<'_>) {
        for observer in self.config.observers.iter() {
            observer.on_attempt(event);
        }
    }

    /// Fans one retry decision out to every configured observer.
    pub(crate) fn observe_retry(&self, event: &RetryEvent<'_>) {
        for observer in self.config.observers.iter() {
            observer.on_retry(event);
        }
    }

    /// Fans one terminal call outcome out to every configured observer.
    pub(crate) fn observe_call(&self, event: &CallEvent<'_>) {
        for observer in self.config.observers.iter() {
            observer.on_call_complete(event);
        }
    }

    /// Reports whether any observer is listening at all.
    pub(crate) fn observed(&self) -> bool {
        !self.config.observers.is_empty()
    }
}

impl ClientCore {
    pub(crate) async fn unary<T, R, F>(
        &self,
        message: T,
        prepared: &PreparedCall,
        policy: CallPolicy,
        idempotency_key: Option<&str>,
        invoke: F,
    ) -> Result<Response<R>, Error>
    where
        T: Clone + Send + 'static,
        R: Send + 'static,
        F: Fn(Arc<dyn RpcTransport>, Request<T>) -> RpcFuture<R>,
    {
        if matches!(policy.safety(), CallSafety::Idempotent) && idempotency_key.is_none() {
            return Err(Error::invalid_argument(
                "idempotent commands require an idempotency key",
            ));
        }
        let route = policy.route();
        let attempts = self.attempt_budget(prepared, policy.safety())?;
        let started = Instant::now();
        let mut progress = RetryProgress::default();
        let mut attempt: u8 = 1;
        loop {
            // One attempt's request assembly, credential acquisition, and
            // transport call are boxed so this loop's own future stays small
            // for large generated messages.
            let issued = Box::pin(self.issue_attempt(
                &message,
                prepared,
                idempotency_key,
                attempt,
                route,
                &invoke,
            ));
            let outcome = match issued.await {
                Ok(outcome) => {
                    progress.attempts = u32::from(attempt);
                    outcome
                }
                Err(failure) => {
                    if failure.issued {
                        progress.attempts = u32::from(attempt);
                    }
                    progress.cause = failure.cause;
                    return Err(self.finish(
                        route,
                        prepared,
                        started,
                        progress,
                        failure.status,
                        failure.error,
                    ));
                }
            };
            match outcome {
                Ok(response) => {
                    self.observe_call(&CallEvent {
                        method: route,
                        attempts: progress.attempts,
                        elapsed: started.elapsed(),
                        cumulative_delay: progress.cumulative_delay,
                        status: Some(Code::Ok),
                        final_cause: FinalCause::NotRetried,
                        request_id: &prepared.request_id,
                        trace_id: &prepared.trace_id,
                    });
                    return Ok(Response::from_tonic(response));
                }
                Err(status) => {
                    let error = Error::from_status(&status);
                    let delay = match self.plan_retry(&error, attempt, attempts, prepared) {
                        Ok(delay) => delay,
                        Err(cause) => {
                            progress.cause = cause;
                            let error = if matches!(cause, FinalCause::DeadlineExceeded) {
                                Error::deadline_exceeded()
                            } else {
                                error
                            };
                            return Err(self.finish(
                                route,
                                prepared,
                                started,
                                progress,
                                Some(status.code()),
                                error,
                            ));
                        }
                    };
                    self.observe_retry(&RetryEvent {
                        method: route,
                        attempt,
                        delay,
                        status: Some(status.code()),
                        request_id: &prepared.request_id,
                    });
                    self.sleeper.sleep(delay).await;
                    progress.cumulative_delay = progress.cumulative_delay.saturating_add(delay);
                    attempt += 1;
                }
            }
        }
    }

    /// Issues exactly one attempt.
    ///
    /// Request assembly and credential acquisition happen inside the caller's
    /// total budget, so a slow credential provider consumes the same deadline
    /// as the RPC itself. The attempt is reported to observers whatever its
    /// outcome.
    async fn issue_attempt<T, R, F>(
        &self,
        message: &T,
        prepared: &PreparedCall,
        idempotency_key: Option<&str>,
        attempt: u8,
        route: &str,
        invoke: &F,
    ) -> AttemptOutcome<R>
    where
        T: Clone + Send + 'static,
        R: Send + 'static,
        F: Fn(Arc<dyn RpcTransport>, Request<T>) -> RpcFuture<R>,
    {
        let request = self
            .request(
                message.clone(),
                prepared,
                idempotency_key,
                attempt - 1,
                route,
            )
            .await
            .map_err(|error| AttemptFailure {
                cause: if matches!(error.kind(), ErrorKind::DeadlineExceeded) {
                    FinalCause::DeadlineExceeded
                } else {
                    FinalCause::CredentialFailure
                },
                error,
                status: None,
                issued: false,
            })?;
        let remaining = prepared.remaining().map_err(|error| AttemptFailure {
            error,
            cause: FinalCause::DeadlineExceeded,
            status: None,
            issued: false,
        })?;
        let metadata_keys = self.attempt_metadata_keys(&request);
        let issued = Instant::now();
        let invocation =
            tokio::time::timeout(remaining, invoke(Arc::clone(&self.transport), request)).await;
        let Ok(outcome) = invocation else {
            self.report_attempt(
                route,
                prepared,
                attempt,
                issued,
                Some(Code::DeadlineExceeded),
                &metadata_keys,
            );
            return Err(AttemptFailure {
                error: Error::deadline_exceeded(),
                cause: FinalCause::DeadlineExceeded,
                status: Some(Code::DeadlineExceeded),
                issued: true,
            });
        };
        let status = outcome
            .as_ref()
            .map_or_else(Status::code, |_response| Code::Ok);
        self.report_attempt(
            route,
            prepared,
            attempt,
            issued,
            Some(status),
            &metadata_keys,
        );
        Ok(outcome)
    }

    /// Decides whether one failed attempt is retried and for how long.
    ///
    /// Returns the backoff to sleep, or the terminal cause that ends the
    /// call. A server-pinned `retry-after-ms` is authoritative but is clamped
    /// to the configured maximum backoff, so a remote value can never stall
    /// the caller past its own policy.
    fn plan_retry(
        &self,
        error: &Error,
        attempt: u8,
        attempts: u8,
        prepared: &PreparedCall,
    ) -> Result<Duration, FinalCause> {
        if !error.is_retryable() {
            return Err(if error.server_retry_override() == Some(false) {
                FinalCause::ServerRetryOptOut
            } else {
                FinalCause::NonRetryableStatus
            });
        }
        if attempt >= attempts {
            return Err(FinalCause::AttemptsExhausted);
        }
        let remaining = prepared
            .remaining()
            .map_err(|_| FinalCause::DeadlineExceeded)?;
        let delay = error.retry_after().map_or_else(
            || self.backoff(attempt),
            |hint| hint.min(self.config.retry.max_backoff),
        );
        if delay >= remaining {
            return Err(FinalCause::DeadlineExceeded);
        }
        Ok(delay)
    }

    /// Collects outbound metadata KEY NAMES for observers. Values are never
    /// read, and nothing is collected when no observer is listening.
    fn attempt_metadata_keys<T>(&self, request: &Request<T>) -> Vec<String> {
        if !self.observed() {
            return Vec::new();
        }
        request
            .metadata()
            .keys()
            .map(|key| match key {
                KeyRef::Ascii(key) => key.as_str().to_owned(),
                KeyRef::Binary(key) => key.as_str().to_owned(),
            })
            // Even a key NAME that could identify a credential header is
            // withheld, so an observer sees only routing and policy keys.
            .filter(|key| !crate::is_credential_bearing(key))
            .collect()
    }

    fn report_attempt(
        &self,
        route: &str,
        prepared: &PreparedCall,
        attempt: u8,
        started: Instant,
        status: Option<Code>,
        metadata_keys: &[String],
    ) {
        if !self.observed() {
            return;
        }
        let keys = metadata_keys
            .iter()
            .map(String::as_str)
            .collect::<Vec<&str>>();
        self.observe_attempt(&AttemptEvent {
            method: route,
            attempt,
            elapsed: started.elapsed(),
            status,
            request_id: &prepared.request_id,
            trace_id: &prepared.trace_id,
            metadata_keys: &keys,
        });
    }

    /// Decorates a terminal failure with its retry accounting and reports the
    /// completed call exactly once.
    fn finish(
        &self,
        route: &str,
        prepared: &PreparedCall,
        started: Instant,
        progress: RetryProgress,
        status: Option<Code>,
        error: Error,
    ) -> Error {
        self.observe_call(&CallEvent {
            method: route,
            attempts: progress.attempts,
            elapsed: started.elapsed(),
            cumulative_delay: progress.cumulative_delay,
            status,
            final_cause: progress.cause,
            request_id: &prepared.request_id,
            trace_id: &prepared.trace_id,
        });
        error.with_attempts(progress.summary())
    }

    /// Resolves the attempt budget for one call.
    ///
    /// A never-retry route is pinned to a single attempt whatever the caller
    /// asked for. A non-idempotent route stays at one attempt unless the
    /// caller used the explicitly named unsafe override.
    pub(crate) fn attempt_budget(
        &self,
        prepared: &PreparedCall,
        safety: CallSafety,
    ) -> Result<u8, Error> {
        if matches!(safety, CallSafety::NeverRetry) {
            if prepared.max_attempts.is_some_and(|attempts| attempts > 1) {
                return Err(Error::invalid_argument(
                    "this RPC is never retryable and cannot take an attempt override",
                ));
            }
            return Ok(1);
        }
        if matches!(safety, CallSafety::Unsafe) {
            if !prepared.unsafe_retry_acknowledged {
                return Ok(1);
            }
            return Ok(prepared
                .max_attempts
                .unwrap_or(self.config.retry.max_attempts));
        }
        if prepared.unsafe_retry_acknowledged {
            return Err(Error::invalid_argument(
                "the unsafe non-idempotent retry override cannot be applied to a retryable RPC",
            ));
        }
        Ok(prepared
            .max_attempts
            .unwrap_or(self.config.retry.max_attempts))
    }

    pub(crate) async fn request<T>(
        &self,
        message: T,
        prepared: &PreparedCall,
        idempotency_key: Option<&str>,
        attempt_index: u8,
        route: &str,
    ) -> Result<Request<T>, Error> {
        let remaining = prepared.remaining()?;
        let authorization = if let Some(provider) = &self.config.token_provider {
            let token = tokio::time::timeout(remaining, provider.token(&self.config.audience))
                .await
                .map_err(|_| Error::deadline_exceeded())?
                .map_err(|_| Error::authentication("credential provider failed"))?;
            Some(token.authorization_value(SystemTime::now())?)
        } else {
            None
        };

        let remaining = prepared.remaining()?;

        let mut request = Request::new(message);
        request.set_timeout(remaining);
        // Caller metadata is written first so an SDK-owned key always wins,
        // even though the validators already refuse every reserved key.
        for (key, value) in self.config.custom_metadata.iter() {
            insert_dynamic_metadata(&mut request, key, value)?;
        }
        for (key, value) in &prepared.metadata {
            insert_dynamic_metadata(&mut request, key, value)?;
        }
        insert_metadata(
            &mut request,
            "x-mindclade-sdk",
            sdk_metadata_value(self.config.omit_platform_metadata),
        )?;
        insert_metadata(&mut request, "x-request-id", &prepared.request_id)?;
        insert_metadata(&mut request, "x-trace-id", &prepared.trace_id)?;
        insert_metadata(
            &mut request,
            RETRY_COUNT_METADATA,
            &attempt_index.to_string(),
        )?;
        insert_metadata(
            &mut request,
            TIMEOUT_MS_METADATA,
            &u64::try_from(remaining.as_millis())
                .unwrap_or(u64::MAX)
                .to_string(),
        )?;
        insert_metadata(
            &mut request,
            "x-mindclade-expected-tenant",
            self.config.identity.tenant_id(),
        )?;
        insert_metadata(
            &mut request,
            "x-mindclade-expected-project",
            self.config.identity.project_id(),
        )?;
        insert_metadata(
            &mut request,
            "x-mindclade-expected-principal",
            self.config.identity.principal_id(),
        )?;
        if let Some(value) = idempotency_key {
            insert_metadata(&mut request, "idempotency-key", value)?;
        }

        // Caller interceptors run after all SDK metadata and before any
        // credential is attached. `InterceptorMetadata` cannot read values and
        // refuses reserved and credential-bearing keys, so credential
        // injection below is not reachable from this seam.
        if !self.config.interceptors.is_empty() {
            let context = InterceptContext {
                method: route,
                attempt: attempt_index,
                request_id: &prepared.request_id,
                trace_id: &prepared.trace_id,
                remaining,
            };
            let mut view = InterceptorMetadata::new(request.metadata_mut());
            for interceptor in self.config.interceptors.iter() {
                interceptor.intercept(&context, &mut view)?;
            }
        }

        if let Some(value) = &prepared.lease_token {
            let mut token = MetadataValue::try_from(value.expose())
                .map_err(|_| Error::invalid_argument("lease token is not valid metadata"))?;
            token.set_sensitive(true);
            request
                .metadata_mut()
                .insert("x-mindclade-lease-token", token);
        }

        if let Some(authorization) = authorization {
            let mut value = MetadataValue::try_from(authorization).map_err(|_| {
                Error::authentication("credential provider returned an invalid token")
            })?;
            value.set_sensitive(true);
            request.metadata_mut().insert("authorization", value);
        }
        Ok(request)
    }

    /// Full jitter: a value drawn uniformly from `[0, min(cap, base * 2^n)]`.
    pub(crate) fn backoff(&self, attempt: u8) -> Duration {
        let shift = u32::from(attempt.saturating_sub(1)).min(31);
        let cap = self
            .config
            .retry
            .initial_backoff
            .saturating_mul(1_u32 << shift)
            .min(self.config.retry.max_backoff);
        let ceiling = u64::try_from(cap.as_micros()).unwrap_or(u64::MAX);
        Duration::from_micros(self.config.jitter.jitter_micros(ceiling))
    }
}

fn insert_metadata<T>(
    request: &mut Request<T>,
    key: &'static str,
    value: &str,
) -> Result<(), Error> {
    let value = MetadataValue::try_from(value)
        .map_err(|_| Error::invalid_argument("request metadata is not valid ASCII"))?;
    request.metadata_mut().insert(key, value);
    Ok(())
}

/// Inserts one caller-supplied metadata entry under a runtime key.
fn insert_dynamic_metadata<T>(
    request: &mut Request<T>,
    key: &str,
    value: &str,
) -> Result<(), Error> {
    let key = AsciiMetadataKey::from_bytes(key.as_bytes())
        .map_err(|_| Error::invalid_argument("request metadata key is not valid"))?;
    let value = MetadataValue::try_from(value)
        .map_err(|_| Error::invalid_argument("request metadata is not valid ASCII"))?;
    request.metadata_mut().insert(key, value);
    Ok(())
}
