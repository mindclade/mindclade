use std::{
    pin::Pin,
    sync::{Arc, Mutex},
    time::SystemTime,
};

use tonic::{
    Request, Response, Status,
    codegen::{async_trait, tokio_stream::Stream},
    metadata::MetadataValue,
    service::{Interceptor, interceptor::InterceptedService},
    transport::{Certificate, Channel, ClientTlsConfig, Endpoint},
};

use mindclade_protocols::internal::{
    admin::v1::{
        CreateProjectRequest, CreateProjectResponse, ExportAuditRecordsRequest,
        ExportAuditRecordsResponse, GetAuditExportRequest, GetAuditExportResponse,
        GetProjectRequest, GetProjectResponse, GetTenantRequest, GetTenantResponse,
        ListProjectsRequest, ListProjectsResponse, QueryAuditRecordsRequest,
        QueryAuditRecordsResponse, UpdateProjectRequest, UpdateProjectResponse,
        UpdateTenantRequest, UpdateTenantResponse, admin_service_client::AdminServiceClient,
    },
    agent::v1::{
        CancelAgentRunRequest, CancelAgentRunResponse, CommitAgentStepRequest,
        CommitAgentStepResponse, CommitToolReceiptRequest, CommitToolReceiptResponse,
        CreateAgentDefinitionRequest, CreateAgentDefinitionResponse, GetAgentDefinitionRequest,
        GetAgentDefinitionResponse, GetAgentRunRequest, GetAgentRunResponse, GetAgentStepRequest,
        GetAgentStepResponse, ListAgentDefinitionsRequest, ListAgentDefinitionsResponse,
        ListAgentRunsRequest, ListAgentRunsResponse, ListAgentStepsRequest, ListAgentStepsResponse,
        StartAgentRunRequest, StartAgentRunResponse, UpdateAgentDefinitionRequest,
        UpdateAgentDefinitionResponse, agent_service_client::AgentServiceClient,
    },
    artifact::v1::{
        AbortArtifactUploadRequest, AbortArtifactUploadResponse, AcquireArtifactLeaseRequest,
        AcquireArtifactLeaseResponse, BeginArtifactUploadRequest, BeginArtifactUploadResponse,
        CommitArtifactRequest, CommitArtifactResponse, DownloadArtifactRequest,
        DownloadArtifactResponse, FinalizeArtifactUploadRequest, FinalizeArtifactUploadResponse,
        GetArtifactRequest, GetArtifactResponse, GetArtifactUploadRequest,
        GetArtifactUploadResponse, ListArtifactsRequest, ListArtifactsResponse,
        QuarantineArtifactRequest, QuarantineArtifactResponse, QuarantineArtifactUploadRequest,
        QuarantineArtifactUploadResponse, ReleaseArtifactLeaseRequest,
        ReleaseArtifactLeaseResponse, ResolveArtifactAliasRequest, ResolveArtifactAliasResponse,
        UploadArtifactChunkRequest, UploadArtifactChunkResponse,
        artifact_service_client::ArtifactServiceClient,
    },
    dataset::v1::{
        CreateDatasetRequest, CreateDatasetResponse, GetDatasetReleaseRequest,
        GetDatasetReleaseResponse, GetDatasetRequest, GetDatasetResponse,
        ListDatasetReleasesRequest, ListDatasetReleasesResponse, ListDatasetsRequest,
        ListDatasetsResponse, PublishDatasetReleaseRequest, PublishDatasetReleaseResponse,
        RevokeDatasetReleaseRequest, RevokeDatasetReleaseResponse, UpdateDatasetRequest,
        UpdateDatasetResponse, dataset_service_client::DatasetServiceClient,
    },
    evaluation::v1::{
        CancelEvaluationRunRequest, CancelEvaluationRunResponse, CommitEvaluationResultRequest,
        CommitEvaluationResultResponse, CreateEvaluationRunRequest, CreateEvaluationRunResponse,
        CreatePromotionDecisionRequest, CreatePromotionDecisionResponse,
        GetEvaluationResultRequest, GetEvaluationResultResponse, GetEvaluationRunRequest,
        GetEvaluationRunResponse, GetPromotionDecisionRequest, GetPromotionDecisionResponse,
        ListEvaluationRunsRequest, ListEvaluationRunsResponse,
        evaluation_service_client::EvaluationServiceClient,
    },
    experiment::v1::{
        CompleteTrialRequest, CompleteTrialResponse, CreateExperimentRequest,
        CreateExperimentResponse, CreateStudyRequest, CreateStudyResponse, CreateTrialRequest,
        CreateTrialResponse, GetExperimentRequest, GetExperimentResponse, GetStudyRequest,
        GetStudyResponse, GetTrialRequest, GetTrialResponse, ListExperimentsRequest,
        ListExperimentsResponse, ListStudiesRequest, ListStudiesResponse, ListTrialsRequest,
        ListTrialsResponse, TransitionExperimentRequest, TransitionExperimentResponse,
        TransitionStudyRequest, TransitionStudyResponse, TransitionTrialRequest,
        TransitionTrialResponse, UpdateExperimentRequest, UpdateExperimentResponse,
        experiment_service_client::ExperimentServiceClient,
    },
    inference::v1::{
        CommitInferenceResultRequest, CommitInferenceResultResponse, GetInferenceRequestRequest,
        GetInferenceRequestResponse, GetInferenceResultRequest, GetInferenceResultResponse,
        SubmitInferenceRequest, SubmitInferenceResponse, WatchInferenceRequest,
        WatchInferenceResponse, inference_service_client::InferenceServiceClient,
    },
    job::v1::{
        AcquireAttemptLeaseRequest, AcquireAttemptLeaseResponse, CancelAttemptRequest,
        CancelAttemptResponse, CancelJobRequest, CancelJobResponse, CancelOperationRequest,
        CancelOperationResponse, CommitAttemptRequest, CommitAttemptResponse, GetAttemptRequest,
        GetAttemptResponse, GetJobRequest, GetJobResponse, GetOperationRequest,
        GetOperationResponse, GetRunRequest, GetRunResponse, HeartbeatAttemptRequest,
        HeartbeatAttemptResponse, ListAttemptsRequest, ListAttemptsResponse, ListJobsRequest,
        ListJobsResponse, ListOperationsRequest, ListOperationsResponse, ListRunsRequest,
        ListRunsResponse, RenewAttemptLeaseRequest, RenewAttemptLeaseResponse, RequestJobRequest,
        RequestJobResponse, WatchOperationRequest, WatchOperationResponse,
        job_service_client::JobServiceClient, operation_service_client::OperationServiceClient,
        run_service_client::RunServiceClient,
    },
    model::v1::{
        GetModelReleaseRequest, GetModelReleaseResponse, GetModelRequest, GetModelResponse,
        ListModelReleasesRequest, ListModelReleasesResponse, ListModelsRequest, ListModelsResponse,
        PromoteModelReleaseRequest, PromoteModelReleaseResponse, RegisterModelReleaseRequest,
        RegisterModelReleaseResponse, RegisterModelRequest, RegisterModelResponse,
        RevokeModelReleaseRequest, RevokeModelReleaseResponse,
        model_service_client::ModelServiceClient,
    },
    policy::v1::{
        ActivateUsePolicyRequest, ActivateUsePolicyResponse, CreateUsePolicyRequest,
        CreateUsePolicyResponse, EvaluateAuthorizationRequest, EvaluateAuthorizationResponse,
        GetUsePolicyRequest, GetUsePolicyResponse, ListUsePoliciesRequest, ListUsePoliciesResponse,
        ResolvePolicySnapshotRequest, ResolvePolicySnapshotResponse, RevokeUsePolicyRequest,
        RevokeUsePolicyResponse, UpdateUsePolicyRequest, UpdateUsePolicyResponse,
        policy_service_client::PolicyServiceClient,
    },
    training::v1::{
        CancelTrainingRunRequest, CancelTrainingRunResponse, CommitCheckpointRequest,
        CommitCheckpointResponse, CommitTrainingProgressRequest, CommitTrainingProgressResponse,
        CompleteTrainingRunRequest, CompleteTrainingRunResponse, CreateTrainingRunRequest,
        CreateTrainingRunResponse, GetCheckpointRequest, GetCheckpointResponse,
        GetTrainingRunRequest, GetTrainingRunResponse, ListCheckpointsRequest,
        ListCheckpointsResponse, ListTrainingRunsRequest, ListTrainingRunsResponse,
        PrepareCheckpointRequest, PrepareCheckpointResponse, ResumeTrainingAttemptRequest,
        ResumeTrainingAttemptResponse, StartTrainingAttemptRequest, StartTrainingAttemptResponse,
        WatchTrainingRunRequest, WatchTrainingRunResponse,
        training_service_client::TrainingServiceClient,
    },
    workflow::v1::{
        CancelWorkflowRunRequest, CancelWorkflowRunResponse, CommitWorkflowTransitionRequest,
        CommitWorkflowTransitionResponse, ConsumeApprovalRequest, ConsumeApprovalResponse,
        CreateWorkflowDefinitionRequest, CreateWorkflowDefinitionResponse, DecideApprovalRequest,
        DecideApprovalResponse, GetApprovalRequestRequest, GetApprovalRequestResponse,
        GetWorkflowDefinitionRequest, GetWorkflowDefinitionResponse, GetWorkflowRunRequest,
        GetWorkflowRunResponse, ListApprovalRequestsRequest, ListApprovalRequestsResponse,
        ListWorkflowDefinitionsRequest, ListWorkflowDefinitionsResponse, ListWorkflowRunsRequest,
        ListWorkflowRunsResponse, RequestApprovalRequest, RequestApprovalResponse,
        StartWorkflowRunRequest, StartWorkflowRunResponse, UpdateWorkflowDefinitionRequest,
        UpdateWorkflowDefinitionResponse, WatchWorkflowRunRequest, WatchWorkflowRunResponse,
        approval_service_client::ApprovalServiceClient,
        workflow_service_client::WorkflowServiceClient,
    },
};

use crate::{
    Config, Error,
    config::{TrustRoots, validate_metadata_value},
    request::generate_request_id,
};

/// Boxed generated operation-update stream used by production and fake
/// transports.
pub type OperationStream =
    Pin<Box<dyn Stream<Item = Result<WatchOperationResponse, Status>> + Send + 'static>>;

/// Boxed generation-pinned artifact byte stream used by production and fake
/// transports.
pub type ArtifactStream =
    Pin<Box<dyn Stream<Item = Result<DownloadArtifactResponse, Status>> + Send + 'static>>;

/// Boxed generated inference stream used by production and injectable
/// transports. Messages and cursors remain authoritative protobuf values.
pub type InferenceStream =
    Pin<Box<dyn Stream<Item = Result<WatchInferenceResponse, Status>> + Send + 'static>>;

/// Boxed generated workflow-revision stream used by production and fake
/// transports.
pub type WorkflowStream =
    Pin<Box<dyn Stream<Item = Result<WatchWorkflowRunResponse, Status>> + Send + 'static>>;

/// Boxed generated training-update stream used by production and fake
/// transports.
pub type TrainingStream =
    Pin<Box<dyn Stream<Item = Result<WatchTrainingRunResponse, Status>> + Send + 'static>>;

type AuthorizedChannel = InterceptedService<Channel, GeneratedClientInterceptor>;
const MAX_WIRE_MESSAGE_BYTES: usize = 8 << 20;

macro_rules! bounded_client {
    ($client:ty, $channel:expr) => {
        <$client>::new($channel)
            .max_decoding_message_size(MAX_WIRE_MESSAGE_BYTES)
            .max_encoding_message_size(MAX_WIRE_MESSAGE_BYTES)
    };
}

/// Complete generated Tonic client estate for uncommon internal workflows.
/// Every client is backed by a policy-enforcing interceptor, so callers cannot
/// bypass authentication or tenant-scope expectations by passing a bare
/// generated message.
#[derive(Clone)]
pub struct GeneratedClients {
    pub admin: AdminServiceClient<AuthorizedChannel>,
    pub agent: AgentServiceClient<AuthorizedChannel>,
    pub artifact: ArtifactServiceClient<AuthorizedChannel>,
    pub dataset: DatasetServiceClient<AuthorizedChannel>,
    pub evaluation: EvaluationServiceClient<AuthorizedChannel>,
    pub experiment: ExperimentServiceClient<AuthorizedChannel>,
    pub inference: InferenceServiceClient<AuthorizedChannel>,
    pub job: JobServiceClient<AuthorizedChannel>,
    pub operation: OperationServiceClient<AuthorizedChannel>,
    pub run: RunServiceClient<AuthorizedChannel>,
    pub model: ModelServiceClient<AuthorizedChannel>,
    pub policy: PolicyServiceClient<AuthorizedChannel>,
    pub training: TrainingServiceClient<AuthorizedChannel>,
    pub workflow: WorkflowServiceClient<AuthorizedChannel>,
    pub approval: ApprovalServiceClient<AuthorizedChannel>,
}

