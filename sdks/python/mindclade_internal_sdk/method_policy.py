"""Fully-qualified retry safety policy for the generated RPC escape hatch."""

from __future__ import annotations

import copy
import hmac
from typing import Any, cast

from google.protobuf.message import Message
from mindclade.common.v1 import command_context_pb2
from mindclade.dataset.v1 import dataset_commands_pb2
from mindclade.inference.v1 import inference_request_pb2
from mindclade.internal.admin.v1 import admin_service_pb2
from mindclade.internal.agent.v1 import agent_service_pb2
from mindclade.internal.artifact.v1 import artifact_service_pb2
from mindclade.internal.dataset.v1 import dataset_service_pb2
from mindclade.internal.evaluation.v1 import evaluation_service_pb2
from mindclade.internal.experiment.v1 import experiment_service_pb2
from mindclade.internal.inference.v1 import inference_service_pb2
from mindclade.internal.job.v1 import job_service_pb2
from mindclade.internal.model.v1 import model_service_pb2
from mindclade.internal.policy.v1 import policy_service_pb2
from mindclade.internal.training.v1 import training_service_pb2
from mindclade.internal.workflow.v1 import workflow_service_pb2
from mindclade.model.v1 import model_commands_pb2
from mindclade.training.v1 import training_commands_pb2
from mindclade.workflow.v1 import approval_pb2

from ._invocation import canonical_digest
from .calls import PreparedCall
from .config import ClientConfig
from .transport import (
    ABORT_ARTIFACT_UPLOAD,
    ACQUIRE_ARTIFACT_LEASE,
    ACQUIRE_ATTEMPT_LEASE,
    ACTIVATE_USE_POLICY,
    BEGIN_ARTIFACT_UPLOAD,
    CANCEL_ATTEMPT,
    CANCEL_EVALUATION_RUN,
    CANCEL_JOB,
    CANCEL_OPERATION,
    CANCEL_TRAINING_RUN,
    CANCEL_WORKFLOW_RUN,
    COMMIT_ARTIFACT,
    COMMIT_ATTEMPT,
    COMMIT_CHECKPOINT,
    COMMIT_EVALUATION_RESULT,
    COMMIT_INFERENCE_RESULT,
    COMMIT_TRAINING_PROGRESS,
    COMMIT_WORKFLOW_TRANSITION,
    COMPLETE_TRAINING_RUN,
    COMPLETE_TRIAL,
    CONSUME_APPROVAL,
    CREATE_DATASET,
    CREATE_EVALUATION_RUN,
    CREATE_EXPERIMENT,
    CREATE_PROJECT,
    CREATE_PROMOTION_DECISION,
    CREATE_STUDY,
    CREATE_TRAINING_RUN,
    CREATE_TRIAL,
    CREATE_USE_POLICY,
    CREATE_WORKFLOW_DEFINITION,
    DECIDE_APPROVAL,
    EVALUATE_AUTHORIZATION,
    EXPORT_AUDIT_RECORDS,
    FINALIZE_ARTIFACT_UPLOAD,
    HEARTBEAT_ATTEMPT,
    PREPARE_CHECKPOINT,
    PROMOTE_MODEL_RELEASE,
    PUBLISH_DATASET_RELEASE,
    QUARANTINE_ARTIFACT,
    QUARANTINE_ARTIFACT_UPLOAD,
    REGISTER_MODEL,
    REGISTER_MODEL_RELEASE,
    RELEASE_ARTIFACT_LEASE,
    RENEW_ATTEMPT_LEASE,
    REQUEST_APPROVAL,
    REQUEST_JOB,
    RESUME_TRAINING_ATTEMPT,
    REVOKE_DATASET_RELEASE,
    REVOKE_MODEL_RELEASE,
    REVOKE_USE_POLICY,
    START_TRAINING_ATTEMPT,
    START_WORKFLOW_RUN,
    SUBMIT_INFERENCE,
    TRANSITION_EXPERIMENT,
    TRANSITION_STUDY,
    TRANSITION_TRIAL,
    UPDATE_DATASET,
    UPDATE_EXPERIMENT,
    UPDATE_PROJECT,
    UPDATE_TENANT,
    UPDATE_USE_POLICY,
    UPDATE_WORKFLOW_DEFINITION,
    UPLOAD_ARTIFACT_CHUNK,
)

