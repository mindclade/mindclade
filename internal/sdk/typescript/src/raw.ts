import type { DescService } from "@bufbuild/protobuf";
import { type Client, createClient, type Transport } from "@connectrpc/connect";

import { AdminService } from "../../../../protocols/generated/typescript/internal/admin/v1/admin_service_pb.js";
import { AgentService } from "../../../../protocols/generated/typescript/internal/agent/v1/agent_service_pb.js";
import { ArtifactService } from "../../../../protocols/generated/typescript/internal/artifact/v1/artifact_service_pb.js";
import { DatasetService } from "../../../../protocols/generated/typescript/internal/dataset/v1/dataset_service_pb.js";
import { EvaluationService } from "../../../../protocols/generated/typescript/internal/evaluation/v1/evaluation_service_pb.js";
import { ExperimentService } from "../../../../protocols/generated/typescript/internal/experiment/v1/experiment_service_pb.js";
import { InferenceService } from "../../../../protocols/generated/typescript/internal/inference/v1/inference_service_pb.js";
import {
	JobService,
	OperationService,
	RunService,
} from "../../../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import { ModelService } from "../../../../protocols/generated/typescript/internal/model/v1/model_service_pb.js";
import { PolicyService } from "../../../../protocols/generated/typescript/internal/policy/v1/policy_service_pb.js";
import { TrainingService } from "../../../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import {
	ApprovalService,
	WorkflowService,
} from "../../../../protocols/generated/typescript/internal/workflow/v1/workflow_service_pb.js";

/** Complete typed client estate for internal generated services. */
export class RawInternalClients {
	readonly admin: Client<typeof AdminService>;
	readonly agents: Client<typeof AgentService>;
	readonly artifacts: Client<typeof ArtifactService>;
	readonly datasets: Client<typeof DatasetService>;
	readonly evaluations: Client<typeof EvaluationService>;
	readonly experiments: Client<typeof ExperimentService>;
	readonly inference: Client<typeof InferenceService>;
	readonly jobs: Client<typeof JobService>;
	readonly operations: Client<typeof OperationService>;
	readonly runs: Client<typeof RunService>;
	readonly models: Client<typeof ModelService>;
	readonly policy: Client<typeof PolicyService>;
	readonly training: Client<typeof TrainingService>;
	readonly workflows: Client<typeof WorkflowService>;
	readonly approvals: Client<typeof ApprovalService>;
	readonly #transport: Transport;

	constructor(transport: Transport) {
		this.#transport = transport;
		this.admin = createClient(AdminService, transport);
		this.agents = createClient(AgentService, transport);
		this.artifacts = createClient(ArtifactService, transport);
		this.datasets = createClient(DatasetService, transport);
		this.evaluations = createClient(EvaluationService, transport);
		this.experiments = createClient(ExperimentService, transport);
		this.inference = createClient(InferenceService, transport);
		this.jobs = createClient(JobService, transport);
		this.operations = createClient(OperationService, transport);
		this.runs = createClient(RunService, transport);
		this.models = createClient(ModelService, transport);
		this.policy = createClient(PolicyService, transport);
		this.training = createClient(TrainingService, transport);
		this.workflows = createClient(WorkflowService, transport);
		this.approvals = createClient(ApprovalService, transport);
	}

	/** Escape hatch for a new generated internal service descriptor without an
	 * SDK release. The caller receives the native Connect client type. */
	forService<Service extends DescService>(service: Service): Client<Service> {
		return createClient(service, this.#transport);
	}
}