impl GeneratedClients {
    pub(crate) async fn authorized(channel: Channel, config: &Config) -> Result<Self, Error> {
        let (authorization, expires_at) = if let Some(provider) = &config.token_provider {
            let token = tokio::time::timeout(config.rpc_timeout, provider.token(&config.audience))
                .await
                .map_err(|_| Error::deadline_exceeded())?
                .map_err(|_| Error::authentication("credential provider failed"))?;
            (
                Some(sensitive_authorization(
                    &token.authorization_value(SystemTime::now())?,
                )?),
                Some(token.expires_at()),
            )
        } else {
            (None, None)
        };
        let interceptor = GeneratedClientInterceptor {
            authorization,
            expires_at,
            tenant_id: metadata_value(config.identity.tenant_id())?,
            project_id: metadata_value(config.identity.project_id())?,
            principal_id: metadata_value(config.identity.principal_id())?,
            timeout: config.rpc_timeout,
        };
        Ok(Self::new(AuthorizedChannel::new(channel, interceptor)))
    }

    fn new(channel: AuthorizedChannel) -> Self {
        Self {
            admin: bounded_client!(AdminServiceClient<_>, channel.clone()),
            agent: bounded_client!(AgentServiceClient<_>, channel.clone()),
            artifact: bounded_client!(ArtifactServiceClient<_>, channel.clone()),
            dataset: bounded_client!(DatasetServiceClient<_>, channel.clone()),
            evaluation: bounded_client!(EvaluationServiceClient<_>, channel.clone()),
            experiment: bounded_client!(ExperimentServiceClient<_>, channel.clone()),
            inference: bounded_client!(InferenceServiceClient<_>, channel.clone()),
            job: bounded_client!(JobServiceClient<_>, channel.clone()),
            operation: bounded_client!(OperationServiceClient<_>, channel.clone()),
            run: bounded_client!(RunServiceClient<_>, channel.clone()),
            model: bounded_client!(ModelServiceClient<_>, channel.clone()),
            policy: bounded_client!(PolicyServiceClient<_>, channel.clone()),
            training: bounded_client!(TrainingServiceClient<_>, channel.clone()),
            workflow: bounded_client!(WorkflowServiceClient<_>, channel.clone()),
            approval: bounded_client!(ApprovalServiceClient<_>, channel),
        }
    }
}

#[derive(Clone)]
#[doc(hidden)]
pub struct GeneratedClientInterceptor {
    authorization: Option<MetadataValue<tonic::metadata::Ascii>>,
    expires_at: Option<SystemTime>,
    tenant_id: MetadataValue<tonic::metadata::Ascii>,
    project_id: MetadataValue<tonic::metadata::Ascii>,
    principal_id: MetadataValue<tonic::metadata::Ascii>,
    timeout: std::time::Duration,
}

impl Interceptor for GeneratedClientInterceptor {
    fn call(&mut self, mut request: Request<()>) -> Result<Request<()>, Status> {
        let credential_is_stale = self.expires_at.is_some_and(|expires_at| {
            expires_at
                .duration_since(SystemTime::now())
                .map_or(true, |remaining| {
                    remaining <= std::time::Duration::from_secs(30)
                })
        });
        if credential_is_stale {
            return Err(Status::unauthenticated(
                "generated client credential must be refreshed",
            ));
        }
        let request_id = match request.metadata().get("x-request-id") {
            Some(value) => value
                .to_str()
                .map_err(|_| Status::invalid_argument("request identity is invalid"))?
                .to_owned(),
            None => generate_request_id(),
        };
        validate_metadata_value("request ID", &request_id, true)
            .map_err(|_| Status::invalid_argument("request identity is invalid"))?;
        if let Some(trace_id) = request.metadata().get("x-trace-id") {
            let trace_id = trace_id
                .to_str()
                .map_err(|_| Status::invalid_argument("trace identity is invalid"))?;
            validate_metadata_value("trace ID", trace_id, true)
                .map_err(|_| Status::invalid_argument("trace identity is invalid"))?;
        }
        let timeout = request
            .metadata()
            .get("grpc-timeout")
            .and_then(parse_grpc_timeout)
            .map_or(self.timeout, |requested| requested.min(self.timeout));
        for key in [
            "authorization",
            "proxy-authorization",
            "cookie",
            "x-api-key",
            "x-goog-api-key",
        ] {
            request.metadata_mut().remove(key);
        }
        if let Some(authorization) = &self.authorization {
            request
                .metadata_mut()
                .insert("authorization", authorization.clone());
        }
        request
            .metadata_mut()
            .insert("x-mindclade-expected-tenant", self.tenant_id.clone());
        request
            .metadata_mut()
            .insert("x-mindclade-expected-project", self.project_id.clone());
        request
            .metadata_mut()
            .insert("x-mindclade-expected-principal", self.principal_id.clone());
        request.metadata_mut().insert(
            "x-mindclade-sdk",
            MetadataValue::from_static("mindclade-internal-rust-sdk/0.1"),
        );
        if request.metadata().get("x-request-id").is_none() {
            request.metadata_mut().insert(
                "x-request-id",
                metadata_value(&request_id)
                    .map_err(|_| Status::internal("request identity failed"))?,
            );
        }
        if request.metadata().get("x-trace-id").is_none() {
            request.metadata_mut().insert(
                "x-trace-id",
                metadata_value(&request_id)
                    .map_err(|_| Status::internal("trace identity failed"))?,
            );
        }
        request.set_timeout(timeout);
        Ok(request)
    }
}

fn parse_grpc_timeout(
    value: &MetadataValue<tonic::metadata::Ascii>,
) -> Option<std::time::Duration> {
    let value = value.to_str().ok()?;
    if value.len() < 2 || value.len() > 9 {
        return None;
    }
    let (digits, unit) = value.split_at(value.len() - 1);
    let amount = digits.parse::<u64>().ok()?;
    match unit {
        "H" => amount
            .checked_mul(60 * 60)
            .map(std::time::Duration::from_secs),
        "M" => amount.checked_mul(60).map(std::time::Duration::from_secs),
        "S" => Some(std::time::Duration::from_secs(amount)),
        "m" => Some(std::time::Duration::from_millis(amount)),
        "u" => Some(std::time::Duration::from_micros(amount)),
        "n" => Some(std::time::Duration::from_nanos(amount)),
        _ => None,
    }
}

fn metadata_value(value: &str) -> Result<MetadataValue<tonic::metadata::Ascii>, Error> {
    MetadataValue::try_from(value)
        .map_err(|_| Error::configuration("generated client metadata is invalid"))
}

fn sensitive_authorization(value: &str) -> Result<MetadataValue<tonic::metadata::Ascii>, Error> {
    let mut value = MetadataValue::try_from(value)
        .map_err(|_| Error::authentication("credential provider returned an invalid token"))?;
    value.set_sensitive(true);
    Ok(value)
}

