"""Injectable generated-gRPC transport adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any, Protocol

import grpc
from google.protobuf.message import Message
from mindclade.internal.admin.v1 import admin_service_pb2, admin_service_pb2_grpc
from mindclade.internal.agent.v1 import agent_service_pb2, agent_service_pb2_grpc
from mindclade.internal.artifact.v1 import artifact_service_pb2, artifact_service_pb2_grpc
from mindclade.internal.dataset.v1 import dataset_service_pb2, dataset_service_pb2_grpc
from mindclade.internal.evaluation.v1 import evaluation_service_pb2, evaluation_service_pb2_grpc
from mindclade.internal.experiment.v1 import experiment_service_pb2, experiment_service_pb2_grpc
from mindclade.internal.inference.v1 import inference_service_pb2, inference_service_pb2_grpc
from mindclade.internal.job.v1 import job_service_pb2, job_service_pb2_grpc
from mindclade.internal.model.v1 import model_service_pb2, model_service_pb2_grpc
from mindclade.internal.policy.v1 import policy_service_pb2, policy_service_pb2_grpc
from mindclade.internal.training.v1 import training_service_pb2, training_service_pb2_grpc
from mindclade.internal.workflow.v1 import workflow_service_pb2, workflow_service_pb2_grpc

from .config import ClientConfig

Metadata = tuple[tuple[str, str | bytes], ...]
_MAX_WIRE_MESSAGE_BYTES = 8 << 20

GET_OPERATION = "/mindclade.internal.job.v1.OperationService/GetOperation"
LIST_OPERATIONS = "/mindclade.internal.job.v1.OperationService/ListOperations"
CANCEL_OPERATION = "/mindclade.internal.job.v1.OperationService/CancelOperation"
WATCH_OPERATION = "/mindclade.internal.job.v1.OperationService/WatchOperation"
REQUEST_JOB = "/mindclade.internal.job.v1.JobService/RequestJob"
GET_JOB = "/mindclade.internal.job.v1.JobService/GetJob"
LIST_JOBS = "/mindclade.internal.job.v1.JobService/ListJobs"
CANCEL_JOB = "/mindclade.internal.job.v1.JobService/CancelJob"
GET_RUN = "/mindclade.internal.job.v1.RunService/GetRun"
LIST_RUNS = "/mindclade.internal.job.v1.RunService/ListRuns"
GET_ATTEMPT = "/mindclade.internal.job.v1.RunService/GetAttempt"
LIST_ATTEMPTS = "/mindclade.internal.job.v1.RunService/ListAttempts"
ACQUIRE_ATTEMPT_LEASE = "/mindclade.internal.job.v1.RunService/AcquireAttemptLease"
RENEW_ATTEMPT_LEASE = "/mindclade.internal.job.v1.RunService/RenewAttemptLease"
HEARTBEAT_ATTEMPT = "/mindclade.internal.job.v1.RunService/HeartbeatAttempt"
CANCEL_ATTEMPT = "/mindclade.internal.job.v1.RunService/CancelAttempt"
COMMIT_ATTEMPT = "/mindclade.internal.job.v1.RunService/CommitAttempt"
EXPIRE_ATTEMPT_LEASES = "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases"
GET_ARTIFACT = "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact"
LIST_ARTIFACTS = "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts"
QUARANTINE_ARTIFACT = "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact"
ACQUIRE_ARTIFACT_LEASE = "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease"
RELEASE_ARTIFACT_LEASE = "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease"
RESOLVE_ARTIFACT_ALIAS = "/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias"
BEGIN_ARTIFACT_UPLOAD = "/mindclade.internal.artifact.v1.ArtifactService/BeginArtifactUpload"
UPLOAD_ARTIFACT_CHUNK = "/mindclade.internal.artifact.v1.ArtifactService/UploadArtifactChunk"
GET_ARTIFACT_UPLOAD = "/mindclade.internal.artifact.v1.ArtifactService/GetArtifactUpload"
FINALIZE_ARTIFACT_UPLOAD = "/mindclade.internal.artifact.v1.ArtifactService/FinalizeArtifactUpload"
ABORT_ARTIFACT_UPLOAD = "/mindclade.internal.artifact.v1.ArtifactService/AbortArtifactUpload"
QUARANTINE_ARTIFACT_UPLOAD = (
    "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifactUpload"
)
DOWNLOAD_ARTIFACT = "/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact"
COMMIT_ARTIFACT = "/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact"
CREATE_TRAINING_RUN = "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun"
GET_TRAINING_RUN = "/mindclade.internal.training.v1.TrainingService/GetTrainingRun"
LIST_TRAINING_RUNS = "/mindclade.internal.training.v1.TrainingService/ListTrainingRuns"
START_TRAINING_ATTEMPT = "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt"
RESUME_TRAINING_ATTEMPT = "/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt"
COMMIT_TRAINING_PROGRESS = "/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress"
PREPARE_CHECKPOINT = "/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint"
COMMIT_CHECKPOINT = "/mindclade.internal.training.v1.TrainingService/CommitCheckpoint"
COMPLETE_TRAINING_RUN = "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun"
CANCEL_TRAINING_RUN = "/mindclade.internal.training.v1.TrainingService/CancelTrainingRun"
GET_CHECKPOINT = "/mindclade.internal.training.v1.TrainingService/GetCheckpoint"
LIST_CHECKPOINTS = "/mindclade.internal.training.v1.TrainingService/ListCheckpoints"
WATCH_TRAINING_RUN = "/mindclade.internal.training.v1.TrainingService/WatchTrainingRun"
CREATE_DATASET = "/mindclade.internal.dataset.v1.DatasetService/CreateDataset"
GET_DATASET = "/mindclade.internal.dataset.v1.DatasetService/GetDataset"
LIST_DATASETS = "/mindclade.internal.dataset.v1.DatasetService/ListDatasets"
UPDATE_DATASET = "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset"
PUBLISH_DATASET_RELEASE = "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease"
REVOKE_DATASET_RELEASE = "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease"
GET_DATASET_RELEASE = "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease"
LIST_DATASET_RELEASES = "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases"
REGISTER_MODEL = "/mindclade.internal.model.v1.ModelService/RegisterModel"
GET_MODEL = "/mindclade.internal.model.v1.ModelService/GetModel"
LIST_MODELS = "/mindclade.internal.model.v1.ModelService/ListModels"
REGISTER_MODEL_RELEASE = "/mindclade.internal.model.v1.ModelService/RegisterModelRelease"
GET_MODEL_RELEASE = "/mindclade.internal.model.v1.ModelService/GetModelRelease"
LIST_MODEL_RELEASES = "/mindclade.internal.model.v1.ModelService/ListModelReleases"
PROMOTE_MODEL_RELEASE = "/mindclade.internal.model.v1.ModelService/PromoteModelRelease"
REVOKE_MODEL_RELEASE = "/mindclade.internal.model.v1.ModelService/RevokeModelRelease"
SUBMIT_INFERENCE = "/mindclade.internal.inference.v1.InferenceService/SubmitInference"
GET_INFERENCE_REQUEST = "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest"
GET_INFERENCE_RESULT = "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult"
COMMIT_INFERENCE_RESULT = "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult"
WATCH_INFERENCE = "/mindclade.internal.inference.v1.InferenceService/WatchInference"
CREATE_EVALUATION_RUN = "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun"
GET_EVALUATION_RUN = "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun"
LIST_EVALUATION_RUNS = "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns"
CANCEL_EVALUATION_RUN = "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun"
COMMIT_EVALUATION_RESULT = (
    "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult"
)
GET_EVALUATION_RESULT = "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult"
CREATE_PROMOTION_DECISION = (
    "/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision"
)
GET_PROMOTION_DECISION = "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision"
CREATE_EXPERIMENT = "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment"
GET_EXPERIMENT = "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment"
LIST_EXPERIMENTS = "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments"
UPDATE_EXPERIMENT = "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment"
TRANSITION_EXPERIMENT = "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment"
CREATE_STUDY = "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy"
GET_STUDY = "/mindclade.internal.experiment.v1.ExperimentService/GetStudy"
LIST_STUDIES = "/mindclade.internal.experiment.v1.ExperimentService/ListStudies"
TRANSITION_STUDY = "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy"
CREATE_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial"
GET_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/GetTrial"
LIST_TRIALS = "/mindclade.internal.experiment.v1.ExperimentService/ListTrials"
TRANSITION_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial"
COMPLETE_TRIAL = "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial"
EVALUATE_AUTHORIZATION = "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization"
CREATE_USE_POLICY = "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy"
UPDATE_USE_POLICY = "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy"
GET_USE_POLICY = "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy"
LIST_USE_POLICIES = "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies"
ACTIVATE_USE_POLICY = "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy"
REVOKE_USE_POLICY = "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy"
RESOLVE_POLICY_SNAPSHOT = "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot"
GET_TENANT = "/mindclade.internal.admin.v1.AdminService/GetTenant"
UPDATE_TENANT = "/mindclade.internal.admin.v1.AdminService/UpdateTenant"
CREATE_PROJECT = "/mindclade.internal.admin.v1.AdminService/CreateProject"
GET_PROJECT = "/mindclade.internal.admin.v1.AdminService/GetProject"
LIST_PROJECTS = "/mindclade.internal.admin.v1.AdminService/ListProjects"
UPDATE_PROJECT = "/mindclade.internal.admin.v1.AdminService/UpdateProject"
QUERY_AUDIT_RECORDS = "/mindclade.internal.admin.v1.AdminService/QueryAuditRecords"
EXPORT_AUDIT_RECORDS = "/mindclade.internal.admin.v1.AdminService/ExportAuditRecords"
GET_AUDIT_EXPORT = "/mindclade.internal.admin.v1.AdminService/GetAuditExport"
CREATE_WORKFLOW_DEFINITION = (
    "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition"
)
UPDATE_WORKFLOW_DEFINITION = (
    "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition"
)
GET_WORKFLOW_DEFINITION = "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition"
LIST_WORKFLOW_DEFINITIONS = (
    "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions"
)
START_WORKFLOW_RUN = "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun"
GET_WORKFLOW_RUN = "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun"
LIST_WORKFLOW_RUNS = "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns"
CANCEL_WORKFLOW_RUN = "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun"
COMMIT_WORKFLOW_TRANSITION = (
    "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition"
)
WATCH_WORKFLOW_RUN = "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun"
REQUEST_APPROVAL = "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval"
GET_APPROVAL_REQUEST = "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest"
LIST_APPROVAL_REQUESTS = "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests"
DECIDE_APPROVAL = "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval"
CONSUME_APPROVAL = "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval"

_SERVICE_MODULES: tuple[tuple[Any, Any], ...] = (
    (admin_service_pb2, admin_service_pb2_grpc),
    (agent_service_pb2, agent_service_pb2_grpc),
    (artifact_service_pb2, artifact_service_pb2_grpc),
    (dataset_service_pb2, dataset_service_pb2_grpc),
    (evaluation_service_pb2, evaluation_service_pb2_grpc),
    (experiment_service_pb2, experiment_service_pb2_grpc),
    (inference_service_pb2, inference_service_pb2_grpc),
    (job_service_pb2, job_service_pb2_grpc),
    (model_service_pb2, model_service_pb2_grpc),
    (policy_service_pb2, policy_service_pb2_grpc),
    (training_service_pb2, training_service_pb2_grpc),
    (workflow_service_pb2, workflow_service_pb2_grpc),
)


def _bind_generated_services(channel: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind every declared unary-request internal RPC to its generated stub."""

    unary: dict[str, Any] = {}
    streams: dict[str, Any] = {}
    for descriptor_module, grpc_module in _SERVICE_MODULES:
        for service in descriptor_module.DESCRIPTOR.services_by_name.values():
            stub_type = getattr(grpc_module, f"{service.name}Stub")
            stub = stub_type(channel)
            for method in service.methods:
                if method.client_streaming:
                    detail = "internal SDK does not permit ungoverned client streaming"
                    raise RuntimeError(f"{detail}: {method.full_name}")
                route = f"/{service.full_name}/{method.name}"
                target = streams if method.server_streaming else unary
                if route in target:
                    raise RuntimeError(f"duplicate generated RPC route: {route}")
                target[route] = getattr(stub, method.name)
    return unary, streams


