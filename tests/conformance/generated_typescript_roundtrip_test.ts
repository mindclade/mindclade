import { create, equals, fromBinary, fromJson, toBinary, toJson } from "@bufbuild/protobuf";
import { TenantSchema } from "../../protocols/generated/typescript/admin/v1/tenant_pb.js";
import { AgentDefinitionSchema } from "../../protocols/generated/typescript/agent/v1/agent_definition_pb.js";
import { AgentRunCompletedSchema } from "../../protocols/generated/typescript/agent/v1/agent_run_completed_pb.js";
import { OperationSchema } from "../../protocols/generated/typescript/api/v1/mindclade_service_pb.js";
import { ArtifactCommittedSchema } from "../../protocols/generated/typescript/artifact/v1/artifact_committed_pb.js";
import { ArtifactRefSchema } from "../../protocols/generated/typescript/artifact/v1/artifact_reference_pb.js";
import { AuditEventSchema } from "../../protocols/generated/typescript/audit/v1/audit_event_pb.js";
import { IdentifiersSchema } from "../../protocols/generated/typescript/common/v1/identifiers_pb.js";
import { DatasetSchema } from "../../protocols/generated/typescript/dataset/v1/dataset_pb.js";
import { EvaluationRunSchema } from "../../protocols/generated/typescript/evaluation/v1/evaluation_run_pb.js";
import { ExperimentSchema } from "../../protocols/generated/typescript/experiment/v1/experiment_pb.js";
import { FeatureMaterializationCompletedSchema } from "../../protocols/generated/typescript/feature/v1/feature_materialization_completed_pb.js";
import { FeatureMaterializationSchema } from "../../protocols/generated/typescript/feature/v1/feature_materialization_pb.js";
import { InferenceRequestSchema } from "../../protocols/generated/typescript/inference/v1/inference_request_pb.js";
import { GetTenantRequestSchema } from "../../protocols/generated/typescript/internal/admin/v1/admin_service_pb.js";
import { GetAgentDefinitionRequestSchema } from "../../protocols/generated/typescript/internal/agent/v1/agent_service_pb.js";
import { GetArtifactRequestSchema } from "../../protocols/generated/typescript/internal/artifact/v1/artifact_service_pb.js";
import { GetDatasetRequestSchema } from "../../protocols/generated/typescript/internal/dataset/v1/dataset_service_pb.js";
import { GetEvaluationRunRequestSchema } from "../../protocols/generated/typescript/internal/evaluation/v1/evaluation_service_pb.js";
import { GetInferenceResultRequestSchema } from "../../protocols/generated/typescript/internal/inference/v1/inference_service_pb.js";
import { GetJobRequestSchema } from "../../protocols/generated/typescript/internal/job/v1/job_service_pb.js";
import { GetModelRequestSchema } from "../../protocols/generated/typescript/internal/model/v1/model_service_pb.js";
import { GetUsePolicyRequestSchema } from "../../protocols/generated/typescript/internal/policy/v1/policy_service_pb.js";
import { GetTrainingRunRequestSchema } from "../../protocols/generated/typescript/internal/training/v1/training_service_pb.js";
import { GetWorkflowDefinitionRequestSchema } from "../../protocols/generated/typescript/internal/workflow/v1/workflow_service_pb.js";
import { JobSchema } from "../../protocols/generated/typescript/job/v1/job_pb.js";
import { JobRequestedSchema } from "../../protocols/generated/typescript/job/v1/job_requested_pb.js";
import { ModelSchema } from "../../protocols/generated/typescript/model/v1/model_pb.js";
import { ModelRegisteredSchema } from "../../protocols/generated/typescript/model/v1/model_registered_pb.js";
import { PolicyReferenceSchema } from "../../protocols/generated/typescript/policy/v1/policy_reference_pb.js";
import { TrainingRunSchema } from "../../protocols/generated/typescript/training/v1/training_run_pb.js";
import { TrainingStartedSchema } from "../../protocols/generated/typescript/training/v1/training_started_pb.js";
import { TransformExecutionCompletedSchema } from "../../protocols/generated/typescript/transform/v1/transform_execution_completed_pb.js";
import { TransformExecutionSchema } from "../../protocols/generated/typescript/transform/v1/transform_execution_pb.js";
import { WorkflowDefinitionSchema } from "../../protocols/generated/typescript/workflow/v1/workflow_definition_pb.js";
import { WorkflowTransitionedSchema } from "../../protocols/generated/typescript/workflow/v1/workflow_transitioned_pb.js";