/// Narrow injectable seam around generated service clients. Every argument and
/// response is an authoritative generated Protobuf type.
#[async_trait]
pub trait RpcTransport: Send + Sync {
    async fn create_agent_definition(
        &self,
        request: Request<CreateAgentDefinitionRequest>,
    ) -> Result<Response<CreateAgentDefinitionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_agent_definition fake is not configured",
        ))
    }

    async fn update_agent_definition(
        &self,
        request: Request<UpdateAgentDefinitionRequest>,
    ) -> Result<Response<UpdateAgentDefinitionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "update_agent_definition fake is not configured",
        ))
    }

    async fn get_agent_definition(
        &self,
        request: Request<GetAgentDefinitionRequest>,
    ) -> Result<Response<GetAgentDefinitionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_agent_definition fake is not configured",
        ))
    }

    async fn list_agent_definitions(
        &self,
        request: Request<ListAgentDefinitionsRequest>,
    ) -> Result<Response<ListAgentDefinitionsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_agent_definitions fake is not configured",
        ))
    }

    async fn start_agent_run(
        &self,
        request: Request<StartAgentRunRequest>,
    ) -> Result<Response<StartAgentRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "start_agent_run fake is not configured",
        ))
    }

    async fn get_agent_run(
        &self,
        request: Request<GetAgentRunRequest>,
    ) -> Result<Response<GetAgentRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_agent_run fake is not configured",
        ))
    }

    async fn list_agent_runs(
        &self,
        request: Request<ListAgentRunsRequest>,
    ) -> Result<Response<ListAgentRunsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_agent_runs fake is not configured",
        ))
    }

    async fn cancel_agent_run(
        &self,
        request: Request<CancelAgentRunRequest>,
    ) -> Result<Response<CancelAgentRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "cancel_agent_run fake is not configured",
        ))
    }

    async fn get_agent_step(
        &self,
        request: Request<GetAgentStepRequest>,
    ) -> Result<Response<GetAgentStepResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_agent_step fake is not configured",
        ))
    }

    async fn list_agent_steps(
        &self,
        request: Request<ListAgentStepsRequest>,
    ) -> Result<Response<ListAgentStepsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_agent_steps fake is not configured",
        ))
    }

    async fn commit_agent_step(
        &self,
        request: Request<CommitAgentStepRequest>,
    ) -> Result<Response<CommitAgentStepResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_agent_step fake is not configured",
        ))
    }

    async fn commit_tool_receipt(
        &self,
        request: Request<CommitToolReceiptRequest>,
    ) -> Result<Response<CommitToolReceiptResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_tool_receipt fake is not configured",
        ))
    }

    async fn create_training_run(
        &self,
        request: Request<CreateTrainingRunRequest>,
    ) -> Result<Response<CreateTrainingRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_training_run fake is not configured",
        ))
    }

    async fn get_training_run(
        &self,
        request: Request<GetTrainingRunRequest>,
    ) -> Result<Response<GetTrainingRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_training_run fake is not configured",
        ))
    }

    async fn list_training_runs(
        &self,
        request: Request<ListTrainingRunsRequest>,
    ) -> Result<Response<ListTrainingRunsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_training_runs fake is not configured",
        ))
    }

    async fn start_training_attempt(
        &self,
        request: Request<StartTrainingAttemptRequest>,
    ) -> Result<Response<StartTrainingAttemptResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "start_training_attempt fake is not configured",
        ))
    }

    async fn resume_training_attempt(
        &self,
        request: Request<ResumeTrainingAttemptRequest>,
    ) -> Result<Response<ResumeTrainingAttemptResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "resume_training_attempt fake is not configured",
        ))
    }

    async fn commit_training_progress(
        &self,
        request: Request<CommitTrainingProgressRequest>,
    ) -> Result<Response<CommitTrainingProgressResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_training_progress fake is not configured",
        ))
    }

    async fn prepare_checkpoint(
        &self,
        request: Request<PrepareCheckpointRequest>,
    ) -> Result<Response<PrepareCheckpointResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "prepare_checkpoint fake is not configured",
        ))
    }

    async fn commit_checkpoint(
        &self,
        request: Request<CommitCheckpointRequest>,
    ) -> Result<Response<CommitCheckpointResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_checkpoint fake is not configured",
        ))
    }

    async fn complete_training_run(
        &self,
        request: Request<CompleteTrainingRunRequest>,
    ) -> Result<Response<CompleteTrainingRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "complete_training_run fake is not configured",
        ))
    }

    async fn cancel_training_run(
        &self,
        request: Request<CancelTrainingRunRequest>,
    ) -> Result<Response<CancelTrainingRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "cancel_training_run fake is not configured",
        ))
    }

    async fn get_checkpoint(
        &self,
        request: Request<GetCheckpointRequest>,
    ) -> Result<Response<GetCheckpointResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_checkpoint fake is not configured",
        ))
    }

    async fn list_checkpoints(
        &self,
        request: Request<ListCheckpointsRequest>,
    ) -> Result<Response<ListCheckpointsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_checkpoints fake is not configured",
        ))
    }

    async fn watch_training_run(
        &self,
        request: Request<WatchTrainingRunRequest>,
    ) -> Result<Response<TrainingStream>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "watch_training_run fake is not configured",
        ))
    }

    async fn get_operation(
        &self,
        request: Request<GetOperationRequest>,
    ) -> Result<Response<GetOperationResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_operation fake is not configured",
        ))
    }

    async fn list_operations(
        &self,
        request: Request<ListOperationsRequest>,
    ) -> Result<Response<ListOperationsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_operations fake is not configured",
        ))
    }

    async fn cancel_operation(
        &self,
        request: Request<CancelOperationRequest>,
    ) -> Result<Response<CancelOperationResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "cancel_operation fake is not configured",
        ))
    }

    async fn watch_operation(
        &self,
        request: Request<WatchOperationRequest>,
    ) -> Result<Response<OperationStream>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "watch_operation fake is not configured",
        ))
    }

    async fn request_job(
        &self,
        request: Request<RequestJobRequest>,
    ) -> Result<Response<RequestJobResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("request_job fake is not configured"))
    }

    async fn get_job(
        &self,
        request: Request<GetJobRequest>,
    ) -> Result<Response<GetJobResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_job fake is not configured"))
    }

    async fn list_jobs(
        &self,
        request: Request<ListJobsRequest>,
    ) -> Result<Response<ListJobsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("list_jobs fake is not configured"))
    }

    async fn cancel_job(
        &self,
        request: Request<CancelJobRequest>,
    ) -> Result<Response<CancelJobResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("cancel_job fake is not configured"))
    }

    async fn get_run(
        &self,
        request: Request<GetRunRequest>,
    ) -> Result<Response<GetRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_run fake is not configured"))
    }

    async fn list_runs(
        &self,
        request: Request<ListRunsRequest>,
    ) -> Result<Response<ListRunsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("list_runs fake is not configured"))
    }

    async fn get_attempt(
        &self,
        request: Request<GetAttemptRequest>,
    ) -> Result<Response<GetAttemptResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_attempt fake is not configured"))
    }

    async fn list_attempts(
        &self,
        request: Request<ListAttemptsRequest>,
    ) -> Result<Response<ListAttemptsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_attempts fake is not configured",
        ))
    }

    async fn acquire_attempt_lease(
        &self,
        request: Request<AcquireAttemptLeaseRequest>,
    ) -> Result<Response<AcquireAttemptLeaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "acquire_attempt_lease fake is not configured",
        ))
    }

    async fn renew_attempt_lease(
        &self,
        request: Request<RenewAttemptLeaseRequest>,
    ) -> Result<Response<RenewAttemptLeaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "renew_attempt_lease fake is not configured",
        ))
    }

    async fn heartbeat_attempt(
        &self,
        request: Request<HeartbeatAttemptRequest>,
    ) -> Result<Response<HeartbeatAttemptResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "heartbeat_attempt fake is not configured",
        ))
    }

    async fn cancel_attempt(
        &self,
        request: Request<CancelAttemptRequest>,
    ) -> Result<Response<CancelAttemptResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "cancel_attempt fake is not configured",
        ))
    }

    async fn commit_attempt(
        &self,
        request: Request<CommitAttemptRequest>,
    ) -> Result<Response<CommitAttemptResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_attempt fake is not configured",
        ))
    }

    async fn resolve_artifact_alias(
        &self,
        request: Request<ResolveArtifactAliasRequest>,
    ) -> Result<Response<ResolveArtifactAliasResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "resolve_artifact_alias fake is not configured",
        ))
    }

    async fn get_artifact(
        &self,
        request: Request<GetArtifactRequest>,
    ) -> Result<Response<GetArtifactResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_artifact fake is not configured"))
    }

    async fn list_artifacts(
        &self,
        request: Request<ListArtifactsRequest>,
    ) -> Result<Response<ListArtifactsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_artifacts fake is not configured",
        ))
    }

    async fn quarantine_artifact(
        &self,
        request: Request<QuarantineArtifactRequest>,
    ) -> Result<Response<QuarantineArtifactResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "quarantine_artifact fake is not configured",
        ))
    }

    async fn acquire_artifact_lease(
        &self,
        request: Request<AcquireArtifactLeaseRequest>,
    ) -> Result<Response<AcquireArtifactLeaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "acquire_artifact_lease fake is not configured",
        ))
    }

    async fn release_artifact_lease(
        &self,
        request: Request<ReleaseArtifactLeaseRequest>,
    ) -> Result<Response<ReleaseArtifactLeaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "release_artifact_lease fake is not configured",
        ))
    }

    async fn begin_artifact_upload(
        &self,
        request: Request<BeginArtifactUploadRequest>,
    ) -> Result<Response<BeginArtifactUploadResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "begin_artifact_upload fake is not configured",
        ))
    }

    async fn upload_artifact_chunk(
        &self,
        request: Request<UploadArtifactChunkRequest>,
    ) -> Result<Response<UploadArtifactChunkResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "upload_artifact_chunk fake is not configured",
        ))
    }

    async fn get_artifact_upload(
        &self,
        request: Request<GetArtifactUploadRequest>,
    ) -> Result<Response<GetArtifactUploadResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_artifact_upload fake is not configured",
        ))
    }

    async fn finalize_artifact_upload(
        &self,
        request: Request<FinalizeArtifactUploadRequest>,
    ) -> Result<Response<FinalizeArtifactUploadResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "finalize_artifact_upload fake is not configured",
        ))
    }

    async fn abort_artifact_upload(
        &self,
        request: Request<AbortArtifactUploadRequest>,
    ) -> Result<Response<AbortArtifactUploadResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "abort_artifact_upload fake is not configured",
        ))
    }

    async fn quarantine_artifact_upload(
        &self,
        request: Request<QuarantineArtifactUploadRequest>,
    ) -> Result<Response<QuarantineArtifactUploadResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "quarantine_artifact_upload fake is not configured",
        ))
    }

    async fn commit_artifact(
        &self,
        request: Request<CommitArtifactRequest>,
    ) -> Result<Response<CommitArtifactResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_artifact fake is not configured",
        ))
    }

    async fn download_artifact(
        &self,
        request: Request<DownloadArtifactRequest>,
    ) -> Result<Response<ArtifactStream>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "download_artifact fake is not configured",
        ))
    }

    async fn submit_inference(
        &self,
        request: Request<SubmitInferenceRequest>,
    ) -> Result<Response<SubmitInferenceResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "submit_inference fake is not configured",
        ))
    }
    async fn get_inference_request(
        &self,
        request: Request<GetInferenceRequestRequest>,
    ) -> Result<Response<GetInferenceRequestResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_inference_request fake is not configured",
        ))
    }
    async fn get_inference_result(
        &self,
        request: Request<GetInferenceResultRequest>,
    ) -> Result<Response<GetInferenceResultResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_inference_result fake is not configured",
        ))
    }
    async fn commit_inference_result(
        &self,
        request: Request<CommitInferenceResultRequest>,
    ) -> Result<Response<CommitInferenceResultResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_inference_result fake is not configured",
        ))
    }
    async fn watch_inference(
        &self,
        request: Request<WatchInferenceRequest>,
    ) -> Result<Response<InferenceStream>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "watch_inference fake is not configured",
        ))
    }

    async fn create_dataset(
        &self,
        request: Request<CreateDatasetRequest>,
    ) -> Result<Response<CreateDatasetResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_dataset fake is not configured",
        ))
    }
    async fn get_dataset(
        &self,
        request: Request<GetDatasetRequest>,
    ) -> Result<Response<GetDatasetResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_dataset fake is not configured"))
    }
    async fn list_datasets(
        &self,
        request: Request<ListDatasetsRequest>,
    ) -> Result<Response<ListDatasetsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_datasets fake is not configured",
        ))
    }
    async fn update_dataset(
        &self,
        request: Request<UpdateDatasetRequest>,
    ) -> Result<Response<UpdateDatasetResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "update_dataset fake is not configured",
        ))
    }
    async fn publish_dataset_release(
        &self,
        request: Request<PublishDatasetReleaseRequest>,
    ) -> Result<Response<PublishDatasetReleaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "publish_dataset_release fake is not configured",
        ))
    }
    async fn revoke_dataset_release(
        &self,
        request: Request<RevokeDatasetReleaseRequest>,
    ) -> Result<Response<RevokeDatasetReleaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "revoke_dataset_release fake is not configured",
        ))
    }
    async fn get_dataset_release(
        &self,
        request: Request<GetDatasetReleaseRequest>,
    ) -> Result<Response<GetDatasetReleaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_dataset_release fake is not configured",
        ))
    }
    async fn list_dataset_releases(
        &self,
        request: Request<ListDatasetReleasesRequest>,
    ) -> Result<Response<ListDatasetReleasesResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_dataset_releases fake is not configured",
        ))
    }

    async fn create_evaluation_run(
        &self,
        request: Request<CreateEvaluationRunRequest>,
    ) -> Result<Response<CreateEvaluationRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_evaluation_run fake is not configured",
        ))
    }
    async fn get_evaluation_run(
        &self,
        request: Request<GetEvaluationRunRequest>,
    ) -> Result<Response<GetEvaluationRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_evaluation_run fake is not configured",
        ))
    }
    async fn list_evaluation_runs(
        &self,
        request: Request<ListEvaluationRunsRequest>,
    ) -> Result<Response<ListEvaluationRunsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_evaluation_runs fake is not configured",
        ))
    }
    async fn cancel_evaluation_run(
        &self,
        request: Request<CancelEvaluationRunRequest>,
    ) -> Result<Response<CancelEvaluationRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "cancel_evaluation_run fake is not configured",
        ))
    }
    async fn commit_evaluation_result(
        &self,
        request: Request<CommitEvaluationResultRequest>,
    ) -> Result<Response<CommitEvaluationResultResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_evaluation_result fake is not configured",
        ))
    }
    async fn get_evaluation_result(
        &self,
        request: Request<GetEvaluationResultRequest>,
    ) -> Result<Response<GetEvaluationResultResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_evaluation_result fake is not configured",
        ))
    }
    async fn create_promotion_decision(
        &self,
        request: Request<CreatePromotionDecisionRequest>,
    ) -> Result<Response<CreatePromotionDecisionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_promotion_decision fake is not configured",
        ))
    }
    async fn get_promotion_decision(
        &self,
        request: Request<GetPromotionDecisionRequest>,
    ) -> Result<Response<GetPromotionDecisionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_promotion_decision fake is not configured",
        ))
    }

    async fn create_experiment(
        &self,
        request: Request<CreateExperimentRequest>,
    ) -> Result<Response<CreateExperimentResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_experiment fake is not configured",
        ))
    }
    async fn get_experiment(
        &self,
        request: Request<GetExperimentRequest>,
    ) -> Result<Response<GetExperimentResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_experiment fake is not configured",
        ))
    }
    async fn list_experiments(
        &self,
        request: Request<ListExperimentsRequest>,
    ) -> Result<Response<ListExperimentsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_experiments fake is not configured",
        ))
    }
    async fn update_experiment(
        &self,
        request: Request<UpdateExperimentRequest>,
    ) -> Result<Response<UpdateExperimentResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "update_experiment fake is not configured",
        ))
    }
    async fn transition_experiment(
        &self,
        request: Request<TransitionExperimentRequest>,
    ) -> Result<Response<TransitionExperimentResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "transition_experiment fake is not configured",
        ))
    }
    async fn create_study(
        &self,
        request: Request<CreateStudyRequest>,
    ) -> Result<Response<CreateStudyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("create_study fake is not configured"))
    }
    async fn get_study(
        &self,
        request: Request<GetStudyRequest>,
    ) -> Result<Response<GetStudyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_study fake is not configured"))
    }
    async fn list_studies(
        &self,
        request: Request<ListStudiesRequest>,
    ) -> Result<Response<ListStudiesResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("list_studies fake is not configured"))
    }
    async fn transition_study(
        &self,
        request: Request<TransitionStudyRequest>,
    ) -> Result<Response<TransitionStudyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "transition_study fake is not configured",
        ))
    }
    async fn create_trial(
        &self,
        request: Request<CreateTrialRequest>,
    ) -> Result<Response<CreateTrialResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("create_trial fake is not configured"))
    }
    async fn get_trial(
        &self,
        request: Request<GetTrialRequest>,
    ) -> Result<Response<GetTrialResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_trial fake is not configured"))
    }
    async fn list_trials(
        &self,
        request: Request<ListTrialsRequest>,
    ) -> Result<Response<ListTrialsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("list_trials fake is not configured"))
    }
    async fn transition_trial(
        &self,
        request: Request<TransitionTrialRequest>,
    ) -> Result<Response<TransitionTrialResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "transition_trial fake is not configured",
        ))
    }
    async fn complete_trial(
        &self,
        request: Request<CompleteTrialRequest>,
    ) -> Result<Response<CompleteTrialResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "complete_trial fake is not configured",
        ))
    }

    async fn register_model(
        &self,
        request: Request<RegisterModelRequest>,
    ) -> Result<Response<RegisterModelResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "register_model fake is not configured",
        ))
    }
    async fn get_model(
        &self,
        request: Request<GetModelRequest>,
    ) -> Result<Response<GetModelResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_model fake is not configured"))
    }
    async fn list_models(
        &self,
        request: Request<ListModelsRequest>,
    ) -> Result<Response<ListModelsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("list_models fake is not configured"))
    }
    async fn register_model_release(
        &self,
        request: Request<RegisterModelReleaseRequest>,
    ) -> Result<Response<RegisterModelReleaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "register_model_release fake is not configured",
        ))
    }
    async fn get_model_release(
        &self,
        request: Request<GetModelReleaseRequest>,
    ) -> Result<Response<GetModelReleaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_model_release fake is not configured",
        ))
    }
    async fn list_model_releases(
        &self,
        request: Request<ListModelReleasesRequest>,
    ) -> Result<Response<ListModelReleasesResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_model_releases fake is not configured",
        ))
    }
    async fn promote_model_release(
        &self,
        request: Request<PromoteModelReleaseRequest>,
    ) -> Result<Response<PromoteModelReleaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "promote_model_release fake is not configured",
        ))
    }
    async fn revoke_model_release(
        &self,
        request: Request<RevokeModelReleaseRequest>,
    ) -> Result<Response<RevokeModelReleaseResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "revoke_model_release fake is not configured",
        ))
    }

    async fn evaluate_authorization(
        &self,
        request: Request<EvaluateAuthorizationRequest>,
    ) -> Result<Response<EvaluateAuthorizationResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "evaluate_authorization fake is not configured",
        ))
    }
    async fn create_use_policy(
        &self,
        request: Request<CreateUsePolicyRequest>,
    ) -> Result<Response<CreateUsePolicyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_use_policy fake is not configured",
        ))
    }
    async fn update_use_policy(
        &self,
        request: Request<UpdateUsePolicyRequest>,
    ) -> Result<Response<UpdateUsePolicyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "update_use_policy fake is not configured",
        ))
    }
    async fn get_use_policy(
        &self,
        request: Request<GetUsePolicyRequest>,
    ) -> Result<Response<GetUsePolicyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_use_policy fake is not configured",
        ))
    }
    async fn list_use_policies(
        &self,
        request: Request<ListUsePoliciesRequest>,
    ) -> Result<Response<ListUsePoliciesResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_use_policies fake is not configured",
        ))
    }
    async fn activate_use_policy(
        &self,
        request: Request<ActivateUsePolicyRequest>,
    ) -> Result<Response<ActivateUsePolicyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "activate_use_policy fake is not configured",
        ))
    }
    async fn revoke_use_policy(
        &self,
        request: Request<RevokeUsePolicyRequest>,
    ) -> Result<Response<RevokeUsePolicyResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "revoke_use_policy fake is not configured",
        ))
    }
    async fn resolve_policy_snapshot(
        &self,
        request: Request<ResolvePolicySnapshotRequest>,
    ) -> Result<Response<ResolvePolicySnapshotResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "resolve_policy_snapshot fake is not configured",
        ))
    }

    async fn get_tenant(
        &self,
        request: Request<GetTenantRequest>,
    ) -> Result<Response<GetTenantResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_tenant fake is not configured"))
    }
    async fn update_tenant(
        &self,
        request: Request<UpdateTenantRequest>,
    ) -> Result<Response<UpdateTenantResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "update_tenant fake is not configured",
        ))
    }
    async fn create_project(
        &self,
        request: Request<CreateProjectRequest>,
    ) -> Result<Response<CreateProjectResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_project fake is not configured",
        ))
    }
    async fn get_project(
        &self,
        request: Request<GetProjectRequest>,
    ) -> Result<Response<GetProjectResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented("get_project fake is not configured"))
    }
    async fn list_projects(
        &self,
        request: Request<ListProjectsRequest>,
    ) -> Result<Response<ListProjectsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_projects fake is not configured",
        ))
    }
    async fn update_project(
        &self,
        request: Request<UpdateProjectRequest>,
    ) -> Result<Response<UpdateProjectResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "update_project fake is not configured",
        ))
    }
    async fn query_audit_records(
        &self,
        request: Request<QueryAuditRecordsRequest>,
    ) -> Result<Response<QueryAuditRecordsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "query_audit_records fake is not configured",
        ))
    }
    async fn export_audit_records(
        &self,
        request: Request<ExportAuditRecordsRequest>,
    ) -> Result<Response<ExportAuditRecordsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "export_audit_records fake is not configured",
        ))
    }
    async fn get_audit_export(
        &self,
        request: Request<GetAuditExportRequest>,
    ) -> Result<Response<GetAuditExportResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_audit_export fake is not configured",
        ))
    }

    async fn create_workflow_definition(
        &self,
        request: Request<CreateWorkflowDefinitionRequest>,
    ) -> Result<Response<CreateWorkflowDefinitionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "create_workflow_definition fake is not configured",
        ))
    }
    async fn update_workflow_definition(
        &self,
        request: Request<UpdateWorkflowDefinitionRequest>,
    ) -> Result<Response<UpdateWorkflowDefinitionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "update_workflow_definition fake is not configured",
        ))
    }
    async fn get_workflow_definition(
        &self,
        request: Request<GetWorkflowDefinitionRequest>,
    ) -> Result<Response<GetWorkflowDefinitionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_workflow_definition fake is not configured",
        ))
    }
    async fn list_workflow_definitions(
        &self,
        request: Request<ListWorkflowDefinitionsRequest>,
    ) -> Result<Response<ListWorkflowDefinitionsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_workflow_definitions fake is not configured",
        ))
    }
    async fn start_workflow_run(
        &self,
        request: Request<StartWorkflowRunRequest>,
    ) -> Result<Response<StartWorkflowRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "start_workflow_run fake is not configured",
        ))
    }
    async fn get_workflow_run(
        &self,
        request: Request<GetWorkflowRunRequest>,
    ) -> Result<Response<GetWorkflowRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_workflow_run fake is not configured",
        ))
    }
    async fn list_workflow_runs(
        &self,
        request: Request<ListWorkflowRunsRequest>,
    ) -> Result<Response<ListWorkflowRunsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_workflow_runs fake is not configured",
        ))
    }
    async fn cancel_workflow_run(
        &self,
        request: Request<CancelWorkflowRunRequest>,
    ) -> Result<Response<CancelWorkflowRunResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "cancel_workflow_run fake is not configured",
        ))
    }
    async fn commit_workflow_transition(
        &self,
        request: Request<CommitWorkflowTransitionRequest>,
    ) -> Result<Response<CommitWorkflowTransitionResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "commit_workflow_transition fake is not configured",
        ))
    }
    async fn watch_workflow_run(
        &self,
        request: Request<WatchWorkflowRunRequest>,
    ) -> Result<Response<WorkflowStream>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "watch_workflow_run fake is not configured",
        ))
    }
    async fn request_approval(
        &self,
        request: Request<RequestApprovalRequest>,
    ) -> Result<Response<RequestApprovalResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "request_approval fake is not configured",
        ))
    }
    async fn get_approval_request(
        &self,
        request: Request<GetApprovalRequestRequest>,
    ) -> Result<Response<GetApprovalRequestResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "get_approval_request fake is not configured",
        ))
    }
    async fn list_approval_requests(
        &self,
        request: Request<ListApprovalRequestsRequest>,
    ) -> Result<Response<ListApprovalRequestsResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "list_approval_requests fake is not configured",
        ))
    }
    async fn decide_approval(
        &self,
        request: Request<DecideApprovalRequest>,
    ) -> Result<Response<DecideApprovalResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "decide_approval fake is not configured",
        ))
    }
    async fn consume_approval(
        &self,
        request: Request<ConsumeApprovalRequest>,
    ) -> Result<Response<ConsumeApprovalResponse>, Status> {
        let _ = request;
        Err(Status::unimplemented(
            "consume_approval fake is not configured",
        ))
    }
}

