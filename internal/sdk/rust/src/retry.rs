use std::{
    future::Future,
    pin::Pin,
    sync::Arc,
    time::{Duration, Instant, SystemTime},
};

use tonic::{Request, Response, Status, codegen::async_trait, metadata::MetadataValue};

use crate::{ClientCore, Error, RpcTransport, error::is_retryable_code, request::PreparedCall};

pub(crate) type RpcFuture<R> =
    Pin<Box<dyn Future<Output = Result<Response<R>, Status>> + Send + 'static>>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CallSafety {
    Safe,
    Idempotent,
    Unsafe,
}

/// Central policy for ergonomic methods. Unknown methods fail closed to one
/// attempt; transport metadata can never make an unregistered mutation safe.
pub(crate) fn registered_method_safety(method: &str) -> CallSafety {
    if idempotent_method(method) {
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
        let attempts = if matches!(safety, CallSafety::Unsafe) {
            1
        } else {
            self.config.retry.max_attempts
        };

        for attempt in 1..=attempts {
            let request = self
                .request(message.clone(), prepared, idempotency_key)
                .await?;
            let remaining = prepared
                .deadline
                .checked_duration_since(Instant::now())
                .ok_or_else(Error::deadline_exceeded)?;
            let invocation =
                tokio::time::timeout(remaining, invoke(Arc::clone(&self.transport), request))
                    .await
                    .map_err(|_| Error::deadline_exceeded())?;
            match invocation {
                Ok(response) => return Ok(response),
                Err(status) => {
                    let error = Error::from_status(&status);
                    if attempt == attempts || !is_retryable_code(status.code()) {
                        return Err(error);
                    }
                    let remaining = prepared
                        .deadline
                        .checked_duration_since(Instant::now())
                        .ok_or_else(Error::deadline_exceeded)?;
                    let delay = error.retry_after().unwrap_or_else(|| self.backoff(attempt));
                    if delay >= remaining {
                        return Err(Error::deadline_exceeded());
                    }
                    self.sleeper.sleep(delay).await;
                }
            }
        }
        Err(Error::protocol("retry loop exited unexpectedly"))
    }

    pub(crate) async fn request<T>(
        &self,
        message: T,
        prepared: &PreparedCall,
        idempotency_key: Option<&str>,
    ) -> Result<Request<T>, Error> {
        let remaining = prepared
            .deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(Error::deadline_exceeded)?;
        let authorization = if let Some(provider) = &self.config.token_provider {
            let token = tokio::time::timeout(remaining, provider.token(&self.config.audience))
                .await
                .map_err(|_| Error::deadline_exceeded())?
                .map_err(|_| Error::authentication("credential provider failed"))?;
            Some(token.authorization_value(SystemTime::now())?)
        } else {
            None
        };

        let remaining = prepared
            .deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(Error::deadline_exceeded)?;

        let mut request = Request::new(message);
        request.set_timeout(remaining);
        insert_metadata(
            &mut request,
            "x-mindclade-sdk",
            "mindclade-internal-rust-sdk/0.1",
        )?;
        insert_metadata(&mut request, "x-request-id", &prepared.request_id)?;
        insert_metadata(&mut request, "x-trace-id", &prepared.trace_id)?;
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

    pub(crate) fn backoff(&self, attempt: u8) -> Duration {
        let shift = u32::from(attempt.saturating_sub(1)).min(31);
        self.config
            .retry
            .initial_backoff
            .saturating_mul(1_u32 << shift)
            .min(self.config.retry.max_backoff)
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