type _ArtifactMutation = (
    artifact_service_pb2.BeginArtifactUploadRequest
    | artifact_service_pb2.UploadArtifactChunkRequest
    | artifact_service_pb2.FinalizeArtifactUploadRequest
    | artifact_service_pb2.AbortArtifactUploadRequest
    | artifact_service_pb2.QuarantineArtifactUploadRequest
)

SAFE_UNARY_METHODS = frozenset(
    {
        "/mindclade.internal.admin.v1.AdminService/GetTenant",
        "/mindclade.internal.admin.v1.AdminService/GetProject",
        "/mindclade.internal.admin.v1.AdminService/ListProjects",
        "/mindclade.internal.admin.v1.AdminService/QueryAuditRecords",
        "/mindclade.internal.admin.v1.AdminService/GetAuditExport",
        "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition",
        "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions",
        "/mindclade.internal.agent.v1.AgentService/GetAgentRun",
        "/mindclade.internal.agent.v1.AgentService/ListAgentRuns",
        "/mindclade.internal.agent.v1.AgentService/GetAgentStep",
        "/mindclade.internal.agent.v1.AgentService/ListAgentSteps",
        "/mindclade.internal.artifact.v1.ArtifactService/GetArtifact",
        "/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts",
        "/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias",
        "/mindclade.internal.artifact.v1.ArtifactService/GetArtifactUpload",
        "/mindclade.internal.dataset.v1.DatasetService/GetDataset",
        "/mindclade.internal.dataset.v1.DatasetService/ListDatasets",
        "/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease",
        "/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases",
        "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun",
        "/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns",
        "/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult",
        "/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision",
        "/mindclade.internal.experiment.v1.ExperimentService/GetExperiment",
        "/mindclade.internal.experiment.v1.ExperimentService/ListExperiments",
        "/mindclade.internal.experiment.v1.ExperimentService/GetStudy",
        "/mindclade.internal.experiment.v1.ExperimentService/ListStudies",
        "/mindclade.internal.experiment.v1.ExperimentService/GetTrial",
        "/mindclade.internal.experiment.v1.ExperimentService/ListTrials",
        "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult",
        "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest",
        "/mindclade.internal.job.v1.OperationService/GetOperation",
        "/mindclade.internal.job.v1.OperationService/ListOperations",
        "/mindclade.internal.job.v1.JobService/GetJob",
        "/mindclade.internal.job.v1.JobService/ListJobs",
        "/mindclade.internal.job.v1.RunService/GetRun",
        "/mindclade.internal.job.v1.RunService/ListRuns",
        "/mindclade.internal.job.v1.RunService/GetAttempt",
        "/mindclade.internal.job.v1.RunService/ListAttempts",
        "/mindclade.internal.model.v1.ModelService/GetModel",
        "/mindclade.internal.model.v1.ModelService/ListModels",
        "/mindclade.internal.model.v1.ModelService/GetModelRelease",
        "/mindclade.internal.model.v1.ModelService/ListModelReleases",
        "/mindclade.internal.policy.v1.PolicyService/GetUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/ListUsePolicies",
        "/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot",
        "/mindclade.internal.training.v1.TrainingService/GetTrainingRun",
        "/mindclade.internal.training.v1.TrainingService/ListTrainingRuns",
        "/mindclade.internal.training.v1.TrainingService/GetCheckpoint",
        "/mindclade.internal.training.v1.TrainingService/ListCheckpoints",
        "/mindclade.internal.training.v1.TrainingService/WatchTrainingRun",
        "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition",
        "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions",
        "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun",
        "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns",
        "/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest",
        "/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests",
        "/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact",
        "/mindclade.internal.inference.v1.InferenceService/WatchInference",
        "/mindclade.internal.job.v1.OperationService/WatchOperation",
        "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun",
    }
)