/// Payload-free invocation record produced by [`RecordingTransport`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecordedRpcCall {
    pub method: &'static str,
    pub metadata_keys: Vec<String>,
}

/// Generic recording fake seam for every method exposed by [`RpcTransport`].
/// It records only the method and metadata key names, never credentials or
/// serialized generated messages.
pub struct RecordingTransport<T: RpcTransport + ?Sized> {
    inner: Arc<T>,
    calls: Arc<Mutex<Vec<RecordedRpcCall>>>,
}

impl<T: RpcTransport + ?Sized> RecordingTransport<T> {
    #[must_use]
    pub fn new(inner: Arc<T>) -> Self {
        Self {
            inner,
            calls: Arc::new(Mutex::new(Vec::new())),
        }
    }

    #[must_use]
    pub fn calls(&self) -> Vec<RecordedRpcCall> {
        self.calls
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    fn record<Message>(&self, method: &'static str, request: &Request<Message>) {
        let mut metadata_keys = request
            .metadata()
            .keys()
            .map(|key| match key {
                tonic::metadata::KeyRef::Ascii(value) => value.as_str().to_owned(),
                tonic::metadata::KeyRef::Binary(value) => value.as_str().to_owned(),
            })
            .collect::<Vec<_>>();
        metadata_keys.sort_unstable();
        metadata_keys.dedup();
        self.calls
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(RecordedRpcCall {
                method,
                metadata_keys,
            });
    }
}

impl<T: RpcTransport + ?Sized> Clone for RecordingTransport<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
            calls: Arc::clone(&self.calls),
        }
    }
}

macro_rules! record_unary {
    ($method:ident, $request:ty, $response:ty, $route:literal) => {
        fn $method<'life0, 'async_trait>(
            &'life0 self,
            request: Request<$request>,
        ) -> Pin<
            Box<
                dyn std::future::Future<Output = Result<Response<$response>, Status>>
                    + Send
                    + 'async_trait,
            >,
        >
        where
            'life0: 'async_trait,
            Self: 'async_trait,
        {
            Box::pin(async move {
                self.record($route, &request);
                self.inner.$method(request).await
            })
        }
    };
}

