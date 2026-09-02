package conformance_test

import (
	"testing"

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	agentv1 "github.com/mindclade/mindclade/protocols/generated/go/agent/v1"
	apiv1 "github.com/mindclade/mindclade/protocols/generated/go/api/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	auditv1 "github.com/mindclade/mindclade/protocols/generated/go/audit/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	featurev1 "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	internalagentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/agent/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	internalevaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/evaluation/v1"
	internalexperimentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/experiment/v1"
	internalinferencev1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/inference/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	transformv1 "github.com/mindclade/mindclade/protocols/generated/go/transform/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

func TestEveryGeneratedGoPackageRoundTripsRepresentativeMessage(t *testing.T) {
	t.Parallel()
	tests := []struct {
		packageName string
		message     proto.Message
	}{
		{"mindclade.admin.v1", &adminv1.Tenant{Name: "tenants/tenant_1"}},
		{"mindclade.agent.v1", &agentv1.AgentDefinition{Name: "tenants/tenant_1/projects/project_1/agentDefinitions/agent_1"}},
		{"mindclade.api.v1", &apiv1.Operation{Name: "tenants/tenant_1/projects/project_1/operations/op_1"}},
		{"mindclade.artifact.v1", &artifactv1.ArtifactRef{Digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}},
		{"mindclade.common.v1", &commonv1.Identifiers{TenantId: "tenant_1"}},
		{"mindclade.dataset.v1", &datasetv1.Dataset{Name: "tenants/tenant_1/projects/project_1/datasets/dataset_1"}},
		{"mindclade.evaluation.v1", &evaluationv1.EvaluationRun{Name: "tenants/tenant_1/projects/project_1/evaluationRuns/eval_1"}},
		{"mindclade.events.agent.v1", &agentv1.AgentRunCompleted{AttemptId: "attempt_1"}},
		{"mindclade.events.artifact.v1", &artifactv1.ArtifactCommitted{ProducerAttemptId: "attempt_1"}},
		{"mindclade.events.audit.v1", &auditv1.AuditEvent{ActorPrincipalId: "principal_1"}},
		{"mindclade.events.experiment.v1", &experimentv1.ExperimentCreated{Experiment: &experimentv1.Experiment{Name: "tenants/tenant_1/projects/project_1/experiments/experiment_1"}}},
		{"mindclade.events.feature.v1", &featurev1.FeatureMaterializationCompleted{MaterializationName: "materializations/materialization_1"}},
		{"mindclade.events.job.v1", &jobv1.JobRequested{JobId: "job_1"}},
		{"mindclade.events.model.v1", &modelv1.ModelRegistered{ModelName: "models/model_1"}},
		{"mindclade.events.training.v1", &trainingv1.TrainingStarted{TrainingRunName: "trainingRuns/run_1"}},
		{"mindclade.events.transform.v1", &transformv1.TransformExecutionCompleted{ExecutionName: "transformExecutions/execution_1"}},
		{"mindclade.events.workflow.v1", &workflowv1.WorkflowTransitioned{TransitionReasonCode: "STEP_COMPLETED"}},
		{"mindclade.experiment.v1", &experimentv1.Experiment{Name: "tenants/tenant_1/projects/project_1/experiments/experiment_1"}},
		{"mindclade.feature.v1", &featurev1.FeatureMaterialization{Name: "tenants/tenant_1/projects/project_1/featureMaterializations/materialization_1"}},
		{"mindclade.inference.v1", &inferencev1.InferenceRequest{Name: "tenants/tenant_1/projects/project_1/inferenceRequests/request_1"}},
		{"mindclade.internal.admin.v1", &internaladminv1.GetTenantRequest{Name: "tenants/tenant_1"}},
		{"mindclade.internal.agent.v1", &internalagentv1.GetAgentDefinitionRequest{Name: "agentDefinitions/agent_1"}},
		{"mindclade.internal.artifact.v1", &internalartifactv1.GetArtifactRequest{Name: "artifacts/artifact_1"}},
		{"mindclade.internal.dataset.v1", &internaldatasetv1.GetDatasetRequest{Name: "datasets/dataset_1"}},
		{"mindclade.internal.evaluation.v1", &internalevaluationv1.GetEvaluationRunRequest{Name: "evaluationRuns/eval_1"}},
		{"mindclade.internal.experiment.v1", &internalexperimentv1.GetExperimentRequest{Name: "experiments/experiment_1"}},
		{"mindclade.internal.inference.v1", &internalinferencev1.GetInferenceResultRequest{OperationName: "operations/op_1"}},
		{"mindclade.internal.job.v1", &internaljobv1.GetJobRequest{Name: "jobs/job_1"}},
		{"mindclade.internal.model.v1", &internalmodelv1.GetModelRequest{Name: "models/model_1"}},
		{"mindclade.internal.policy.v1", &internalpolicyv1.GetUsePolicyRequest{Name: "policies/policy_1"}},
		{"mindclade.internal.training.v1", &internaltrainingv1.GetTrainingRunRequest{Name: "trainingRuns/run_1"}},
		{"mindclade.internal.workflow.v1", &internalworkflowv1.GetWorkflowDefinitionRequest{Name: "workflowDefinitions/workflow_1"}},
		{"mindclade.job.v1", &jobv1.Job{JobId: "job_1"}},
		{"mindclade.model.v1", &modelv1.Model{Name: "tenants/tenant_1/projects/project_1/models/model_1"}},
		{"mindclade.policy.v1", &policyv1.PolicyReference{Name: "policies/policy_1"}},
		{"mindclade.training.v1", &trainingv1.TrainingRun{Name: "tenants/tenant_1/projects/project_1/trainingRuns/run_1"}},
		{"mindclade.transform.v1", &transformv1.TransformExecution{Name: "tenants/tenant_1/projects/project_1/transformExecutions/execution_1"}},
		{"mindclade.workflow.v1", &workflowv1.WorkflowDefinition{Name: "tenants/tenant_1/projects/project_1/workflowDefinitions/workflow_1"}},
	}

	for _, test := range tests {
		test := test
		t.Run(test.packageName, func(t *testing.T) {
			descriptor := test.message.ProtoReflect().Descriptor()
			if got := string(descriptor.ParentFile().Package()); got != test.packageName {
				t.Fatalf("descriptor package = %q, want %q", got, test.packageName)
			}
			wire, err := proto.MarshalOptions{Deterministic: true}.Marshal(test.message)
			if err != nil {
				t.Fatal(err)
			}
			if len(wire) == 0 {
				t.Fatal("representative message serialized to an empty wire payload")
			}
			wireDecoded := test.message.ProtoReflect().Type().New().Interface()
			if err := proto.Unmarshal(wire, wireDecoded); err != nil {
				t.Fatal(err)
			}
			if !proto.Equal(test.message, wireDecoded) {
				t.Fatalf("wire round trip mismatch: %v != %v", test.message, wireDecoded)
			}

			jsonPayload, err := protojson.Marshal(test.message)
			if err != nil {
				t.Fatal(err)
			}
			jsonDecoded := test.message.ProtoReflect().Type().New().Interface()
			if err := protojson.Unmarshal(jsonPayload, jsonDecoded); err != nil {
				t.Fatal(err)
			}
			if !proto.Equal(test.message, jsonDecoded) {
				t.Fatalf("ProtoJSON round trip mismatch: %v != %v", test.message, jsonDecoded)
			}
		})
	}
}