def _declared_routes() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    unary: set[str] = set()
    streams: set[str] = set()
    services: set[str] = set()
    for descriptor_module, _ in _SERVICE_MODULES:
        for service in descriptor_module.DESCRIPTOR.services_by_name.values():
            services.add(service.full_name)
            for method in service.methods:
                route = f"/{service.full_name}/{method.name}"
                (streams if method.server_streaming else unary).add(route)
    return frozenset(unary), frozenset(streams), frozenset(services)


INTERNAL_UNARY_METHODS, INTERNAL_STREAM_METHODS, INTERNAL_SERVICE_NAMES = _declared_routes()


class SyncTransport(Protocol):
    def unary_unary(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Message: ...

    def unary_unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> tuple[Message, Metadata]: ...

    def unary_stream(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Iterator[Message]: ...

    def close(self) -> None: ...


class AsyncTransport(Protocol):
    async def unary_unary(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Message: ...

    async def unary_unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> tuple[Message, Metadata]: ...

    def unary_stream(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> AsyncIterator[Message]: ...

    async def close(self) -> None: ...


def _channel_options(config: ClientConfig) -> tuple[tuple[str, str | int], ...]:
    options: list[tuple[str, str | int]] = [
        ("grpc.primary_user_agent", config.user_agent),
        ("grpc.max_receive_message_length", _MAX_WIRE_MESSAGE_BYTES),
        ("grpc.max_send_message_length", _MAX_WIRE_MESSAGE_BYTES),
    ]
    if config.tls_server_name:
        options.append(("grpc.ssl_target_name_override", config.tls_server_name))
    return tuple(options)


def _credentials(config: ClientConfig) -> grpc.ChannelCredentials:
    return grpc.ssl_channel_credentials(root_certificates=config.root_certificates)


class GrpcSyncTransport:
    """Synchronous adapter over generated service stubs."""

    def __init__(self, config: ClientConfig) -> None:
        if config.insecure_for_testing:
            channel = grpc.insecure_channel(
                config.resolved_endpoint, options=_channel_options(config)
            )
        else:
            channel = grpc.secure_channel(
                config.resolved_endpoint,
                _credentials(config),
                options=_channel_options(config),
            )
        self._channel = channel
        self._unary, self._streams = _bind_generated_services(channel)

    def unary_unary(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Message:
        return self._unary[method](request, timeout=timeout, metadata=metadata)

    def unary_unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> tuple[Message, Metadata]:
        response, call = self._unary[method].with_call(request, timeout=timeout, metadata=metadata)
        return response, _metadata(call.initial_metadata())

    def unary_stream(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Iterator[Message]:
        call = self._streams[method](request, timeout=timeout, metadata=metadata)
        try:
            yield from call
        finally:
            call.cancel()

    def close(self) -> None:
        self._channel.close()


class GrpcAsyncTransport:
    """Asyncio adapter over the same generated service stubs."""

    def __init__(self, config: ClientConfig) -> None:
        if config.insecure_for_testing:
            channel = grpc.aio.insecure_channel(
                config.resolved_endpoint, options=_channel_options(config)
            )
        else:
            channel = grpc.aio.secure_channel(
                config.resolved_endpoint,
                _credentials(config),
                options=_channel_options(config),
            )
        self._channel = channel
        self._unary, self._streams = _bind_generated_services(channel)

    async def unary_unary(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> Message:
        return await self._unary[method](request, timeout=timeout, metadata=metadata)

    async def unary_unary_with_metadata(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> tuple[Message, Metadata]:
        call = self._unary[method](request, timeout=timeout, metadata=metadata)
        response = await call
        return response, _metadata(await call.initial_metadata())

    async def unary_stream(
        self,
        method: str,
        request: Message,
        *,
        timeout: float,
        metadata: Metadata,
    ) -> AsyncIterator[Message]:
        call = self._streams[method](request, timeout=timeout, metadata=metadata)
        try:
            async for item in call:
                yield item
        finally:
            call.cancel()

    async def close(self) -> None:
        await self._channel.close()


def _metadata(values: Any) -> Metadata:
    """Copy gRPC metadata into an immutable, transport-neutral value."""

    if values is None:
        return ()
    return tuple((str(key), value) for key, value in values)
