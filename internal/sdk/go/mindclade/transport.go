package mindclade

import (
	"errors"

	"google.golang.org/grpc"

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
)

// TransportClients is the complete generated internal service estate. It is
// exposed only from this repository-internal package for advanced workflows;
// common workflows should use the ergonomic services on Client.
type TransportClients struct {
	Admin      internaladminv1.AdminServiceClient
	Agent      internalagentv1.AgentServiceClient
	Artifact   internalartifactv1.ArtifactServiceClient
	Dataset    internaldatasetv1.DatasetServiceClient
	Evaluation internalevaluationv1.EvaluationServiceClient
	Experiment internalexperimentv1.ExperimentServiceClient
	Inference  internalinferencev1.InferenceServiceClient
	Job        internaljobv1.JobServiceClient
	Operation  internaljobv1.OperationServiceClient
	Run        internaljobv1.RunServiceClient
	Model      internalmodelv1.ModelServiceClient
	Policy     internalpolicyv1.PolicyServiceClient
	Training   internaltrainingv1.TrainingServiceClient
	Workflow   internalworkflowv1.WorkflowServiceClient
	Approval   internalworkflowv1.ApprovalServiceClient
}

func newTransportClients(connection grpc.ClientConnInterface) TransportClients {
	return TransportClients{
		Admin:      internaladminv1.NewAdminServiceClient(connection),
		Agent:      internalagentv1.NewAgentServiceClient(connection),
		Artifact:   internalartifactv1.NewArtifactServiceClient(connection),
		Dataset:    internaldatasetv1.NewDatasetServiceClient(connection),
		Evaluation: internalevaluationv1.NewEvaluationServiceClient(connection),
		Experiment: internalexperimentv1.NewExperimentServiceClient(connection),
		Inference:  internalinferencev1.NewInferenceServiceClient(connection),
		Job:        internaljobv1.NewJobServiceClient(connection),
		Operation:  internaljobv1.NewOperationServiceClient(connection),
		Run:        internaljobv1.NewRunServiceClient(connection),
		Model:      internalmodelv1.NewModelServiceClient(connection),
		Policy:     internalpolicyv1.NewPolicyServiceClient(connection),
		Training:   internaltrainingv1.NewTrainingServiceClient(connection),
		Workflow:   internalworkflowv1.NewWorkflowServiceClient(connection),
		Approval:   internalworkflowv1.NewApprovalServiceClient(connection),
	}
}

func (clients TransportClients) validate() error {
	if clients.Admin == nil || clients.Agent == nil || clients.Artifact == nil ||
		clients.Dataset == nil || clients.Evaluation == nil || clients.Experiment == nil || clients.Inference == nil ||
		clients.Job == nil || clients.Operation == nil || clients.Run == nil ||
		clients.Model == nil || clients.Policy == nil || clients.Training == nil ||
		clients.Workflow == nil || clients.Approval == nil {
		return errors.New("mindclade: the generated transport client estate is incomplete")
	}
	return nil
}