# Mutations whose request embeds a generated ``CommandContext``. Membership is
# necessary but never sufficient: ``retry_permitted`` still verifies the
# embedded context's idempotency key, scope, and canonical request digest
# against the call the SDK is about to make. The table exists so the estate is
# declarative and checkable rather than implied by a dispatch chain, and so a
# route added to that chain without being declared here fails closed.
IDEMPOTENT_MUTATION_METHODS = frozenset(
    {
        "/mindclade.internal.admin.v1.AdminService/CreateProject",
        "/mindclade.internal.admin.v1.AdminService/ExportAuditRecords",
        "/mindclade.internal.admin.v1.AdminService/UpdateProject",
        "/mindclade.internal.admin.v1.AdminService/UpdateTenant",
        "/mindclade.internal.agent.v1.AgentService/CancelAgentRun",
        "/mindclade.internal.agent.v1.AgentService/CommitAgentStep",
        "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt",
        "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition",
        "/mindclade.internal.agent.v1.AgentService/StartAgentRun",
        "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition",
        "/mindclade.internal.artifact.v1.ArtifactService/AbortArtifactUpload",
        "/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease",
        "/mindclade.internal.artifact.v1.ArtifactService/BeginArtifactUpload",
        "/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact",
        "/mindclade.internal.artifact.v1.ArtifactService/FinalizeArtifactUpload",
        "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact",
        "/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifactUpload",
        "/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease",
        "/mindclade.internal.artifact.v1.ArtifactService/UploadArtifactChunk",
        "/mindclade.internal.dataset.v1.DatasetService/CreateDataset",
        "/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease",
        "/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease",
        "/mindclade.internal.dataset.v1.DatasetService/UpdateDataset",
        "/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun",
        "/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult",
        "/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun",
        "/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision",
        "/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial",
        "/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment",
        "/mindclade.internal.experiment.v1.ExperimentService/CreateStudy",
        "/mindclade.internal.experiment.v1.ExperimentService/CreateTrial",
        "/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment",
        "/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy",
        "/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial",
        "/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment",
        "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult",
        "/mindclade.internal.inference.v1.InferenceService/SubmitInference",
        "/mindclade.internal.job.v1.JobService/CancelJob",
        "/mindclade.internal.job.v1.JobService/RequestJob",
        "/mindclade.internal.job.v1.OperationService/CancelOperation",
        "/mindclade.internal.job.v1.RunService/AcquireAttemptLease",
        "/mindclade.internal.job.v1.RunService/CancelAttempt",
        "/mindclade.internal.job.v1.RunService/CommitAttempt",
        "/mindclade.internal.job.v1.RunService/HeartbeatAttempt",
        "/mindclade.internal.job.v1.RunService/RenewAttemptLease",
        "/mindclade.internal.model.v1.ModelService/PromoteModelRelease",
        "/mindclade.internal.model.v1.ModelService/RegisterModel",
        "/mindclade.internal.model.v1.ModelService/RegisterModelRelease",
        "/mindclade.internal.model.v1.ModelService/RevokeModelRelease",
        "/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization",
        "/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy",
        "/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy",
        "/mindclade.internal.training.v1.TrainingService/CancelTrainingRun",
        "/mindclade.internal.training.v1.TrainingService/CommitCheckpoint",
        "/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress",
        "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun",
        "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun",
        "/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint",
        "/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt",
        "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt",
        "/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval",
        "/mindclade.internal.workflow.v1.ApprovalService/DecideApproval",
        "/mindclade.internal.workflow.v1.ApprovalService/RequestApproval",
        "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun",
        "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition",
        "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition",
        "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun",
        "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition",
    }
)

# The single deliberate never-retry escape hatch. Lease expiry replays a
# control-plane reconciler primitive, so replaying it is never safe at any
# attempt count, under any server override, in any language.
NEVER_RETRY_METHODS = frozenset(
    {
        "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases",
    }
)