#[async_trait]
impl<T: RpcTransport + ?Sized + 'static> RpcTransport for RecordingTransport<T> {
    record_unary!(
        create_agent_definition,
        CreateAgentDefinitionRequest,
        CreateAgentDefinitionResponse,
        "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition"
    );
    record_unary!(
        update_agent_definition,
        UpdateAgentDefinitionRequest,
        UpdateAgentDefinitionResponse,
        "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition"
    );
    record_unary!(
        get_agent_definition,
        GetAgentDefinitionRequest,
        GetAgentDefinitionResponse,
        "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition"
    );
    record_unary!(
        list_agent_definitions,
        ListAgentDefinitionsRequest,
        ListAgentDefinitionsResponse,
        "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions"
    );
    record_unary!(
        start_agent_run,
        StartAgentRunRequest,
        StartAgentRunResponse,
        "/mindclade.internal.agent.v1.AgentService/StartAgentRun"
    );
    record_unary!(
        get_agent_run,
        GetAgentRunRequest,
        GetAgentRunResponse,
        "/mindclade.internal.agent.v1.AgentService/GetAgentRun"
    );
    record_unary!(
        list_agent_runs,
        ListAgentRunsRequest,
        ListAgentRunsResponse,
        "/mindclade.internal.agent.v1.AgentService/ListAgentRuns"
    );
    record_unary!(
        cancel_agent_run,
        CancelAgentRunRequest,
        CancelAgentRunResponse,
        "/mindclade.internal.agent.v1.AgentService/CancelAgentRun"
    );
    record_unary!(
        get_agent_step,
        GetAgentStepRequest,
        GetAgentStepResponse,
        "/mindclade.internal.agent.v1.AgentService/GetAgentStep"
    );
    record_unary!(
        list_agent_steps,
        ListAgentStepsRequest,
        ListAgentStepsResponse,
        "/mindclade.internal.agent.v1.AgentService/ListAgentSteps"
    );
    record_unary!(
        commit_agent_step,
        CommitAgentStepRequest,
        CommitAgentStepResponse,
        "/mindclade.internal.agent.v1.AgentService/CommitAgentStep"
    );
    record_unary!(
        commit_tool_receipt,
        CommitToolReceiptRequest,
        CommitToolReceiptResponse,
        "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt"
    );

    async fn create_training_run(
        &self,
        request: Request<CreateTrainingRunRequest>,
    ) -> Result<Response<CreateTrainingRunResponse>, Status> {
        self.record(
            "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun",
            &request,
        );
        self.inner.create_training_run(request).await
    }

    record_unary!(
        get_training_run,
        GetTrainingRunRequest,
        GetTrainingRunResponse,
        "/mindclade.internal.training.v1.TrainingService/GetTrainingRun"
    );
    record_unary!(
        list_training_runs,
        ListTrainingRunsRequest,
        ListTrainingRunsResponse,
        "/mindclade.internal.training.v1.TrainingService/ListTrainingRuns"
    );
    record_unary!(
        start_training_attempt,
        StartTrainingAttemptRequest,
        StartTrainingAttemptResponse,
        "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt"
    );
    record_unary!(
        resume_training_attempt,
        ResumeTrainingAttemptRequest,
        ResumeTrainingAttemptResponse,
        "/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt"
    );
    record_unary!(
        commit_training_progress,
        CommitTrainingProgressRequest,
        CommitTrainingProgressResponse,
        "/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress"
    );
    record_unary!(
        prepare_checkpoint,
        PrepareCheckpointRequest,
        PrepareCheckpointResponse,
        "/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint"
    );
    record_unary!(
        commit_checkpoint,
        CommitCheckpointRequest,
        CommitCheckpointResponse,
        "/mindclade.internal.training.v1.TrainingService/CommitCheckpoint"
    );
    record_unary!(
        complete_training_run,
        CompleteTrainingRunRequest,
        CompleteTrainingRunResponse,
        "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun"
    );
    record_unary!(
        cancel_training_run,
        CancelTrainingRunRequest,
        CancelTrainingRunResponse,
        "/mindclade.internal.training.v1.TrainingService/CancelTrainingRun"
    );
    record_unary!(
        get_checkpoint,
        GetCheckpointRequest,
        GetCheckpointResponse,
        "/mindclade.internal.training.v1.TrainingService/GetCheckpoint"
    );
    record_unary!(
        list_checkpoints,
        ListCheckpointsRequest,
        ListCheckpointsResponse,
        "/mindclade.internal.training.v1.TrainingService/ListCheckpoints"
    );

    async fn watch_training_run(
        &self,
        request: Request<WatchTrainingRunRequest>,
    ) -> Result<Response<TrainingStream>, Status> {
        self.record(
            "/mindclade.internal.training.v1.TrainingService/WatchTrainingRun",
            &request,
        );
        self.inner.watch_training_run(request).await
    }

    async fn get_operation(
        &self,
        request: Request<GetOperationRequest>,
    ) -> Result<Response<GetOperationResponse>, Status> {
        self.record(
            "/mindclade.internal.job.v1.OperationService/GetOperation",
            &request,
        );
        self.inner.get_operation(request).await
    }

    record_unary!(
        list_operations,
        ListOperationsRequest,
        ListOperationsResponse,
        "/mindclade.internal.job.v1.OperationService/ListOperations"
    );

    async fn cancel_operation(
        &self,
        request: Request<CancelOperationRequest>,
    ) -> Result<Response<CancelOperationResponse>, Status> {
        self.record(
            "/mindclade.internal.job.v1.OperationService/CancelOperation",
            &request,
        );
        self.inner.cancel_operation(request).await
    }

    async fn watch_operation(
        &self,
        request: Request<WatchOperationRequest>,
    ) -> Result<Response<OperationStream>, Status> {
        self.record(
            "/mindclade.internal.job.v1.OperationService/WatchOperation",
            &request,
        );
        self.inner.watch_operation(request).await
    }

    record_unary!(
        request_job,
        RequestJobRequest,
        RequestJobResponse,
        "/mindclade.internal.job.v1.JobService/RequestJob"
    );
    record_unary!(
        get_job,
        GetJobRequest,
        GetJobResponse,
        "/mindclade.internal.job.v1.JobService/GetJob"
    );
    record_unary!(
        list_jobs,
        ListJobsRequest,
        ListJobsResponse,
        "/mindclade.internal.job.v1.JobService/ListJobs"
    );
    record_unary!(
        cancel_job,
        CancelJobRequest,
        CancelJobResponse,
        "/mindclade.internal.job.v1.JobService/CancelJob"
    );
    record_unary!(
        get_run,
        GetRunRequest,
        GetRunResponse,
        "/mindclade.internal.job.v1.RunService/GetRun"
    );
    record_unary!(
        list_runs,
        ListRunsRequest,
        ListRunsResponse,
        "/mindclade.internal.job.v1.RunService/ListRuns"
    );
    record_unary!(
        get_attempt,
        GetAttemptRequest,
        GetAttemptResponse,
        "/mindclade.internal.job.v1.RunService/GetAttempt"
    );
    record_unary!(
        list_attempts,
        ListAttemptsRequest,
        ListAttemptsResponse,
        "/mindclade.internal.job.v1.RunService/ListAttempts"
    );
    record_unary!(
        acquire_attempt_lease,
        AcquireAttemptLeaseRequest,
        AcquireAttemptLeaseResponse,
        "/mindclade.internal.job.v1.RunService/AcquireAttemptLease"
    );
    record_unary!(
        renew_attempt_lease,
        RenewAttemptLeaseRequest,
        RenewAttemptLeaseResponse,
        "/mindclade.internal.job.v1.RunService/RenewAttemptLease"
    );
    record_unary!(
        heartbeat_attempt,
        HeartbeatAttemptRequest,
        HeartbeatAttemptResponse,
        "/mindclade.internal.job.v1.RunService/HeartbeatAttempt"
    );
    record_unary!(
        cancel_attempt,
        CancelAttemptRequest,
        CancelAttemptResponse,
        "/mindclade.internal.job.v1.RunService/CancelAttempt"
    );
    record_unary!(
        commit_attempt,
        CommitAttemptRequest,
        CommitAttemptResponse,
        "/mindclade.internal.job.v1.RunService/CommitAttempt"
    );

    async fn resolve_artifact_alias(
        &self,
        request: Request<ResolveArtifactAliasRequest>,
    ) -> Result<Response<ResolveArtifactAliasResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias",
            &request,
        );
        self.inner.resolve_artifact_alias(request).await
    }

    record_unary!(
        get_artifact,
        GetArtifactRequest,
        GetArtifactResponse,
        "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact"
    );
    record_unary!(
        list_artifacts,
        ListArtifactsRequest,
        ListArtifactsResponse,
        "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts"
    );
    record_unary!(
        quarantine_artifact,
        QuarantineArtifactRequest,
        QuarantineArtifactResponse,
        "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact"
    );
    record_unary!(
        acquire_artifact_lease,
        AcquireArtifactLeaseRequest,
        AcquireArtifactLeaseResponse,
        "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease"
    );
    record_unary!(
        release_artifact_lease,
        ReleaseArtifactLeaseRequest,
        ReleaseArtifactLeaseResponse,
        "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease"
    );

    async fn begin_artifact_upload(
        &self,
        request: Request<BeginArtifactUploadRequest>,
    ) -> Result<Response<BeginArtifactUploadResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/BeginArtifactUpload",
            &request,
        );
        self.inner.begin_artifact_upload(request).await
    }

    async fn upload_artifact_chunk(
        &self,
        request: Request<UploadArtifactChunkRequest>,
    ) -> Result<Response<UploadArtifactChunkResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/UploadArtifactChunk",
            &request,
        );
        self.inner.upload_artifact_chunk(request).await
    }

    async fn get_artifact_upload(
        &self,
        request: Request<GetArtifactUploadRequest>,
    ) -> Result<Response<GetArtifactUploadResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/GetArtifactUpload",
            &request,
        );
        self.inner.get_artifact_upload(request).await
    }

    async fn finalize_artifact_upload(
        &self,
        request: Request<FinalizeArtifactUploadRequest>,
    ) -> Result<Response<FinalizeArtifactUploadResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/FinalizeArtifactUpload",
            &request,
        );
        self.inner.finalize_artifact_upload(request).await
    }

    async fn abort_artifact_upload(
        &self,
        request: Request<AbortArtifactUploadRequest>,
    ) -> Result<Response<AbortArtifactUploadResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/AbortArtifactUpload",
            &request,
        );
        self.inner.abort_artifact_upload(request).await
    }

    async fn quarantine_artifact_upload(
        &self,
        request: Request<QuarantineArtifactUploadRequest>,
    ) -> Result<Response<QuarantineArtifactUploadResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifactUpload",
            &request,
        );
        self.inner.quarantine_artifact_upload(request).await
    }

    async fn commit_artifact(
        &self,
        request: Request<CommitArtifactRequest>,
    ) -> Result<Response<CommitArtifactResponse>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact",
            &request,
        );
        self.inner.commit_artifact(request).await
    }

    async fn download_artifact(
        &self,
        request: Request<DownloadArtifactRequest>,
    ) -> Result<Response<ArtifactStream>, Status> {
        self.record(
            "/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact",
            &request,
        );
        self.inner.download_artifact(request).await
    }

    record_unary!(
        submit_inference,
        SubmitInferenceRequest,
        SubmitInferenceResponse,
        "/mindclade.internal.inference.v1.InferenceService/SubmitInference"
    );
    record_unary!(
        get_inference_request,
        GetInferenceRequestRequest,
        GetInferenceRequestResponse,
        "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest"
    );
    record_unary!(
        get_inference_result,
        GetInferenceResultRequest,
        GetInferenceResultResponse,
        "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult"
    );
    record_unary!(
        commit_inference_result,
        CommitInferenceResultRequest,
        CommitInferenceResultResponse,
        "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult"
    );

    async fn watch_inference(
        &self,
        request: Request<WatchInferenceRequest>,
    ) -> Result<Response<InferenceStream>, Status> {
        self.record(
            "/mindclade.internal.inference.v1.InferenceService/WatchInference",
            &request,
        );
        self.inner.watch_inference(request).await
    }

    record_unary!(
        create_dataset,
        CreateDatasetRequest,
        CreateDatasetResponse,
        "/mindclade.internal.dataset.v1.DatasetService/CreateDataset"
    );
    record_unary!(
        get_dataset,
        GetDatasetRequest,
        GetDatasetResponse,
        "/mindclade.internal.dataset.v1.DatasetService/GetDataset"
    );
    record_unary!(
        list_datasets,
        ListDatasetsRequest,
        ListDatasetsResponse,
        "/mindclade.internal.dataset.v1.DatasetService/ListDatasets"
    );
    record_unary!(
        update_dataset,
        UpdateDatasetRequest,
        UpdateDatasetResponse,
        "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset"
    );
    record_unary!(
        publish_dataset_release,
        PublishDatasetReleaseRequest,
        PublishDatasetReleaseResponse,
        "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease"
    );
    record_unary!(
        revoke_dataset_release,
        RevokeDatasetReleaseRequest,
        RevokeDatasetReleaseResponse,
        "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease"
    );
    record_unary!(
        get_dataset_release,
        GetDatasetReleaseRequest,
        GetDatasetReleaseResponse,
        "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease"
    );
    record_unary!(
        list_dataset_releases,
        ListDatasetReleasesRequest,
        ListDatasetReleasesResponse,
        "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases"
    );
    record_unary!(
        create_evaluation_run,
        CreateEvaluationRunRequest,
        CreateEvaluationRunResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun"
    );
    record_unary!(
        get_evaluation_run,
        GetEvaluationRunRequest,
        GetEvaluationRunResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun"
    );
    record_unary!(
        list_evaluation_runs,
        ListEvaluationRunsRequest,
        ListEvaluationRunsResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns"
    );
    record_unary!(
        cancel_evaluation_run,
        CancelEvaluationRunRequest,
        CancelEvaluationRunResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun"
    );
    record_unary!(
        commit_evaluation_result,
        CommitEvaluationResultRequest,
        CommitEvaluationResultResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult"
    );
    record_unary!(
        get_evaluation_result,
        GetEvaluationResultRequest,
        GetEvaluationResultResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult"
    );
    record_unary!(
        create_promotion_decision,
        CreatePromotionDecisionRequest,
        CreatePromotionDecisionResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision"
    );
    record_unary!(
        get_promotion_decision,
        GetPromotionDecisionRequest,
        GetPromotionDecisionResponse,
        "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision"
    );
    record_unary!(
        create_experiment,
        CreateExperimentRequest,
        CreateExperimentResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment"
    );
    record_unary!(
        get_experiment,
        GetExperimentRequest,
        GetExperimentResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment"
    );
    record_unary!(
        list_experiments,
        ListExperimentsRequest,
        ListExperimentsResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments"
    );
    record_unary!(
        update_experiment,
        UpdateExperimentRequest,
        UpdateExperimentResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment"
    );
    record_unary!(
        transition_experiment,
        TransitionExperimentRequest,
        TransitionExperimentResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment"
    );
    record_unary!(
        create_study,
        CreateStudyRequest,
        CreateStudyResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy"
    );
    record_unary!(
        get_study,
        GetStudyRequest,
        GetStudyResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/GetStudy"
    );
    record_unary!(
        list_studies,
        ListStudiesRequest,
        ListStudiesResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/ListStudies"
    );
    record_unary!(
        transition_study,
        TransitionStudyRequest,
        TransitionStudyResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy"
    );
    record_unary!(
        create_trial,
        CreateTrialRequest,
        CreateTrialResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial"
    );
    record_unary!(
        get_trial,
        GetTrialRequest,
        GetTrialResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/GetTrial"
    );
    record_unary!(
        list_trials,
        ListTrialsRequest,
        ListTrialsResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/ListTrials"
    );
    record_unary!(
        transition_trial,
        TransitionTrialRequest,
        TransitionTrialResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial"
    );
    record_unary!(
        complete_trial,
        CompleteTrialRequest,
        CompleteTrialResponse,
        "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial"
    );
    record_unary!(
        register_model,
        RegisterModelRequest,
        RegisterModelResponse,
        "/mindclade.internal.model.v1.ModelService/RegisterModel"
    );
    record_unary!(
        get_model,
        GetModelRequest,
        GetModelResponse,
        "/mindclade.internal.model.v1.ModelService/GetModel"
    );
    record_unary!(
        list_models,
        ListModelsRequest,
        ListModelsResponse,
        "/mindclade.internal.model.v1.ModelService/ListModels"
    );
    record_unary!(
        register_model_release,
        RegisterModelReleaseRequest,
        RegisterModelReleaseResponse,
        "/mindclade.internal.model.v1.ModelService/RegisterModelRelease"
    );
    record_unary!(
        get_model_release,
        GetModelReleaseRequest,
        GetModelReleaseResponse,
        "/mindclade.internal.model.v1.ModelService/GetModelRelease"
    );
    record_unary!(
        list_model_releases,
        ListModelReleasesRequest,
        ListModelReleasesResponse,
        "/mindclade.internal.model.v1.ModelService/ListModelReleases"
    );
    record_unary!(
        promote_model_release,
        PromoteModelReleaseRequest,
        PromoteModelReleaseResponse,
        "/mindclade.internal.model.v1.ModelService/PromoteModelRelease"
    );
    record_unary!(
        revoke_model_release,
        RevokeModelReleaseRequest,
        RevokeModelReleaseResponse,
        "/mindclade.internal.model.v1.ModelService/RevokeModelRelease"
    );
    record_unary!(
        evaluate_authorization,
        EvaluateAuthorizationRequest,
        EvaluateAuthorizationResponse,
        "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization"
    );
    record_unary!(
        create_use_policy,
        CreateUsePolicyRequest,
        CreateUsePolicyResponse,
        "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy"
    );
    record_unary!(
        update_use_policy,
        UpdateUsePolicyRequest,
        UpdateUsePolicyResponse,
        "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy"
    );
    record_unary!(
        get_use_policy,
        GetUsePolicyRequest,
        GetUsePolicyResponse,
        "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy"
    );
    record_unary!(
        list_use_policies,
        ListUsePoliciesRequest,
        ListUsePoliciesResponse,
        "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies"
    );
    record_unary!(
        activate_use_policy,
        ActivateUsePolicyRequest,
        ActivateUsePolicyResponse,
        "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy"
    );
    record_unary!(
        revoke_use_policy,
        RevokeUsePolicyRequest,
        RevokeUsePolicyResponse,
        "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy"
    );
    record_unary!(
        resolve_policy_snapshot,
        ResolvePolicySnapshotRequest,
        ResolvePolicySnapshotResponse,
        "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot"
    );
    record_unary!(
        get_tenant,
        GetTenantRequest,
        GetTenantResponse,
        "/mindclade.internal.admin.v1.AdminService/GetTenant"
    );
    record_unary!(
        update_tenant,
        UpdateTenantRequest,
        UpdateTenantResponse,
        "/mindclade.internal.admin.v1.AdminService/UpdateTenant"
    );
    record_unary!(
        create_project,
        CreateProjectRequest,
        CreateProjectResponse,
        "/mindclade.internal.admin.v1.AdminService/CreateProject"
    );
    record_unary!(
        get_project,
        GetProjectRequest,
        GetProjectResponse,
        "/mindclade.internal.admin.v1.AdminService/GetProject"
    );
    record_unary!(
        list_projects,
        ListProjectsRequest,
        ListProjectsResponse,
        "/mindclade.internal.admin.v1.AdminService/ListProjects"
    );
    record_unary!(
        update_project,
        UpdateProjectRequest,
        UpdateProjectResponse,
        "/mindclade.internal.admin.v1.AdminService/UpdateProject"
    );
    record_unary!(
        query_audit_records,
        QueryAuditRecordsRequest,
        QueryAuditRecordsResponse,
        "/mindclade.internal.admin.v1.AdminService/QueryAuditRecords"
    );
    record_unary!(
        export_audit_records,
        ExportAuditRecordsRequest,
        ExportAuditRecordsResponse,
        "/mindclade.internal.admin.v1.AdminService/ExportAuditRecords"
    );
    record_unary!(
        get_audit_export,
        GetAuditExportRequest,
        GetAuditExportResponse,
        "/mindclade.internal.admin.v1.AdminService/GetAuditExport"
    );
    record_unary!(
        create_workflow_definition,
        CreateWorkflowDefinitionRequest,
        CreateWorkflowDefinitionResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition"
    );
    record_unary!(
        update_workflow_definition,
        UpdateWorkflowDefinitionRequest,
        UpdateWorkflowDefinitionResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition"
    );
    record_unary!(
        get_workflow_definition,
        GetWorkflowDefinitionRequest,
        GetWorkflowDefinitionResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition"
    );
    record_unary!(
        list_workflow_definitions,
        ListWorkflowDefinitionsRequest,
        ListWorkflowDefinitionsResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions"
    );
    record_unary!(
        start_workflow_run,
        StartWorkflowRunRequest,
        StartWorkflowRunResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun"
    );
    record_unary!(
        get_workflow_run,
        GetWorkflowRunRequest,
        GetWorkflowRunResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun"
    );
    record_unary!(
        list_workflow_runs,
        ListWorkflowRunsRequest,
        ListWorkflowRunsResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns"
    );
    record_unary!(
        cancel_workflow_run,
        CancelWorkflowRunRequest,
        CancelWorkflowRunResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun"
    );
    record_unary!(
        commit_workflow_transition,
        CommitWorkflowTransitionRequest,
        CommitWorkflowTransitionResponse,
        "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition"
    );
    async fn watch_workflow_run(
        &self,
        request: Request<WatchWorkflowRunRequest>,
    ) -> Result<Response<WorkflowStream>, Status> {
        self.record(
            "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun",
            &request,
        );
        self.inner.watch_workflow_run(request).await
    }
    record_unary!(
        request_approval,
        RequestApprovalRequest,
        RequestApprovalResponse,
        "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval"
    );
    record_unary!(
        get_approval_request,
        GetApprovalRequestRequest,
        GetApprovalRequestResponse,
        "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest"
    );
    record_unary!(
        list_approval_requests,
        ListApprovalRequestsRequest,
        ListApprovalRequestsResponse,
        "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests"
    );
    record_unary!(
        decide_approval,
        DecideApprovalRequest,
        DecideApprovalResponse,
        "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval"
    );
    record_unary!(
        consume_approval,
        ConsumeApprovalRequest,
        ConsumeApprovalResponse,
        "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval"
    );
}

