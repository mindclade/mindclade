use std::{
    collections::hash_map::RandomState,
    fmt,
    future::Future,
    hash::{BuildHasher, Hash, Hasher},
    pin::Pin,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use sha2::{Digest, Sha256};
use tonic::{Request, Response, Status, codegen::async_trait, metadata::MetadataValue};

use crate::{
    ClientCore, Error, ErrorKind, RpcTransport,
    error::{FinalCause, RETRY_COUNT_METADATA, RetryAttemptSummary, TIMEOUT_MS_METADATA},
    request::PreparedCall,
};

/// Bounded rejection-sampling attempts before an unbiased draw is abandoned in
/// favour of a negligibly biased one. The loop can therefore never hang.
const MAX_JITTER_DRAWS: u8 = 8;

pub(crate) type RpcFuture<R> =
    Pin<Box<dyn Future<Output = Result<Response<R>, Status>> + Send + 'static>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CallSafety {
    Safe,
    Idempotent,
    Unsafe,
    /// A raw-only reconciler command that must never be retried implicitly,
    /// and that no named override can make retryable.
    NeverRetry,
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
pub(crate) fn registered_method_safety(method: &str) -> CallSafety {
    if never_retry_method(method) {
        CallSafety::NeverRetry
    } else if idempotent_method(method) {
        CallSafety::Idempotent
    } else if safe_method(method) {
        CallSafety::Safe
    } else {
        CallSafety::Unsafe
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

impl ClientCore {
    pub(crate) async fn unary<T, R, F>(
        &self,
        message: T,
        prepared: &PreparedCall,
        safety: CallSafety,
        idempotency_key: Option<&str>,
        invoke: F,
    ) -> Result<Response<R>, Error>
    where
        T: Clone + Send + 'static,
        R: Send + 'static,
        F: Fn(Arc<dyn RpcTransport>, Request<T>) -> RpcFuture<R>,
    {
        if matches!(safety, CallSafety::Idempotent) && idempotency_key.is_none() {
            return Err(Error::invalid_argument(
                "idempotent commands require an idempotency key",
            ));
        }
        let attempts = self.attempt_budget(prepared, safety)?;
        let mut attempt: u8 = 1;
        let mut cumulative_delay = Duration::ZERO;
        loop {
            let attempt_index = attempt - 1;
            let issued = u32::from(attempt_index);
            let request = self
                .request(message.clone(), prepared, idempotency_key, attempt_index)
                .await
                .map_err(|error| {
                    let cause = if matches!(error.kind(), ErrorKind::DeadlineExceeded) {
                        FinalCause::DeadlineExceeded
                    } else {
                        FinalCause::CredentialFailure
                    };
                    error.with_attempts(RetryAttemptSummary::new(issued, cumulative_delay, cause))
                })?;
            let remaining = prepared.remaining().map_err(|error| {
                error.with_attempts(RetryAttemptSummary::new(
                    issued,
                    cumulative_delay,
                    FinalCause::DeadlineExceeded,
                ))
            })?;
            let invocation =
                tokio::time::timeout(remaining, invoke(Arc::clone(&self.transport), request)).await;
            let made = u32::from(attempt);
            let status = match invocation {
                Err(_elapsed) => {
                    return Err(Error::deadline_exceeded().with_attempts(
                        RetryAttemptSummary::new(
                            made,
                            cumulative_delay,
                            FinalCause::DeadlineExceeded,
                        ),
                    ));
                }
                Ok(Ok(response)) => return Ok(response),
                Ok(Err(status)) => status,
            };
            let error = Error::from_status(&status);
            if !error.is_retryable() {
                let cause = if error.server_retry_override() == Some(false) {
                    FinalCause::ServerRetryOptOut
                } else {
                    FinalCause::NonRetryableStatus
                };
                return Err(
                    error.with_attempts(RetryAttemptSummary::new(made, cumulative_delay, cause))
                );
            }
            if attempt >= attempts {
                return Err(error.with_attempts(RetryAttemptSummary::new(
                    made,
                    cumulative_delay,
                    FinalCause::AttemptsExhausted,
                )));
            }
            let remaining = prepared.remaining().map_err(|deadline| {
                deadline.with_attempts(RetryAttemptSummary::new(
                    made,
                    cumulative_delay,
                    FinalCause::DeadlineExceeded,
                ))
            })?;
            // A server-pinned `retry-after-ms` is authoritative but is clamped
            // to the configured maximum backoff so a remote value can never
            // stall the caller past its own policy.
            let delay = error.retry_after().map_or_else(
                || self.backoff(attempt),
                |hint| hint.min(self.config.retry.max_backoff),
            );
            if delay >= remaining {
                return Err(
                    Error::deadline_exceeded().with_attempts(RetryAttemptSummary::new(
                        made,
                        cumulative_delay,
                        FinalCause::DeadlineExceeded,
                    )),
                );
            }
            self.sleeper.sleep(delay).await;
            cumulative_delay = cumulative_delay.saturating_add(delay);
            attempt += 1;
        }
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
            return Ok(prepared.max_attempts.unwrap_or(self.config.retry.max_attempts));
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
        insert_metadata(
            &mut request,
            "x-mindclade-sdk",
            "mindclade-internal-rust-sdk/0.1",
        )?;
        insert_metadata(&mut request, "x-request-id", &prepared.request_id)?;
        insert_metadata(&mut request, "x-trace-id", &prepared.trace_id)?;
        insert_metadata(&mut request, RETRY_COUNT_METADATA, &attempt_index.to_string())?;
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