# AgentService route identities. They live here rather than being imported from
# ``agents`` because that module imports this one's dependencies; the strings are
# pinned by the descriptor-conformance parity test like every other route above.
CREATE_AGENT_DEFINITION = "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition"
UPDATE_AGENT_DEFINITION = "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition"
START_AGENT_RUN = "/mindclade.internal.agent.v1.AgentService/StartAgentRun"
CANCEL_AGENT_RUN = "/mindclade.internal.agent.v1.AgentService/CancelAgentRun"
COMMIT_AGENT_STEP = "/mindclade.internal.agent.v1.AgentService/CommitAgentStep"
COMMIT_TOOL_RECEIPT = "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt"


def _matches(
    context: command_context_pb2.CommandContext,
    call: PreparedCall,
    config: ClientConfig,
    digest: str,
    *,
    project_id: str | None = None,
) -> bool:
    expected_project = config.project_id if project_id is None else project_id
    return (
        call.idempotency_key is not None
        and hmac.compare_digest(context.idempotency_key, call.idempotency_key)
        and hmac.compare_digest(context.canonical_request_digest, digest)
        and hmac.compare_digest(context.tenant_id, config.tenant_id)
        and hmac.compare_digest(context.project_id, expected_project)
        and hmac.compare_digest(context.principal_id, config.principal_id)
    )


def _artifact_matches(
    request: _ArtifactMutation,
    clone: _ArtifactMutation,
    call: PreparedCall,
    config: ClientConfig,
) -> bool:
    if not request.HasField("context"):
        return False
    cast(Message, clone).CopyFrom(cast(Message, request))
    context = command_context_pb2.CommandContext()
    context.CopyFrom(clone.context)
    clone.ClearField("context")
    return _matches(context, call, config, canonical_digest(clone))


def _lifecycle_matches[
    CommandT: (
        dataset_commands_pb2.CreateDatasetCommand,
        dataset_commands_pb2.UpdateDatasetCommand,
        dataset_commands_pb2.PublishDatasetReleaseCommand,
        dataset_commands_pb2.RevokeDatasetReleaseCommand,
        model_commands_pb2.RegisterModelCommand,
        model_commands_pb2.RegisterModelReleaseCommand,
        model_commands_pb2.PromoteModelReleaseCommand,
        model_commands_pb2.RevokeModelReleaseCommand,
    )
](command: CommandT, call: PreparedCall, config: ClientConfig) -> bool:
    if not command.HasField("context"):
        return False
    clone = copy.deepcopy(command)
    context = command_context_pb2.CommandContext()
    context.CopyFrom(clone.context)
    clone.ClearField("context")
    return _matches(context, call, config, canonical_digest(clone))