type RuntimeSchema = Parameters<typeof create>[0];

const cases: ReadonlyArray<readonly [RuntimeSchema, Record<string, unknown>]> = [
  [TenantSchema, { name: "tenants/fixture" }],
  [AgentDefinitionSchema, { name: "agentDefinitions/fixture" }],
  [OperationSchema, { name: "operations/fixture" }],
  [ArtifactRefSchema, { digest: "sha256:fixture" }],
  [IdentifiersSchema, { tenantId: "tenant-fixture" }],
  [DatasetSchema, { name: "datasets/fixture" }],
  [EvaluationRunSchema, { name: "evaluationRuns/fixture" }],
  [AgentRunCompletedSchema, { attemptId: "attempt-fixture" }],
  [ArtifactCommittedSchema, { producerAttemptId: "attempt-fixture" }],
  [AuditEventSchema, { actorPrincipalId: "principal-fixture" }],
  [FeatureMaterializationCompletedSchema, { materializationName: "featureMaterializations/fixture" }],
  [JobRequestedSchema, { jobId: "job-fixture" }],
  [ModelRegisteredSchema, { modelName: "models/fixture" }],
  [TrainingStartedSchema, { trainingRunName: "trainingRuns/fixture" }],
  [TransformExecutionCompletedSchema, { executionName: "transformExecutions/fixture" }],
  [WorkflowTransitionedSchema, { transitionReasonCode: "fixture" }],
  [ExperimentSchema, { name: "experiments/fixture" }],
  [FeatureMaterializationSchema, { name: "featureMaterializations/fixture" }],
  [InferenceRequestSchema, { name: "inferenceRequests/fixture" }],
  [GetTenantRequestSchema, { name: "tenants/fixture" }],
  [GetAgentDefinitionRequestSchema, { name: "agentDefinitions/fixture" }],
  [GetArtifactRequestSchema, { name: "artifacts/fixture" }],
  [GetDatasetRequestSchema, { name: "datasets/fixture" }],
  [GetEvaluationRunRequestSchema, { name: "evaluationRuns/fixture" }],
  [GetInferenceResultRequestSchema, { operationName: "operations/fixture" }],
  [GetJobRequestSchema, { name: "jobs/fixture" }],
  [GetModelRequestSchema, { name: "models/fixture" }],
  [GetUsePolicyRequestSchema, { name: "policies/fixture" }],
  [GetTrainingRunRequestSchema, { name: "trainingRuns/fixture" }],
  [GetWorkflowDefinitionRequestSchema, { name: "workflowDefinitions/fixture" }],
  [JobSchema, { jobId: "job-fixture" }],
  [ModelSchema, { name: "models/fixture" }],
  [PolicyReferenceSchema, { name: "policies/fixture" }],
  [TrainingRunSchema, { name: "trainingRuns/fixture" }],
  [TransformExecutionSchema, { name: "transformExecutions/fixture" }],
  [WorkflowDefinitionSchema, { name: "workflowDefinitions/fixture" }],
];

for (const [schema, initializer] of cases) {
  const original = create(schema, initializer);
  const wire = toBinary(schema, original);
  if (wire.byteLength === 0) {
    throw new Error(`${schema.typeName} encoded to no bytes`);
  }
  if (!equals(schema, fromBinary(schema, wire), original)) {
    throw new Error(`${schema.typeName} binary round trip mismatch`);
  }
  if (!equals(schema, fromJson(schema, toJson(schema, original)), original)) {
    throw new Error(`${schema.typeName} ProtoJSON round trip mismatch`);
  }
}