/// Production transport backed directly by generated Tonic clients.
#[derive(Clone)]
pub struct TonicTransport {
    channel: Channel,
    agent: AgentServiceClient<Channel>,
    training: TrainingServiceClient<Channel>,
    job: JobServiceClient<Channel>,
    operation: OperationServiceClient<Channel>,
    run: RunServiceClient<Channel>,
    artifact: ArtifactServiceClient<Channel>,
    inference: InferenceServiceClient<Channel>,
    dataset: DatasetServiceClient<Channel>,
    evaluation: EvaluationServiceClient<Channel>,
    experiment: ExperimentServiceClient<Channel>,
    model: ModelServiceClient<Channel>,
    policy: PolicyServiceClient<Channel>,
    admin: AdminServiceClient<Channel>,
    workflow: WorkflowServiceClient<Channel>,
    approval: ApprovalServiceClient<Channel>,
}

impl TonicTransport {
    /// Establishes a channel using TLS roots and hostname verification unless
    /// the configuration explicitly selected Local loopback test transport.
    ///
    /// # Errors
    ///
    /// Returns an error if the endpoint or TLS policy cannot initialize a
    /// channel or the connection cannot be established.
    pub async fn connect(config: &Config) -> Result<Self, Error> {
        let mut endpoint = Endpoint::from_shared(config.endpoint.clone())
            .map_err(|_| Error::configuration("endpoint cannot initialize a gRPC channel"))?
            .connect_timeout(config.connect_timeout)
            .tcp_nodelay(true);

        if !config.insecure_loopback {
            let mut tls = match &config.trust_roots {
                TrustRoots::WebPki => ClientTlsConfig::new().with_webpki_roots(),
                TrustRoots::CustomCa(ca) => {
                    ClientTlsConfig::new().ca_certificate(Certificate::from_pem(Arc::clone(ca)))
                }
            };
            if let Some(server_name) = &config.server_name {
                tls = tls.domain_name(server_name.clone());
            }
            endpoint = endpoint
                .tls_config(tls)
                .map_err(|_| Error::configuration("TLS configuration is invalid"))?;
        }

        let channel = endpoint.connect().await.map_err(|_| Error::transport())?;
        Ok(Self {
            channel: channel.clone(),
            agent: bounded_client!(AgentServiceClient<_>, channel.clone()),
            training: bounded_client!(TrainingServiceClient<_>, channel.clone()),
            job: bounded_client!(JobServiceClient<_>, channel.clone()),
            operation: bounded_client!(OperationServiceClient<_>, channel.clone()),
            run: bounded_client!(RunServiceClient<_>, channel.clone()),
            artifact: bounded_client!(ArtifactServiceClient<_>, channel.clone()),
            inference: bounded_client!(InferenceServiceClient<_>, channel.clone()),
            dataset: bounded_client!(DatasetServiceClient<_>, channel.clone()),
            evaluation: bounded_client!(EvaluationServiceClient<_>, channel.clone()),
            experiment: bounded_client!(ExperimentServiceClient<_>, channel.clone()),
            model: bounded_client!(ModelServiceClient<_>, channel.clone()),
            policy: bounded_client!(PolicyServiceClient<_>, channel.clone()),
            admin: bounded_client!(AdminServiceClient<_>, channel.clone()),
            workflow: bounded_client!(WorkflowServiceClient<_>, channel.clone()),
            approval: bounded_client!(ApprovalServiceClient<_>, channel),
        })
    }

    pub(crate) fn channel(&self) -> Channel {
        self.channel.clone()
    }
}

macro_rules! tonic_unary {
    ($field:ident, $method:ident, $request:ty, $response:ty) => {
        fn $method<'life0, 'async_trait>(
            &'life0 self,
            request: Request<$request>,
        ) -> Pin<
            Box<
                dyn std::future::Future<Output = Result<Response<$response>, Status>>
                    + Send
                    + 'async_trait,
            >,
        >
        where
            'life0: 'async_trait,
            Self: 'async_trait,
        {
            Box::pin(async move { self.$field.clone().$method(request).await })
        }
    };
}

#[async_trait]
impl RpcTransport for TonicTransport {
    tonic_unary!(
        agent,
        create_agent_definition,
        CreateAgentDefinitionRequest,
        CreateAgentDefinitionResponse
    );
    tonic_unary!(
        agent,
        update_agent_definition,
        UpdateAgentDefinitionRequest,
        UpdateAgentDefinitionResponse
    );
    tonic_unary!(
        agent,
        get_agent_definition,
        GetAgentDefinitionRequest,
        GetAgentDefinitionResponse
    );
    tonic_unary!(
        agent,
        list_agent_definitions,
        ListAgentDefinitionsRequest,
        ListAgentDefinitionsResponse
    );
    tonic_unary!(
        agent,
        start_agent_run,
        StartAgentRunRequest,
        StartAgentRunResponse
    );
    tonic_unary!(
        agent,
        get_agent_run,
        GetAgentRunRequest,
        GetAgentRunResponse
    );
    tonic_unary!(
        agent,
        list_agent_runs,
        ListAgentRunsRequest,
        ListAgentRunsResponse
    );
    tonic_unary!(
        agent,
        cancel_agent_run,
        CancelAgentRunRequest,
        CancelAgentRunResponse
    );
    tonic_unary!(
        agent,
        get_agent_step,
        GetAgentStepRequest,
        GetAgentStepResponse
    );
    tonic_unary!(
        agent,
        list_agent_steps,
        ListAgentStepsRequest,
        ListAgentStepsResponse
    );
    tonic_unary!(
        agent,
        commit_agent_step,
        CommitAgentStepRequest,
        CommitAgentStepResponse
    );
    tonic_unary!(
        agent,
        commit_tool_receipt,
        CommitToolReceiptRequest,
        CommitToolReceiptResponse
    );

    async fn create_training_run(
        &self,
        request: Request<CreateTrainingRunRequest>,
    ) -> Result<Response<CreateTrainingRunResponse>, Status> {
        self.training.clone().create_training_run(request).await
    }

    tonic_unary!(
        training,
        get_training_run,
        GetTrainingRunRequest,
        GetTrainingRunResponse
    );
    tonic_unary!(
        training,
        list_training_runs,
        ListTrainingRunsRequest,
        ListTrainingRunsResponse
    );
    tonic_unary!(
        training,
        start_training_attempt,
        StartTrainingAttemptRequest,
        StartTrainingAttemptResponse
    );
    tonic_unary!(
        training,
        resume_training_attempt,
        ResumeTrainingAttemptRequest,
        ResumeTrainingAttemptResponse
    );
    tonic_unary!(
        training,
        commit_training_progress,
        CommitTrainingProgressRequest,
        CommitTrainingProgressResponse
    );
    tonic_unary!(
        training,
        prepare_checkpoint,
        PrepareCheckpointRequest,
        PrepareCheckpointResponse
    );
    tonic_unary!(
        training,
        commit_checkpoint,
        CommitCheckpointRequest,
        CommitCheckpointResponse
    );
    tonic_unary!(
        training,
        complete_training_run,
        CompleteTrainingRunRequest,
        CompleteTrainingRunResponse
    );
    tonic_unary!(
        training,
        cancel_training_run,
        CancelTrainingRunRequest,
        CancelTrainingRunResponse
    );
    tonic_unary!(
        training,
        get_checkpoint,
        GetCheckpointRequest,
        GetCheckpointResponse
    );
    tonic_unary!(
        training,
        list_checkpoints,
        ListCheckpointsRequest,
        ListCheckpointsResponse
    );