def retry_permitted(
    method: str,
    request: Message,
    call: PreparedCall,
    config: ClientConfig,
) -> bool:
    """Return true only for safe reads or verified generated command intent."""

    # The never-retry tier is checked first and unconditionally, so the raw-only
    # reconciler primitive cannot be promoted by a later branch, by a server
    # override, or by a future edit that adds its route to a mutation table.
    if method in NEVER_RETRY_METHODS:
        return False
    if method in SAFE_UNARY_METHODS:
        return True
    # A mutation must be declared before its request is even inspected: a route
    # reachable through the dispatch below but absent from the table fails closed.
    if method not in IDEMPOTENT_MUTATION_METHODS:
        return False
    agent_mutations: dict[str, type[Message]] = {
        CREATE_AGENT_DEFINITION: agent_service_pb2.CreateAgentDefinitionRequest,
        UPDATE_AGENT_DEFINITION: agent_service_pb2.UpdateAgentDefinitionRequest,
        START_AGENT_RUN: agent_service_pb2.StartAgentRunRequest,
        CANCEL_AGENT_RUN: agent_service_pb2.CancelAgentRunRequest,
        COMMIT_AGENT_STEP: agent_service_pb2.CommitAgentStepRequest,
        COMMIT_TOOL_RECEIPT: agent_service_pb2.CommitToolReceiptRequest,
    }
    if method in agent_mutations and isinstance(request, agent_mutations[method]):
        return _request_matches(request, call, config)
    policy_mutations: dict[str, type[Message]] = {
        EVALUATE_AUTHORIZATION: policy_service_pb2.EvaluateAuthorizationRequest,
        CREATE_USE_POLICY: policy_service_pb2.CreateUsePolicyRequest,
        UPDATE_USE_POLICY: policy_service_pb2.UpdateUsePolicyRequest,
        ACTIVATE_USE_POLICY: policy_service_pb2.ActivateUsePolicyRequest,
        REVOKE_USE_POLICY: policy_service_pb2.RevokeUsePolicyRequest,
    }
    if method in policy_mutations and isinstance(request, policy_mutations[method]):
        return _request_matches(request, call, config)
    admin_mutations: dict[str, type[Message]] = {
        UPDATE_TENANT: admin_service_pb2.UpdateTenantRequest,
        CREATE_PROJECT: admin_service_pb2.CreateProjectRequest,
        UPDATE_PROJECT: admin_service_pb2.UpdateProjectRequest,
        EXPORT_AUDIT_RECORDS: admin_service_pb2.ExportAuditRecordsRequest,
    }
    if method in admin_mutations and isinstance(request, admin_mutations[method]):
        expected_project = config.project_id
        if method == UPDATE_TENANT or (
            method == EXPORT_AUDIT_RECORDS
            and cast(admin_service_pb2.ExportAuditRecordsRequest, request).query.parent
            == (
                config.tenant_id
                if config.tenant_id.startswith("tenants/")
                else f"tenants/{config.tenant_id}"
            )
        ):
            expected_project = ""
        return _request_matches(request, call, config, project_id=expected_project)
    evaluation_mutations: dict[str, type[Message]] = {
        CREATE_EVALUATION_RUN: evaluation_service_pb2.CreateEvaluationRunRequest,
        CANCEL_EVALUATION_RUN: evaluation_service_pb2.CancelEvaluationRunRequest,
        COMMIT_EVALUATION_RESULT: evaluation_service_pb2.CommitEvaluationResultRequest,
        CREATE_PROMOTION_DECISION: evaluation_service_pb2.CreatePromotionDecisionRequest,
    }
    if method in evaluation_mutations and isinstance(request, evaluation_mutations[method]):
        return _request_matches(request, call, config)
    experiment_mutations: dict[str, type[Message]] = {
        CREATE_EXPERIMENT: experiment_service_pb2.CreateExperimentRequest,
        UPDATE_EXPERIMENT: experiment_service_pb2.UpdateExperimentRequest,
        TRANSITION_EXPERIMENT: experiment_service_pb2.TransitionExperimentRequest,
        CREATE_STUDY: experiment_service_pb2.CreateStudyRequest,
        TRANSITION_STUDY: experiment_service_pb2.TransitionStudyRequest,
        CREATE_TRIAL: experiment_service_pb2.CreateTrialRequest,
        TRANSITION_TRIAL: experiment_service_pb2.TransitionTrialRequest,
        COMPLETE_TRIAL: experiment_service_pb2.CompleteTrialRequest,
    }
    if method in experiment_mutations and isinstance(request, experiment_mutations[method]):
        typed_request = cast(Any, request)
        if not request.HasField("command") or not typed_request.command.HasField("context"):
            return False
        command = cast(Message, copy.deepcopy(typed_request.command))
        context = command_context_pb2.CommandContext()
        context.CopyFrom(cast(Any, command).context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    if method == CANCEL_OPERATION and isinstance(request, job_service_pb2.CancelOperationRequest):
        if not request.HasField("context"):
            return False
        clone = job_service_pb2.CancelOperationRequest()
        clone.CopyFrom(request)
        context = command_context_pb2.CommandContext()
        context.CopyFrom(clone.context)
        clone.ClearField("context")
        return _matches(context, call, config, canonical_digest(clone))
    if method == REQUEST_JOB and isinstance(request, job_service_pb2.RequestJobRequest):
        if not request.HasField("command") or not request.command.HasField("context"):
            return False
        command = copy.deepcopy(request.command)
        context = command_context_pb2.CommandContext()
        context.CopyFrom(command.context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    job_run_mutations: dict[str, type[Message]] = {
        CANCEL_JOB: job_service_pb2.CancelJobRequest,
        ACQUIRE_ATTEMPT_LEASE: job_service_pb2.AcquireAttemptLeaseRequest,
        RENEW_ATTEMPT_LEASE: job_service_pb2.RenewAttemptLeaseRequest,
        HEARTBEAT_ATTEMPT: job_service_pb2.HeartbeatAttemptRequest,
        CANCEL_ATTEMPT: job_service_pb2.CancelAttemptRequest,
        COMMIT_ATTEMPT: job_service_pb2.CommitAttemptRequest,
    }
    if method in job_run_mutations and isinstance(request, job_run_mutations[method]):
        return _request_matches(request, call, config)
    if method == CREATE_TRAINING_RUN and isinstance(
        request, training_service_pb2.CreateTrainingRunRequest
    ):
        if not request.HasField("command") or not request.command.HasField("context"):
            return False
        command = training_commands_pb2.CreateTrainingRunCommand()
        command.CopyFrom(request.command)
        context = command_context_pb2.CommandContext()
        context.CopyFrom(command.context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    training_mutations: dict[str, type[Message]] = {
        START_TRAINING_ATTEMPT: training_service_pb2.StartTrainingAttemptRequest,
        RESUME_TRAINING_ATTEMPT: training_service_pb2.ResumeTrainingAttemptRequest,
        COMMIT_TRAINING_PROGRESS: training_service_pb2.CommitTrainingProgressRequest,
        PREPARE_CHECKPOINT: training_service_pb2.PrepareCheckpointRequest,
        COMMIT_CHECKPOINT: training_service_pb2.CommitCheckpointRequest,
        COMPLETE_TRAINING_RUN: training_service_pb2.CompleteTrainingRunRequest,
        CANCEL_TRAINING_RUN: training_service_pb2.CancelTrainingRunRequest,
    }
    if method in training_mutations and isinstance(request, training_mutations[method]):
        typed_request = cast(Any, request)
        if not request.HasField("command") or not typed_request.command.HasField("context"):
            return False
        command = cast(Message, copy.deepcopy(typed_request.command))
        context = command_context_pb2.CommandContext()
        context.CopyFrom(cast(Any, command).context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    if method == SUBMIT_INFERENCE and isinstance(
        request, inference_service_pb2.SubmitInferenceRequest
    ):
        if not request.HasField("inference_request") or not request.inference_request.HasField(
            "context"
        ):
            return False
        command = inference_request_pb2.InferenceRequest()
        command.CopyFrom(request.inference_request)
        context = command_context_pb2.CommandContext()
        context.CopyFrom(command.context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    if method == COMMIT_INFERENCE_RESULT and isinstance(
        request, inference_service_pb2.CommitInferenceResultRequest
    ):
        if not request.HasField("context"):
            return False
        command = inference_service_pb2.CommitInferenceResultRequest()
        command.CopyFrom(request)
        context = command_context_pb2.CommandContext()
        context.CopyFrom(command.context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    workflow_mutations: dict[str, type[Message]] = {
        CREATE_WORKFLOW_DEFINITION: workflow_service_pb2.CreateWorkflowDefinitionRequest,
        UPDATE_WORKFLOW_DEFINITION: workflow_service_pb2.UpdateWorkflowDefinitionRequest,
        START_WORKFLOW_RUN: workflow_service_pb2.StartWorkflowRunRequest,
        CANCEL_WORKFLOW_RUN: workflow_service_pb2.CancelWorkflowRunRequest,
        COMMIT_WORKFLOW_TRANSITION: workflow_service_pb2.CommitWorkflowTransitionRequest,
        DECIDE_APPROVAL: workflow_service_pb2.DecideApprovalRequest,
        CONSUME_APPROVAL: workflow_service_pb2.ConsumeApprovalRequest,
    }
    if method in workflow_mutations and isinstance(request, workflow_mutations[method]):
        return _request_matches(request, call, config)
    if method == REQUEST_APPROVAL and isinstance(
        request, workflow_service_pb2.RequestApprovalRequest
    ):
        if not request.HasField("approval_request") or not request.approval_request.HasField(
            "context"
        ):
            return False
        command = approval_pb2.ApprovalRequest()
        command.CopyFrom(request.approval_request)
        context = command_context_pb2.CommandContext()
        context.CopyFrom(command.context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    if method == CREATE_DATASET and isinstance(request, dataset_service_pb2.CreateDatasetRequest):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == UPDATE_DATASET and isinstance(request, dataset_service_pb2.UpdateDatasetRequest):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == PUBLISH_DATASET_RELEASE and isinstance(
        request, dataset_service_pb2.PublishDatasetReleaseRequest
    ):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == REVOKE_DATASET_RELEASE and isinstance(
        request, dataset_service_pb2.RevokeDatasetReleaseRequest
    ):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == REGISTER_MODEL and isinstance(request, model_service_pb2.RegisterModelRequest):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == REGISTER_MODEL_RELEASE and isinstance(
        request, model_service_pb2.RegisterModelReleaseRequest
    ):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == PROMOTE_MODEL_RELEASE and isinstance(
        request, model_service_pb2.PromoteModelReleaseRequest
    ):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == REVOKE_MODEL_RELEASE and isinstance(
        request, model_service_pb2.RevokeModelReleaseRequest
    ):
        return request.HasField("command") and _lifecycle_matches(request.command, call, config)
    if method == BEGIN_ARTIFACT_UPLOAD and isinstance(
        request, artifact_service_pb2.BeginArtifactUploadRequest
    ):
        return _artifact_matches(
            request, artifact_service_pb2.BeginArtifactUploadRequest(), call, config
        )
    if method == UPLOAD_ARTIFACT_CHUNK and isinstance(
        request, artifact_service_pb2.UploadArtifactChunkRequest
    ):
        return _artifact_matches(
            request, artifact_service_pb2.UploadArtifactChunkRequest(), call, config
        )
    if method == FINALIZE_ARTIFACT_UPLOAD and isinstance(
        request, artifact_service_pb2.FinalizeArtifactUploadRequest
    ):
        return _artifact_matches(
            request, artifact_service_pb2.FinalizeArtifactUploadRequest(), call, config
        )
    if method == ABORT_ARTIFACT_UPLOAD and isinstance(
        request, artifact_service_pb2.AbortArtifactUploadRequest
    ):
        return _artifact_matches(
            request, artifact_service_pb2.AbortArtifactUploadRequest(), call, config
        )
    if method == QUARANTINE_ARTIFACT_UPLOAD and isinstance(
        request, artifact_service_pb2.QuarantineArtifactUploadRequest
    ):
        return _artifact_matches(
            request,
            artifact_service_pb2.QuarantineArtifactUploadRequest(),
            call,
            config,
        )
    if method == COMMIT_ARTIFACT and isinstance(
        request, artifact_service_pb2.CommitArtifactRequest
    ):
        if not request.HasField("command") or not request.command.HasField("context"):
            return False
        command = type(request.command)()
        command.CopyFrom(request.command)
        context = command_context_pb2.CommandContext()
        context.CopyFrom(command.context)
        command.ClearField("context")
        return _matches(context, call, config, canonical_digest(command))
    artifact_resource_mutations: dict[str, type[Message]] = {
        QUARANTINE_ARTIFACT: artifact_service_pb2.QuarantineArtifactRequest,
        ACQUIRE_ARTIFACT_LEASE: artifact_service_pb2.AcquireArtifactLeaseRequest,
        RELEASE_ARTIFACT_LEASE: artifact_service_pb2.ReleaseArtifactLeaseRequest,
    }
    if method in artifact_resource_mutations and isinstance(
        request, artifact_resource_mutations[method]
    ):
        return _request_matches(request, call, config)
    return False


def _request_matches(
    request: Message,
    call: PreparedCall,
    config: ClientConfig,
    *,
    project_id: str | None = None,
) -> bool:
    if not request.HasField("context"):
        return False
    clone = copy.deepcopy(request)
    context = command_context_pb2.CommandContext()
    context.CopyFrom(cast(Any, clone).context)
    clone.ClearField("context")
    return _matches(
        context,
        call,
        config,
        canonical_digest(clone),
        project_id=project_id,
    )
