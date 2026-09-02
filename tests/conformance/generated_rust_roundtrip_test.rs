use std::fmt::Debug;

use mindclade_protocols as protocols;
use prost::Message;

fn assert_wire_round_trip<M>(message: M)
where
    M: Message + Default + PartialEq + Debug,
{
    let wire = message.encode_to_vec();
    assert!(
        !wire.is_empty(),
        "representative message encoded to no bytes"
    );
    let decoded = M::decode(wire.as_slice()).expect("decode representative message");
    assert_eq!(message, decoded);
}

#[test]
fn every_generated_rust_package_round_trips_a_representative_message() {
    assert_wire_round_trip(protocols::admin::v1::Tenant {
        name: "tenants/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::agent::v1::AgentDefinition {
        name: "agentDefinitions/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::api::v1::Operation {
        name: "operations/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::artifact::v1::ArtifactRef {
        digest: "sha256:fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::common::v1::Identifiers {
        tenant_id: "tenant-fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::dataset::v1::Dataset {
        name: "datasets/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::evaluation::v1::EvaluationRun {
        name: "evaluationRuns/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::experiment::v1::ExperimentCreated {
        experiment_name: "experiments/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::agent::v1::AgentRunCompleted {
        attempt_id: "attempt-fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::artifact::v1::ArtifactCommitted {
        producer_attempt_id: "attempt-fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::audit::v1::AuditEvent {
        actor_principal_id: "principal-fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::feature::v1::FeatureMaterializationCompleted {
        materialization_name: "featureMaterializations/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::job::v1::JobRequested {
        job_id: "job-fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::model::v1::ModelRegistered {
        model_name: "models/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::training::v1::TrainingStarted {
        training_run_name: "trainingRuns/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::transform::v1::TransformExecutionCompleted {
        execution_name: "transformExecutions/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::workflow::v1::WorkflowTransitioned {
        transition_reason_code: "fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::experiment::v1::Experiment {
        name: "experiments/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::feature::v1::FeatureMaterialization {
        name: "featureMaterializations/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::inference::v1::InferenceRequest {
        name: "inferenceRequests/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::internal::admin::v1::GetTenantRequest {
        name: "tenants/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::internal::agent::v1::GetAgentDefinitionRequest {
        name: "agentDefinitions/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::internal::artifact::v1::GetArtifactRequest {
        name: "artifacts/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::internal::dataset::v1::GetDatasetRequest {
        name: "datasets/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(
        protocols::internal::evaluation::v1::GetEvaluationRunRequest {
            name: "evaluationRuns/fixture".into(),
            ..Default::default()
        },
    );
    assert_wire_round_trip(protocols::internal::experiment::v1::GetExperimentRequest {
        name: "experiments/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(
        protocols::internal::inference::v1::GetInferenceResultRequest {
            operation_name: "operations/fixture".into(),
        },
    );
    assert_wire_round_trip(protocols::internal::job::v1::GetJobRequest {
        name: "jobs/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::internal::model::v1::GetModelRequest {
        name: "models/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::internal::policy::v1::GetUsePolicyRequest {
        name: "policies/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::internal::training::v1::GetTrainingRunRequest {
        name: "trainingRuns/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(
        protocols::internal::workflow::v1::GetWorkflowDefinitionRequest {
            name: "workflowDefinitions/fixture".into(),
            ..Default::default()
        },
    );
    assert_wire_round_trip(protocols::job::v1::Job {
        job_id: "job-fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::model::v1::Model {
        name: "models/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::policy::v1::PolicyReference {
        name: "policies/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::training::v1::TrainingRun {
        name: "trainingRuns/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::transform::v1::TransformExecution {
        name: "transformExecutions/fixture".into(),
        ..Default::default()
    });
    assert_wire_round_trip(protocols::workflow::v1::WorkflowDefinition {
        name: "workflowDefinitions/fixture".into(),
        ..Default::default()
    });
}

#[test]
fn every_json_schema_fixture_has_native_rust_conformance() {
    protocols::schema::v1::assert_fixture_conformance()
        .expect("all generated JSON Schema fixtures must agree in Rust");
}

#[test]
fn generated_event_registry_enforces_exact_identity_and_activation_state() {
    let registration = protocols::event_registry::require_event_registration(
        "mindclade.events.job.v1.JobRequested",
        1,
        "application/x-protobuf; deterministic=true",
    )
    .expect("registered JobRequested identity");
    assert_eq!(registration.lifecycle_state, "active");
    assert_eq!(registration.compatibility_policy, "exact-version");
    assert!(!registration.producers.is_empty());
    assert!(!registration.consumers.is_empty());
    assert!(!protocols::event_registry::EVENT_REGISTRY_RATIFIABLE);
    assert!(protocols::event_registry::require_event_registration(
        "mindclade.events.job.v1.JobRequested",
        2,
        "application/x-protobuf; deterministic=true",
    )
    .is_err());
}