    async fn watch_training_run(
        &self,
        request: Request<WatchTrainingRunRequest>,
    ) -> Result<Response<TrainingStream>, Status> {
        let response = self.training.clone().watch_training_run(request).await?;
        let metadata = response.metadata().clone();
        let stream: TrainingStream = Box::pin(response.into_inner());
        let mut wrapped = Response::new(stream);
        *wrapped.metadata_mut() = metadata;
        Ok(wrapped)
    }

    async fn get_operation(
        &self,
        request: Request<GetOperationRequest>,
    ) -> Result<Response<GetOperationResponse>, Status> {
        self.operation.clone().get_operation(request).await
    }

    async fn list_operations(
        &self,
        request: Request<ListOperationsRequest>,
    ) -> Result<Response<ListOperationsResponse>, Status> {
        self.operation.clone().list_operations(request).await
    }

    async fn cancel_operation(
        &self,
        request: Request<CancelOperationRequest>,
    ) -> Result<Response<CancelOperationResponse>, Status> {
        self.operation.clone().cancel_operation(request).await
    }

    async fn watch_operation(
        &self,
        request: Request<WatchOperationRequest>,
    ) -> Result<Response<OperationStream>, Status> {
        let response = self.operation.clone().watch_operation(request).await?;
        let metadata = response.metadata().clone();
        let stream: OperationStream = Box::pin(response.into_inner());
        let mut wrapped = Response::new(stream);
        *wrapped.metadata_mut() = metadata;
        Ok(wrapped)
    }

    tonic_unary!(job, request_job, RequestJobRequest, RequestJobResponse);
    tonic_unary!(job, get_job, GetJobRequest, GetJobResponse);
    tonic_unary!(job, list_jobs, ListJobsRequest, ListJobsResponse);
    tonic_unary!(job, cancel_job, CancelJobRequest, CancelJobResponse);
    tonic_unary!(run, get_run, GetRunRequest, GetRunResponse);
    tonic_unary!(run, list_runs, ListRunsRequest, ListRunsResponse);
    tonic_unary!(run, get_attempt, GetAttemptRequest, GetAttemptResponse);
    tonic_unary!(
        run,
        list_attempts,
        ListAttemptsRequest,
        ListAttemptsResponse
    );
    tonic_unary!(
        run,
        acquire_attempt_lease,
        AcquireAttemptLeaseRequest,
        AcquireAttemptLeaseResponse
    );
    tonic_unary!(
        run,
        renew_attempt_lease,
        RenewAttemptLeaseRequest,
        RenewAttemptLeaseResponse
    );
    tonic_unary!(
        run,
        heartbeat_attempt,
        HeartbeatAttemptRequest,
        HeartbeatAttemptResponse
    );
    tonic_unary!(
        run,
        cancel_attempt,
        CancelAttemptRequest,
        CancelAttemptResponse
    );
    tonic_unary!(
        run,
        commit_attempt,
        CommitAttemptRequest,
        CommitAttemptResponse
    );

    async fn resolve_artifact_alias(
        &self,
        request: Request<ResolveArtifactAliasRequest>,
    ) -> Result<Response<ResolveArtifactAliasResponse>, Status> {
        self.artifact.clone().resolve_artifact_alias(request).await
    }

    async fn get_artifact(
        &self,
        request: Request<GetArtifactRequest>,
    ) -> Result<Response<GetArtifactResponse>, Status> {
        self.artifact.clone().get_artifact(request).await
    }

    async fn list_artifacts(
        &self,
        request: Request<ListArtifactsRequest>,
    ) -> Result<Response<ListArtifactsResponse>, Status> {
        self.artifact.clone().list_artifacts(request).await
    }

    async fn quarantine_artifact(
        &self,
        request: Request<QuarantineArtifactRequest>,
    ) -> Result<Response<QuarantineArtifactResponse>, Status> {
        self.artifact.clone().quarantine_artifact(request).await
    }

    async fn acquire_artifact_lease(
        &self,
        request: Request<AcquireArtifactLeaseRequest>,
    ) -> Result<Response<AcquireArtifactLeaseResponse>, Status> {
        self.artifact.clone().acquire_artifact_lease(request).await
    }

    async fn release_artifact_lease(
        &self,
        request: Request<ReleaseArtifactLeaseRequest>,
    ) -> Result<Response<ReleaseArtifactLeaseResponse>, Status> {
        self.artifact.clone().release_artifact_lease(request).await
    }

    async fn begin_artifact_upload(
        &self,
        request: Request<BeginArtifactUploadRequest>,
    ) -> Result<Response<BeginArtifactUploadResponse>, Status> {
        self.artifact.clone().begin_artifact_upload(request).await
    }

    async fn upload_artifact_chunk(
        &self,
        request: Request<UploadArtifactChunkRequest>,
    ) -> Result<Response<UploadArtifactChunkResponse>, Status> {
        self.artifact.clone().upload_artifact_chunk(request).await
    }

    async fn get_artifact_upload(
        &self,
        request: Request<GetArtifactUploadRequest>,
    ) -> Result<Response<GetArtifactUploadResponse>, Status> {
        self.artifact.clone().get_artifact_upload(request).await
    }

    async fn finalize_artifact_upload(
        &self,
        request: Request<FinalizeArtifactUploadRequest>,
    ) -> Result<Response<FinalizeArtifactUploadResponse>, Status> {
        self.artifact
            .clone()
            .finalize_artifact_upload(request)
            .await
    }

    async fn abort_artifact_upload(
        &self,
        request: Request<AbortArtifactUploadRequest>,
    ) -> Result<Response<AbortArtifactUploadResponse>, Status> {
        self.artifact.clone().abort_artifact_upload(request).await
    }

    async fn quarantine_artifact_upload(
        &self,
        request: Request<QuarantineArtifactUploadRequest>,
    ) -> Result<Response<QuarantineArtifactUploadResponse>, Status> {
        self.artifact
            .clone()
            .quarantine_artifact_upload(request)
            .await
    }

    async fn commit_artifact(
        &self,
        request: Request<CommitArtifactRequest>,
    ) -> Result<Response<CommitArtifactResponse>, Status> {
        self.artifact.clone().commit_artifact(request).await
    }

    async fn download_artifact(
        &self,
        request: Request<DownloadArtifactRequest>,
    ) -> Result<Response<ArtifactStream>, Status> {
        let response = self.artifact.clone().download_artifact(request).await?;
        let metadata = response.metadata().clone();
        let stream: ArtifactStream = Box::pin(response.into_inner());
        let mut wrapped = Response::new(stream);
        *wrapped.metadata_mut() = metadata;
        Ok(wrapped)
    }

    tonic_unary!(
        inference,
        submit_inference,
        SubmitInferenceRequest,
        SubmitInferenceResponse
    );
    tonic_unary!(
        inference,
        get_inference_request,
        GetInferenceRequestRequest,
        GetInferenceRequestResponse
    );
    tonic_unary!(
        inference,
        get_inference_result,
        GetInferenceResultRequest,
        GetInferenceResultResponse
    );
    tonic_unary!(
        inference,
        commit_inference_result,
        CommitInferenceResultRequest,
        CommitInferenceResultResponse
    );

    async fn watch_inference(
        &self,
        request: Request<WatchInferenceRequest>,
    ) -> Result<Response<InferenceStream>, Status> {
        let response = self.inference.clone().watch_inference(request).await?;
        let metadata = response.metadata().clone();
        let stream: InferenceStream = Box::pin(response.into_inner());
        let mut wrapped = Response::new(stream);
        *wrapped.metadata_mut() = metadata;
        Ok(wrapped)
    }

    tonic_unary!(
        dataset,
        create_dataset,
        CreateDatasetRequest,
        CreateDatasetResponse
    );
    tonic_unary!(dataset, get_dataset, GetDatasetRequest, GetDatasetResponse);
    tonic_unary!(
        dataset,
        list_datasets,
        ListDatasetsRequest,
        ListDatasetsResponse
    );
    tonic_unary!(
        dataset,
        update_dataset,
        UpdateDatasetRequest,
        UpdateDatasetResponse
    );
    tonic_unary!(
        dataset,
        publish_dataset_release,
        PublishDatasetReleaseRequest,
        PublishDatasetReleaseResponse
    );
    tonic_unary!(
        dataset,
        revoke_dataset_release,
        RevokeDatasetReleaseRequest,
        RevokeDatasetReleaseResponse
    );
    tonic_unary!(
        dataset,
        get_dataset_release,
        GetDatasetReleaseRequest,
        GetDatasetReleaseResponse
    );
    tonic_unary!(
        dataset,
        list_dataset_releases,
        ListDatasetReleasesRequest,
        ListDatasetReleasesResponse
    );
    tonic_unary!(
        evaluation,
        create_evaluation_run,
        CreateEvaluationRunRequest,
        CreateEvaluationRunResponse
    );
    tonic_unary!(
        evaluation,
        get_evaluation_run,
        GetEvaluationRunRequest,
        GetEvaluationRunResponse
    );
    tonic_unary!(
        evaluation,
        list_evaluation_runs,
        ListEvaluationRunsRequest,
        ListEvaluationRunsResponse
    );
    tonic_unary!(
        evaluation,
        cancel_evaluation_run,
        CancelEvaluationRunRequest,
        CancelEvaluationRunResponse
    );
    tonic_unary!(
        evaluation,
        commit_evaluation_result,
        CommitEvaluationResultRequest,
        CommitEvaluationResultResponse
    );
    tonic_unary!(
        evaluation,
        get_evaluation_result,
        GetEvaluationResultRequest,
        GetEvaluationResultResponse
    );
    tonic_unary!(
        evaluation,
        create_promotion_decision,
        CreatePromotionDecisionRequest,
        CreatePromotionDecisionResponse
    );
    tonic_unary!(
        evaluation,
        get_promotion_decision,
        GetPromotionDecisionRequest,
        GetPromotionDecisionResponse
    );
    tonic_unary!(
        experiment,
        create_experiment,
        CreateExperimentRequest,
        CreateExperimentResponse
    );
    tonic_unary!(
        experiment,
        get_experiment,
        GetExperimentRequest,
        GetExperimentResponse
    );
    tonic_unary!(
        experiment,
        list_experiments,
        ListExperimentsRequest,
        ListExperimentsResponse
    );
    tonic_unary!(
        experiment,
        update_experiment,
        UpdateExperimentRequest,
        UpdateExperimentResponse
    );
    tonic_unary!(
        experiment,
        transition_experiment,
        TransitionExperimentRequest,
        TransitionExperimentResponse
    );
    tonic_unary!(
        experiment,
        create_study,
        CreateStudyRequest,
        CreateStudyResponse
    );
    tonic_unary!(experiment, get_study, GetStudyRequest, GetStudyResponse);
    tonic_unary!(
        experiment,
        list_studies,
        ListStudiesRequest,
        ListStudiesResponse
    );
    tonic_unary!(
        experiment,
        transition_study,
        TransitionStudyRequest,
        TransitionStudyResponse
    );
    tonic_unary!(
        experiment,
        create_trial,
        CreateTrialRequest,
        CreateTrialResponse
    );
    tonic_unary!(experiment, get_trial, GetTrialRequest, GetTrialResponse);
    tonic_unary!(
        experiment,
        list_trials,
        ListTrialsRequest,
        ListTrialsResponse
    );
    tonic_unary!(
        experiment,
        transition_trial,
        TransitionTrialRequest,
        TransitionTrialResponse
    );
    tonic_unary!(
        experiment,
        complete_trial,
        CompleteTrialRequest,
        CompleteTrialResponse
    );
    tonic_unary!(
        model,
        register_model,
        RegisterModelRequest,
        RegisterModelResponse
    );
    tonic_unary!(model, get_model, GetModelRequest, GetModelResponse);
    tonic_unary!(model, list_models, ListModelsRequest, ListModelsResponse);
    tonic_unary!(
        model,
        register_model_release,
        RegisterModelReleaseRequest,
        RegisterModelReleaseResponse
    );
    tonic_unary!(
        model,
        get_model_release,
        GetModelReleaseRequest,
        GetModelReleaseResponse
    );
    tonic_unary!(
        model,
        list_model_releases,
        ListModelReleasesRequest,
        ListModelReleasesResponse
    );
    tonic_unary!(
        model,
        promote_model_release,
        PromoteModelReleaseRequest,
        PromoteModelReleaseResponse
    );
    tonic_unary!(
        model,
        revoke_model_release,
        RevokeModelReleaseRequest,
        RevokeModelReleaseResponse
    );
    tonic_unary!(
        policy,
        evaluate_authorization,
        EvaluateAuthorizationRequest,
        EvaluateAuthorizationResponse
    );
    tonic_unary!(
        policy,
        create_use_policy,
        CreateUsePolicyRequest,
        CreateUsePolicyResponse
    );
    tonic_unary!(
        policy,
        update_use_policy,
        UpdateUsePolicyRequest,
        UpdateUsePolicyResponse
    );
    tonic_unary!(
        policy,
        get_use_policy,
        GetUsePolicyRequest,
        GetUsePolicyResponse
    );
    tonic_unary!(
        policy,
        list_use_policies,
        ListUsePoliciesRequest,
        ListUsePoliciesResponse
    );
    tonic_unary!(
        policy,
        activate_use_policy,
        ActivateUsePolicyRequest,
        ActivateUsePolicyResponse
    );
    tonic_unary!(
        policy,
        revoke_use_policy,
        RevokeUsePolicyRequest,
        RevokeUsePolicyResponse
    );
    tonic_unary!(
        policy,
        resolve_policy_snapshot,
        ResolvePolicySnapshotRequest,
        ResolvePolicySnapshotResponse
    );
    tonic_unary!(admin, get_tenant, GetTenantRequest, GetTenantResponse);
    tonic_unary!(
        admin,
        update_tenant,
        UpdateTenantRequest,
        UpdateTenantResponse
    );
    tonic_unary!(
        admin,
        create_project,
        CreateProjectRequest,
        CreateProjectResponse
    );
    tonic_unary!(admin, get_project, GetProjectRequest, GetProjectResponse);
    tonic_unary!(
        admin,
        list_projects,
        ListProjectsRequest,
        ListProjectsResponse
    );
    tonic_unary!(
        admin,
        update_project,
        UpdateProjectRequest,
        UpdateProjectResponse
    );
    tonic_unary!(
        admin,
        query_audit_records,
        QueryAuditRecordsRequest,
        QueryAuditRecordsResponse
    );
    tonic_unary!(
        admin,
        export_audit_records,
        ExportAuditRecordsRequest,
        ExportAuditRecordsResponse
    );
    tonic_unary!(
        admin,
        get_audit_export,
        GetAuditExportRequest,
        GetAuditExportResponse
    );
    tonic_unary!(
        workflow,
        create_workflow_definition,
        CreateWorkflowDefinitionRequest,
        CreateWorkflowDefinitionResponse
    );
    tonic_unary!(
        workflow,
        update_workflow_definition,
        UpdateWorkflowDefinitionRequest,
        UpdateWorkflowDefinitionResponse
    );
    tonic_unary!(
        workflow,
        get_workflow_definition,
        GetWorkflowDefinitionRequest,
        GetWorkflowDefinitionResponse
    );
    tonic_unary!(
        workflow,
        list_workflow_definitions,
        ListWorkflowDefinitionsRequest,
        ListWorkflowDefinitionsResponse
    );
    tonic_unary!(
        workflow,
        start_workflow_run,
        StartWorkflowRunRequest,
        StartWorkflowRunResponse
    );
    tonic_unary!(
        workflow,
        get_workflow_run,
        GetWorkflowRunRequest,
        GetWorkflowRunResponse
    );
    tonic_unary!(
        workflow,
        list_workflow_runs,
        ListWorkflowRunsRequest,
        ListWorkflowRunsResponse
    );
    tonic_unary!(
        workflow,
        cancel_workflow_run,
        CancelWorkflowRunRequest,
        CancelWorkflowRunResponse
    );
    tonic_unary!(
        workflow,
        commit_workflow_transition,
        CommitWorkflowTransitionRequest,
        CommitWorkflowTransitionResponse
    );
    async fn watch_workflow_run(
        &self,
        request: Request<WatchWorkflowRunRequest>,
    ) -> Result<Response<WorkflowStream>, Status> {
        let response = self.workflow.clone().watch_workflow_run(request).await?;
        let metadata = response.metadata().clone();
        let stream: WorkflowStream = Box::pin(response.into_inner());
        let mut wrapped = Response::new(stream);
        *wrapped.metadata_mut() = metadata;
        Ok(wrapped)
    }
    tonic_unary!(
        approval,
        request_approval,
        RequestApprovalRequest,
        RequestApprovalResponse
    );
    tonic_unary!(
        approval,
        get_approval_request,
        GetApprovalRequestRequest,
        GetApprovalRequestResponse
    );
    tonic_unary!(
        approval,
        list_approval_requests,
        ListApprovalRequestsRequest,
        ListApprovalRequestsResponse
    );
    tonic_unary!(
        approval,
        decide_approval,
        DecideApprovalRequest,
        DecideApprovalResponse
    );
    tonic_unary!(
        approval,
        consume_approval,
        ConsumeApprovalRequest,
        ConsumeApprovalResponse
    );
}

