package mindclade

import (
	"crypto/subtle"

	"google.golang.org/protobuf/proto"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

// safeMethods is the fully-qualified transport safety allowlist. Unknown
// methods and all mutations default to one attempt.
//
// Retry eligibility is a property of the RPC, not of the call shape, so this
// set covers server-streaming reads as well as unary ones. The name once said
// "unary" and the five server-streaming reads were simply absent, so Go
// disagreed with the other three facades about whether replaying them was
// valid. tests/conformance/test_sdk_retry_safety_parity.py now binds this set
// to the descriptor-derived RPC estate and to its three siblings.
var safeMethods = map[string]struct{}{
	"/mindclade.internal.admin.v1.AdminService/GetTenant":                      {},
	"/mindclade.internal.admin.v1.AdminService/GetProject":                     {},
	"/mindclade.internal.admin.v1.AdminService/ListProjects":                   {},
	"/mindclade.internal.admin.v1.AdminService/QueryAuditRecords":              {},
	"/mindclade.internal.admin.v1.AdminService/GetAuditExport":                 {},
	"/mindclade.internal.agent.v1.AgentService/GetAgentDefinition":             {},
	"/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions":           {},
	"/mindclade.internal.agent.v1.AgentService/GetAgentRun":                    {},
	"/mindclade.internal.agent.v1.AgentService/ListAgentRuns":                  {},
	"/mindclade.internal.agent.v1.AgentService/GetAgentStep":                   {},
	"/mindclade.internal.agent.v1.AgentService/ListAgentSteps":                 {},
	"/mindclade.internal.artifact.v1.ArtifactService/GetArtifact":              {},
	"/mindclade.internal.artifact.v1.ArtifactService/ListArtifacts":            {},
	"/mindclade.internal.artifact.v1.ArtifactService/ResolveArtifactAlias":     {},
	"/mindclade.internal.artifact.v1.ArtifactService/GetArtifactUpload":        {},
	"/mindclade.internal.dataset.v1.DatasetService/GetDataset":                 {},
	"/mindclade.internal.dataset.v1.DatasetService/ListDatasets":               {},
	"/mindclade.internal.dataset.v1.DatasetService/GetDatasetRelease":          {},
	"/mindclade.internal.dataset.v1.DatasetService/ListDatasetReleases":        {},
	"/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationRun":     {},
	"/mindclade.internal.evaluation.v1.EvaluationService/ListEvaluationRuns":   {},
	"/mindclade.internal.evaluation.v1.EvaluationService/GetEvaluationResult":  {},
	"/mindclade.internal.evaluation.v1.EvaluationService/GetPromotionDecision": {},
	"/mindclade.internal.experiment.v1.ExperimentService/GetExperiment":        {},
	"/mindclade.internal.experiment.v1.ExperimentService/ListExperiments":      {},
	"/mindclade.internal.experiment.v1.ExperimentService/GetStudy":             {},
	"/mindclade.internal.experiment.v1.ExperimentService/ListStudies":          {},
	"/mindclade.internal.experiment.v1.ExperimentService/GetTrial":             {},
	"/mindclade.internal.experiment.v1.ExperimentService/ListTrials":           {},
	"/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest":    {},
	"/mindclade.internal.inference.v1.InferenceService/GetInferenceResult":     {},
	"/mindclade.internal.job.v1.OperationService/GetOperation":                 {},
	"/mindclade.internal.job.v1.OperationService/ListOperations":               {},
	"/mindclade.internal.job.v1.JobService/GetJob":                             {},
	"/mindclade.internal.job.v1.JobService/ListJobs":                           {},
	"/mindclade.internal.job.v1.RunService/GetRun":                             {},
	"/mindclade.internal.job.v1.RunService/ListRuns":                           {},
	"/mindclade.internal.job.v1.RunService/GetAttempt":                         {},
	"/mindclade.internal.job.v1.RunService/ListAttempts":                       {},
	"/mindclade.internal.model.v1.ModelService/GetModel":                       {},
	"/mindclade.internal.model.v1.ModelService/ListModels":                     {},
	"/mindclade.internal.model.v1.ModelService/GetModelRelease":                {},
	"/mindclade.internal.model.v1.ModelService/ListModelReleases":              {},
	"/mindclade.internal.policy.v1.PolicyService/GetUsePolicy":                 {},
	"/mindclade.internal.policy.v1.PolicyService/ListUsePolicies":              {},
	"/mindclade.internal.policy.v1.PolicyService/ResolvePolicySnapshot":        {},
	"/mindclade.internal.training.v1.TrainingService/GetTrainingRun":           {},
	"/mindclade.internal.training.v1.TrainingService/ListTrainingRuns":         {},
	"/mindclade.internal.training.v1.TrainingService/GetCheckpoint":            {},
	"/mindclade.internal.training.v1.TrainingService/ListCheckpoints":          {},
	"/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition":    {},
	"/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions":  {},
	"/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun":           {},
	"/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns":         {},
	"/mindclade.internal.workflow.v1.ApprovalService/GetApprovalRequest":       {},
	"/mindclade.internal.workflow.v1.ApprovalService/ListApprovalRequests":     {},

	// Server-streaming reads. Opening one of these streams is as replayable as
	// any other read; a watcher reconnect resumes from the last acknowledged
	// cursor rather than re-observing what the caller already saw.
	"/mindclade.internal.artifact.v1.ArtifactService/DownloadArtifact": {},
	"/mindclade.internal.inference.v1.InferenceService/WatchInference": {},
	"/mindclade.internal.job.v1.OperationService/WatchOperation":       {},
	"/mindclade.internal.training.v1.TrainingService/WatchTrainingRun": {},
	"/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun": {},
}

type mutationRetryValidator func(any, requestMetadata, Config) bool

// Mutation retries require both a known method and a generated command context
// whose key, scope, and canonical digest match the actual request. Merely
// attaching idempotency metadata can never promote an arbitrary raw mutation.
var idempotentMutationMethods = map[string]mutationRetryValidator{
	"/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition":             validateAgentMutationRetry,
	"/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition":             validateAgentMutationRetry,
	"/mindclade.internal.agent.v1.AgentService/StartAgentRun":                     validateAgentMutationRetry,
	"/mindclade.internal.agent.v1.AgentService/CancelAgentRun":                    validateAgentMutationRetry,
	"/mindclade.internal.agent.v1.AgentService/CommitAgentStep":                   validateAgentMutationRetry,
	"/mindclade.internal.agent.v1.AgentService/CommitToolReceipt":                 validateAgentMutationRetry,
	"/mindclade.internal.job.v1.OperationService/CancelOperation":                 validateCancelOperationRetry,
	"/mindclade.internal.job.v1.JobService/RequestJob":                            validateJobMutationRetry,
	"/mindclade.internal.job.v1.JobService/CancelJob":                             validateJobMutationRetry,
	"/mindclade.internal.job.v1.RunService/AcquireAttemptLease":                   validateRunMutationRetry,
	"/mindclade.internal.job.v1.RunService/RenewAttemptLease":                     validateRunMutationRetry,
	"/mindclade.internal.job.v1.RunService/HeartbeatAttempt":                      validateRunMutationRetry,
	"/mindclade.internal.job.v1.RunService/CancelAttempt":                         validateRunMutationRetry,
	"/mindclade.internal.job.v1.RunService/CommitAttempt":                         validateRunMutationRetry,
	"/mindclade.internal.training.v1.TrainingService/CreateTrainingRun":           validateCreateTrainingRunRetry,
	"/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt":        validateTrainingMutationRetry,
	"/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt":       validateTrainingMutationRetry,
	"/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress":      validateTrainingMutationRetry,
	"/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint":           validateTrainingMutationRetry,
	"/mindclade.internal.training.v1.TrainingService/CommitCheckpoint":            validateTrainingMutationRetry,
	"/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun":         validateTrainingMutationRetry,
	"/mindclade.internal.training.v1.TrainingService/CancelTrainingRun":           validateTrainingMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/BeginArtifactUpload":         validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/UploadArtifactChunk":         validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/FinalizeArtifactUpload":      validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/AbortArtifactUpload":         validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifactUpload":    validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/CommitArtifact":              validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/QuarantineArtifact":          validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/AcquireArtifactLease":        validateArtifactMutationRetry,
	"/mindclade.internal.artifact.v1.ArtifactService/ReleaseArtifactLease":        validateArtifactMutationRetry,
	"/mindclade.internal.dataset.v1.DatasetService/CreateDataset":                 validateLifecycleMutationRetry,
	"/mindclade.internal.dataset.v1.DatasetService/UpdateDataset":                 validateLifecycleMutationRetry,
	"/mindclade.internal.dataset.v1.DatasetService/PublishDatasetRelease":         validateLifecycleMutationRetry,
	"/mindclade.internal.dataset.v1.DatasetService/RevokeDatasetRelease":          validateLifecycleMutationRetry,
	"/mindclade.internal.model.v1.ModelService/RegisterModel":                     validateLifecycleMutationRetry,
	"/mindclade.internal.model.v1.ModelService/RegisterModelRelease":              validateLifecycleMutationRetry,
	"/mindclade.internal.model.v1.ModelService/PromoteModelRelease":               validateLifecycleMutationRetry,
	"/mindclade.internal.model.v1.ModelService/RevokeModelRelease":                validateLifecycleMutationRetry,
	"/mindclade.internal.inference.v1.InferenceService/SubmitInference":           validateInferenceMutationRetry,
	"/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult":     validateInferenceMutationRetry,
	"/mindclade.internal.evaluation.v1.EvaluationService/CreateEvaluationRun":     validateEvaluationMutationRetry,
	"/mindclade.internal.evaluation.v1.EvaluationService/CancelEvaluationRun":     validateEvaluationMutationRetry,
	"/mindclade.internal.evaluation.v1.EvaluationService/CommitEvaluationResult":  validateEvaluationMutationRetry,
	"/mindclade.internal.evaluation.v1.EvaluationService/CreatePromotionDecision": validateEvaluationMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/CreateExperiment":        validateExperimentMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/UpdateExperiment":        validateExperimentMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/TransitionExperiment":    validateExperimentMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/CreateStudy":             validateExperimentMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/TransitionStudy":         validateExperimentMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/CreateTrial":             validateExperimentMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/TransitionTrial":         validateExperimentMutationRetry,
	"/mindclade.internal.experiment.v1.ExperimentService/CompleteTrial":           validateExperimentMutationRetry,
	"/mindclade.internal.policy.v1.PolicyService/EvaluateAuthorization":           validatePolicyMutationRetry,
	"/mindclade.internal.policy.v1.PolicyService/CreateUsePolicy":                 validatePolicyMutationRetry,
	"/mindclade.internal.policy.v1.PolicyService/UpdateUsePolicy":                 validatePolicyMutationRetry,
	"/mindclade.internal.policy.v1.PolicyService/ActivateUsePolicy":               validatePolicyMutationRetry,
	"/mindclade.internal.policy.v1.PolicyService/RevokeUsePolicy":                 validatePolicyMutationRetry,
	"/mindclade.internal.admin.v1.AdminService/UpdateTenant":                      validateAdminMutationRetry,
	"/mindclade.internal.admin.v1.AdminService/CreateProject":                     validateAdminMutationRetry,
	"/mindclade.internal.admin.v1.AdminService/UpdateProject":                     validateAdminMutationRetry,
	"/mindclade.internal.admin.v1.AdminService/ExportAuditRecords":                validateAdminMutationRetry,
	"/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition":    validateWorkflowMutationRetry,
	"/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition":    validateWorkflowMutationRetry,
	"/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun":            validateWorkflowMutationRetry,
	"/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun":           validateWorkflowMutationRetry,
	"/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition":    validateWorkflowMutationRetry,
	"/mindclade.internal.workflow.v1.ApprovalService/RequestApproval":             validateWorkflowMutationRetry,
	"/mindclade.internal.workflow.v1.ApprovalService/DecideApproval":              validateWorkflowMutationRetry,
	"/mindclade.internal.workflow.v1.ApprovalService/ConsumeApproval":             validateWorkflowMutationRetry,
}

func validateAgentMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internalagentv1.CreateAgentDefinitionRequest:
		copyMessage := proto.Clone(typed).(*internalagentv1.CreateAgentDefinitionRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalagentv1.UpdateAgentDefinitionRequest:
		copyMessage := proto.Clone(typed).(*internalagentv1.UpdateAgentDefinitionRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalagentv1.StartAgentRunRequest:
		copyMessage := proto.Clone(typed).(*internalagentv1.StartAgentRunRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalagentv1.CancelAgentRunRequest:
		copyMessage := proto.Clone(typed).(*internalagentv1.CancelAgentRunRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalagentv1.CommitAgentStepRequest:
		copyMessage := proto.Clone(typed).(*internalagentv1.CommitAgentStepRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalagentv1.CommitToolReceiptRequest:
		copyMessage := proto.Clone(typed).(*internalagentv1.CommitToolReceiptRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validateJobMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internaljobv1.RequestJobRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*jobv1.RequestJobCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaljobv1.CancelJobRequest:
		copyMessage := proto.Clone(typed).(*internaljobv1.CancelJobRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validateRunMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internaljobv1.AcquireAttemptLeaseRequest:
		copyMessage := proto.Clone(typed).(*internaljobv1.AcquireAttemptLeaseRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaljobv1.RenewAttemptLeaseRequest:
		copyMessage := proto.Clone(typed).(*internaljobv1.RenewAttemptLeaseRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaljobv1.HeartbeatAttemptRequest:
		copyMessage := proto.Clone(typed).(*internaljobv1.HeartbeatAttemptRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaljobv1.CancelAttemptRequest:
		copyMessage := proto.Clone(typed).(*internaljobv1.CancelAttemptRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaljobv1.CommitAttemptRequest:
		copyMessage := proto.Clone(typed).(*internaljobv1.CommitAttemptRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validateWorkflowMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internalworkflowv1.CreateWorkflowDefinitionRequest:
		copyMessage := proto.Clone(typed).(*internalworkflowv1.CreateWorkflowDefinitionRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalworkflowv1.UpdateWorkflowDefinitionRequest:
		copyMessage := proto.Clone(typed).(*internalworkflowv1.UpdateWorkflowDefinitionRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalworkflowv1.StartWorkflowRunRequest:
		copyMessage := proto.Clone(typed).(*internalworkflowv1.StartWorkflowRunRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalworkflowv1.CancelWorkflowRunRequest:
		copyMessage := proto.Clone(typed).(*internalworkflowv1.CancelWorkflowRunRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalworkflowv1.CommitWorkflowTransitionRequest:
		copyMessage := proto.Clone(typed).(*internalworkflowv1.CommitWorkflowTransitionRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalworkflowv1.RequestApprovalRequest:
		if typed.GetApprovalRequest() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetApprovalRequest()).(*workflowv1.ApprovalRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalworkflowv1.DecideApprovalRequest:
		copyMessage := proto.Clone(typed).(*internalworkflowv1.DecideApprovalRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalworkflowv1.ConsumeApprovalRequest:
		copyMessage := proto.Clone(typed).(*internalworkflowv1.ConsumeApprovalRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validatePolicyMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internalpolicyv1.EvaluateAuthorizationRequest:
		copyMessage := proto.Clone(typed).(*internalpolicyv1.EvaluateAuthorizationRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalpolicyv1.CreateUsePolicyRequest:
		copyMessage := proto.Clone(typed).(*internalpolicyv1.CreateUsePolicyRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalpolicyv1.UpdateUsePolicyRequest:
		copyMessage := proto.Clone(typed).(*internalpolicyv1.UpdateUsePolicyRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalpolicyv1.ActivateUsePolicyRequest:
		copyMessage := proto.Clone(typed).(*internalpolicyv1.ActivateUsePolicyRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalpolicyv1.RevokeUsePolicyRequest:
		copyMessage := proto.Clone(typed).(*internalpolicyv1.RevokeUsePolicyRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validateAdminMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	expectedProject := config.ProjectID
	switch typed := request.(type) {
	case *internaladminv1.UpdateTenantRequest:
		copyMessage := proto.Clone(typed).(*internaladminv1.UpdateTenantRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message, expectedProject = copyMessage, ""
	case *internaladminv1.CreateProjectRequest:
		copyMessage := proto.Clone(typed).(*internaladminv1.CreateProjectRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaladminv1.UpdateProjectRequest:
		copyMessage := proto.Clone(typed).(*internaladminv1.UpdateProjectRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaladminv1.ExportAuditRecordsRequest:
		copyMessage := proto.Clone(typed).(*internaladminv1.ExportAuditRecordsRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
		if copyMessage.GetQuery().GetParent() == configuredTenantName(config) {
			expectedProject = ""
		}
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContextForProject(command, metadata, config, digest, expectedProject)
}

func validateInferenceMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internalinferencev1.SubmitInferenceRequest:
		if typed.GetInferenceRequest() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetInferenceRequest()).(*inferencev1.InferenceRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalinferencev1.CommitInferenceResultRequest:
		copyMessage := proto.Clone(typed).(*internalinferencev1.CommitInferenceResultRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validateLifecycleMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internaldatasetv1.CreateDatasetRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*datasetv1.CreateDatasetCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaldatasetv1.UpdateDatasetRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*datasetv1.UpdateDatasetCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaldatasetv1.PublishDatasetReleaseRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*datasetv1.PublishDatasetReleaseCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaldatasetv1.RevokeDatasetReleaseRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*datasetv1.RevokeDatasetReleaseCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalmodelv1.RegisterModelRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*modelv1.RegisterModelCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalmodelv1.RegisterModelReleaseRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*modelv1.RegisterModelReleaseCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalmodelv1.PromoteModelReleaseRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*modelv1.PromoteModelReleaseCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalmodelv1.RevokeModelReleaseRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*modelv1.RevokeModelReleaseCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validateArtifactMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internalartifactv1.BeginArtifactUploadRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.BeginArtifactUploadRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.UploadArtifactChunkRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.UploadArtifactChunkRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.FinalizeArtifactUploadRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.FinalizeArtifactUploadRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.AbortArtifactUploadRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.AbortArtifactUploadRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.QuarantineArtifactUploadRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.QuarantineArtifactUploadRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.CommitArtifactRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*artifactv1.CommitArtifactCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.QuarantineArtifactRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.QuarantineArtifactRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.AcquireArtifactLeaseRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.AcquireArtifactLeaseRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internalartifactv1.ReleaseArtifactLeaseRequest:
		copyMessage := proto.Clone(typed).(*internalartifactv1.ReleaseArtifactLeaseRequest)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

// neverRetryMethods can never be retried implicitly: not by the default
// policy, not by a server x-mindclade-should-retry trailer, and not by an
// explicit caller override. ExpireAttemptLeases is a raw-only control-plane
// reconciler primitive that expires leases in bulk, so a duplicate execution
// can revoke a lease a worker has already renewed under a new epoch.
var neverRetryMethods = map[string]bool{
	"/mindclade.internal.job.v1.RunService/ExpireAttemptLeases": true,
}

func retryPermitted(method string, request any, metadata requestMetadata, config Config) bool {
	if neverRetryMethods[method] {
		return false
	}
	if _, ok := safeMethods[method]; ok {
		return true
	}
	validator, ok := idempotentMutationMethods[method]
	return ok && validator(request, metadata, config)
}

func validateCancelOperationRetry(request any, metadata requestMetadata, config Config) bool {
	typed, ok := request.(*internaljobv1.CancelOperationRequest)
	if !ok || typed.GetContext() == nil {
		return false
	}
	clone := proto.Clone(typed).(*internaljobv1.CancelOperationRequest)
	commandContext := clone.Context
	clone.Context = nil
	digest, err := deterministicDigest(clone)
	return err == nil && validRetryContext(commandContext, metadata, config, digest)
}

func validateCreateTrainingRunRetry(request any, metadata requestMetadata, config Config) bool {
	typed, ok := request.(*internaltrainingv1.CreateTrainingRunRequest)
	if !ok || typed.GetCommand() == nil || typed.GetCommand().GetContext() == nil {
		return false
	}
	// Keep the concrete generated message so deterministic serialization is
	// identical to the façade's pre-context digest.
	clone := proto.Clone(typed.GetCommand()).(*trainingv1.CreateTrainingRunCommand)
	commandContext := clone.Context
	clone.Context = nil
	digest, err := deterministicDigest(clone)
	return err == nil && validRetryContext(commandContext, metadata, config, digest)
}

func validateTrainingMutationRetry(request any, metadata requestMetadata, config Config) bool {
	var command *commonv1.CommandContext
	var message proto.Message
	switch typed := request.(type) {
	case *internaltrainingv1.StartTrainingAttemptRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*trainingv1.StartTrainingAttemptCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaltrainingv1.ResumeTrainingAttemptRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*trainingv1.ResumeTrainingAttemptCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaltrainingv1.CommitTrainingProgressRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*trainingv1.CommitTrainingProgressCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaltrainingv1.PrepareCheckpointRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*trainingv1.PrepareCheckpointCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaltrainingv1.CommitCheckpointRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*trainingv1.CommitCheckpointCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaltrainingv1.CompleteTrainingRunRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*trainingv1.CompleteTrainingRunCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	case *internaltrainingv1.CancelTrainingRunRequest:
		if typed.GetCommand() == nil {
			return false
		}
		copyMessage := proto.Clone(typed.GetCommand()).(*trainingv1.CancelTrainingRunCommand)
		command, copyMessage.Context = copyMessage.Context, nil
		message = copyMessage
	default:
		return false
	}
	digest, err := deterministicDigest(message)
	return err == nil && validRetryContext(command, metadata, config, digest)
}

func validRetryContext(command *commonv1.CommandContext, metadata requestMetadata, config Config, digest string) bool {
	return validRetryContextForProject(command, metadata, config, digest, config.ProjectID)
}

func validRetryContextForProject(command *commonv1.CommandContext, metadata requestMetadata, config Config, digest, expectedProject string) bool {
	if command == nil || metadata.idempotencyKey == "" || command.GetCanonicalRequestDigest() == "" {
		return false
	}
	return constantTimeEqual(command.GetIdempotencyKey(), metadata.idempotencyKey) &&
		constantTimeEqual(command.GetCanonicalRequestDigest(), digest) &&
		constantTimeEqual(command.GetTenantId(), config.TenantID) &&
		constantTimeEqual(command.GetProjectId(), expectedProject) &&
		constantTimeEqual(command.GetPrincipalId(), config.PrincipalID)
}

func constantTimeEqual(left, right string) bool {
	if len(left) != len(right) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(left), []byte(right)) == 1
}