#[cfg(test)]
mod message_size_tests {
    use std::time::Duration;

    use super::*;
    use mindclade_protocols::{
        internal::job::v1::operation_service_server::{OperationService, OperationServiceServer},
        operation::v1::Operation,
    };
    use tonic::codegen::tokio_stream;
    use tonic::transport::Server;

    struct LargeOperationService;

    #[async_trait]
    impl OperationService for LargeOperationService {
        async fn get_operation(
            &self,
            _request: Request<GetOperationRequest>,
        ) -> Result<Response<GetOperationResponse>, Status> {
            Ok(Response::new(GetOperationResponse {
                operation: Some(Operation {
                    operation_id: "x".repeat((4 << 20) + 1_024),
                    ..Operation::default()
                }),
            }))
        }

        async fn list_operations(
            &self,
            _request: Request<ListOperationsRequest>,
        ) -> Result<Response<ListOperationsResponse>, Status> {
            Ok(Response::new(ListOperationsResponse::default()))
        }

        async fn cancel_operation(
            &self,
            _request: Request<CancelOperationRequest>,
        ) -> Result<Response<CancelOperationResponse>, Status> {
            Ok(Response::new(CancelOperationResponse::default()))
        }

        type WatchOperationStream = OperationStream;

        async fn watch_operation(
            &self,
            _request: Request<WatchOperationRequest>,
        ) -> Result<Response<Self::WatchOperationStream>, Status> {
            tokio::time::sleep(Duration::from_millis(60)).await;
            Ok(Response::new(Box::pin(tokio_stream::iter([Ok(
                WatchOperationResponse {
                    operation: Some(Operation {
                        operation_id: "operations/quiet".to_owned(),
                        done: true,
                        ..Operation::default()
                    }),
                    sequence: 1,
                    observed_at: None,
                },
            )]))))
        }
    }

    #[tokio::test]
    async fn configured_client_decodes_a_valid_above_default_wire_message() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let incoming = tokio_stream::wrappers::TcpListenerStream::new(listener);
        let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            Server::builder()
                .add_service(
                    OperationServiceServer::new(LargeOperationService)
                        .max_encoding_message_size(MAX_WIRE_MESSAGE_BYTES),
                )
                .serve_with_incoming_shutdown(incoming, async {
                    let _ = shutdown_receiver.await;
                })
                .await
                .unwrap();
        });
        let channel = Endpoint::from_shared(format!("http://{address}"))
            .unwrap()
            .connect()
            .await
            .unwrap();
        let mut client = bounded_client!(OperationServiceClient<_>, channel);
        let response = client
            .get_operation(GetOperationRequest::default())
            .await
            .unwrap()
            .into_inner();
        assert!(response.operation.unwrap().operation_id.len() > 4 << 20);
        let _ = shutdown_sender.send(());
        server.await.unwrap();
    }

    #[tokio::test]
    async fn ergonomic_watch_preserves_total_deadline_beyond_rpc_default() {
        use tonic::codegen::tokio_stream::StreamExt;

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let incoming = tokio_stream::wrappers::TcpListenerStream::new(listener);
        let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            Server::builder()
                .add_service(OperationServiceServer::new(LargeOperationService))
                .serve_with_incoming_shutdown(incoming, async {
                    let _ = shutdown_receiver.await;
                })
                .await
                .unwrap();
        });
        let identity = crate::Identity::new("tenant", "project", "principal").unwrap();
        let config = crate::Config::local_insecure_builder(identity)
            .endpoint(format!("http://{address}"))
            .default_rpc_timeout(Duration::from_millis(20))
            .build()
            .unwrap();
        let transport = TonicTransport::connect(&config).await.unwrap();
        let mut request = Request::new(WatchOperationRequest {
            name: "operations/quiet".to_owned(),
            ..WatchOperationRequest::default()
        });
        request.set_timeout(Duration::from_millis(250));
        let response = transport.watch_operation(request).await.unwrap();
        let update = response.into_inner().next().await.unwrap().unwrap();
        assert_eq!(update.operation.unwrap().operation_id, "operations/quiet");
        let _ = shutdown_sender.send(());
        server.await.unwrap();
    }
}

#[cfg(test)]
mod generated_client_policy_tests {
    use std::time::{Duration, SystemTime};

    use tonic::{Request, metadata::MetadataValue, service::Interceptor};

    use super::{
        GeneratedClientInterceptor, metadata_value, parse_grpc_timeout, sensitive_authorization,
    };

    fn interceptor(expires_at: SystemTime) -> GeneratedClientInterceptor {
        GeneratedClientInterceptor {
            authorization: Some(sensitive_authorization("Bearer short-lived-test-token").unwrap()),
            expires_at: Some(expires_at),
            tenant_id: metadata_value("tenant-01").unwrap(),
            project_id: metadata_value("project-01").unwrap(),
            principal_id: metadata_value("worker-01").unwrap(),
            timeout: Duration::from_secs(20),
        }
    }

    #[test]
    fn raw_generated_clients_enforce_auth_scope_trace_and_deadline() {
        let mut policy = interceptor(SystemTime::now() + Duration::from_mins(5));
        let request = policy.call(Request::new(())).unwrap();
        let metadata = request.metadata();
        let authorization = metadata.get("authorization").unwrap();
        assert!(authorization.is_sensitive());
        assert_eq!(
            metadata.get("x-mindclade-expected-tenant").unwrap(),
            "tenant-01"
        );
        assert_eq!(
            metadata.get("x-mindclade-expected-project").unwrap(),
            "project-01"
        );
        assert_eq!(
            metadata.get("x-mindclade-expected-principal").unwrap(),
            "worker-01"
        );
        assert!(metadata.get("x-request-id").is_some());
        assert!(metadata.get("x-trace-id").is_some());
        assert!(metadata.get("grpc-timeout").is_some());
    }

    #[test]
    fn raw_generated_clients_fail_closed_inside_refresh_window() {
        let mut policy = interceptor(SystemTime::now() + Duration::from_secs(10));
        let error = policy.call(Request::new(())).unwrap_err();
        assert_eq!(error.code(), tonic::Code::Unauthenticated);
    }

    #[test]
    fn local_generated_clients_omit_authorization() {
        let mut policy = GeneratedClientInterceptor {
            authorization: None,
            expires_at: None,
            tenant_id: metadata_value("tenant-01").unwrap(),
            project_id: metadata_value("project-01").unwrap(),
            principal_id: metadata_value("worker-01").unwrap(),
            timeout: Duration::from_secs(20),
        };
        let mut request = Request::new(());
        request.metadata_mut().insert(
            "authorization",
            sensitive_authorization("Bearer caller-controlled").unwrap(),
        );
        request.metadata_mut().insert(
            "proxy-authorization",
            metadata_value("Basic-caller-controlled").unwrap(),
        );
        request.metadata_mut().insert(
            "cookie",
            metadata_value("session=caller-controlled").unwrap(),
        );
        request
            .metadata_mut()
            .insert("x-api-key", metadata_value("caller-controlled").unwrap());
        let request = policy.call(request).unwrap();
        for key in [
            "authorization",
            "proxy-authorization",
            "cookie",
            "x-api-key",
        ] {
            assert!(request.metadata().get(key).is_none(), "{key} survived");
        }
    }

    #[test]
    fn raw_generated_clients_reject_unbounded_correlation_metadata() {
        let mut policy = interceptor(SystemTime::now() + Duration::from_mins(5));
        let mut request = Request::new(());
        request.metadata_mut().insert(
            "x-request-id",
            MetadataValue::try_from("r".repeat(513)).unwrap(),
        );
        assert_eq!(
            policy.call(request).unwrap_err().code(),
            tonic::Code::InvalidArgument
        );

        let mut request = Request::new(());
        request.metadata_mut().insert(
            "x-trace-id",
            MetadataValue::try_from("t".repeat(513)).unwrap(),
        );
        assert_eq!(
            policy.call(request).unwrap_err().code(),
            tonic::Code::InvalidArgument
        );
    }

    #[test]
    fn raw_generated_clients_preserve_correlation_and_bound_caller_deadline() {
        let mut policy = interceptor(SystemTime::now() + Duration::from_mins(5));
        let mut request = Request::new(());
        request
            .metadata_mut()
            .insert("x-request-id", metadata_value("request-fixed").unwrap());
        request
            .metadata_mut()
            .insert("x-trace-id", metadata_value("trace-fixed").unwrap());
        request.set_timeout(Duration::from_mins(5));
        let request = policy.call(request).unwrap();
        assert_eq!(
            request.metadata().get("x-request-id").unwrap(),
            "request-fixed"
        );
        assert_eq!(request.metadata().get("x-trace-id").unwrap(), "trace-fixed");
        let timeout = parse_grpc_timeout(request.metadata().get("grpc-timeout").unwrap()).unwrap();
        assert!(timeout <= Duration::from_secs(20));
    }
}
