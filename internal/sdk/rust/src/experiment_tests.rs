use std::{
    sync::{Arc, Mutex},
    time::{Duration, SystemTime},
};

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    common::v1::{PageRequest, PageResponse, ResourceRef},
    experiment::v1::{
        CompleteTrialCommand, CreateExperimentCommand, CreateStudyCommand, CreateTrialCommand,
        Experiment, ExperimentKind, ExperimentState, Study, StudyBudget, StudyState, StudyType,
        TransitionExperimentCommand, TransitionStudyCommand, TransitionTrialCommand, Trial,
        TrialOutcome, TrialState, UpdateExperimentCommand,
    },
    internal::experiment::v1::*,
};
use prost_types::{Duration as ProtoDuration, FieldMask};
use tonic::{Request, Response, Status, codegen::async_trait};

use crate::{
    AccessToken, CallOptions, Client, Config, Environment, Identity, RpcTransport, SubmitOptions,
    TokenProvider,
};

const PARENT: &str = "tenants/t-1/projects/p-1";
const EXPERIMENT: &str = "tenants/t-1/projects/p-1/experiments/experiment-1";
const STUDY: &str = "tenants/t-1/projects/p-1/experiments/experiment-1/studies/study-1";
const TRIAL: &str =
    "tenants/t-1/projects/p-1/experiments/experiment-1/studies/study-1/trials/trial-1";

#[derive(Default)]
struct ExperimentTransport {
    calls: Mutex<Vec<&'static str>>,
}

impl ExperimentTransport {
    fn record(&self, method: &'static str) {
        self.calls.lock().unwrap().push(method);
    }
}

#[async_trait]
impl RpcTransport for ExperimentTransport {
    async fn create_experiment(
        &self,
        request: Request<CreateExperimentRequest>,
    ) -> Result<Response<CreateExperimentResponse>, Status> {
        self.record("CreateExperiment");
        assert!(request.metadata().get("x-request-id").is_some());
        assert!(request.metadata().get("x-mindclade-request-id").is_none());
        assert!(
            request
                .get_ref()
                .command
                .as_ref()
                .unwrap()
                .context
                .is_some()
        );
        Ok(Response::new(CreateExperimentResponse {
            experiment: Some(experiment()),
        }))
    }
    async fn get_experiment(
        &self,
        request: Request<GetExperimentRequest>,
    ) -> Result<Response<GetExperimentResponse>, Status> {
        self.record("GetExperiment");
        Ok(Response::new(GetExperimentResponse {
            experiment: Some(Experiment {
                name: request.into_inner().name,
                ..Default::default()
            }),
        }))
    }
    async fn list_experiments(
        &self,
        request: Request<ListExperimentsRequest>,
    ) -> Result<Response<ListExperimentsResponse>, Status> {
        self.record("ListExperiments");
        assert_eq!(request.get_ref().parent, PARENT);
        Ok(Response::new(ListExperimentsResponse {
            experiments: vec![experiment()],
            page: Some(PageResponse {
                next_page_token: "next".into(),
            }),
            read_time: None,
        }))
    }
    async fn update_experiment(
        &self,
        _: Request<UpdateExperimentRequest>,
    ) -> Result<Response<UpdateExperimentResponse>, Status> {
        self.record("UpdateExperiment");
        Ok(Response::new(UpdateExperimentResponse {
            experiment: Some(experiment()),
        }))
    }
    async fn transition_experiment(
        &self,
        _: Request<TransitionExperimentRequest>,
    ) -> Result<Response<TransitionExperimentResponse>, Status> {
        self.record("TransitionExperiment");
        Ok(Response::new(TransitionExperimentResponse {
            experiment: Some(experiment()),
        }))
    }
    async fn create_study(
        &self,
        _: Request<CreateStudyRequest>,
    ) -> Result<Response<CreateStudyResponse>, Status> {
        self.record("CreateStudy");
        Ok(Response::new(CreateStudyResponse {
            study: Some(study()),
        }))
    }
    async fn get_study(
        &self,
        request: Request<GetStudyRequest>,
    ) -> Result<Response<GetStudyResponse>, Status> {
        self.record("GetStudy");
        Ok(Response::new(GetStudyResponse {
            study: Some(Study {
                name: request.into_inner().name,
                ..Default::default()
            }),
        }))
    }
    async fn list_studies(
        &self,
        _: Request<ListStudiesRequest>,
    ) -> Result<Response<ListStudiesResponse>, Status> {
        self.record("ListStudies");
        Ok(Response::new(ListStudiesResponse {
            studies: vec![study()],
            page: Some(PageResponse {
                next_page_token: "next".into(),
            }),
            read_time: None,
        }))
    }
    async fn transition_study(
        &self,
        _: Request<TransitionStudyRequest>,
    ) -> Result<Response<TransitionStudyResponse>, Status> {
        self.record("TransitionStudy");
        Ok(Response::new(TransitionStudyResponse {
            study: Some(study()),
        }))
    }
    async fn create_trial(
        &self,
        _: Request<CreateTrialRequest>,
    ) -> Result<Response<CreateTrialResponse>, Status> {
        self.record("CreateTrial");
        Ok(Response::new(CreateTrialResponse {
            trial: Some(trial()),
        }))
    }
    async fn get_trial(
        &self,
        request: Request<GetTrialRequest>,
    ) -> Result<Response<GetTrialResponse>, Status> {
        self.record("GetTrial");
        Ok(Response::new(GetTrialResponse {
            trial: Some(Trial {
                name: request.into_inner().name,
                ..Default::default()
            }),
        }))
    }
    async fn list_trials(
        &self,
        _: Request<ListTrialsRequest>,
    ) -> Result<Response<ListTrialsResponse>, Status> {
        self.record("ListTrials");
        Ok(Response::new(ListTrialsResponse {
            trials: vec![trial()],
            page: Some(PageResponse {
                next_page_token: "next".into(),
            }),
            read_time: None,
        }))
    }
    async fn transition_trial(
        &self,
        _: Request<TransitionTrialRequest>,
    ) -> Result<Response<TransitionTrialResponse>, Status> {
        self.record("TransitionTrial");
        Ok(Response::new(TransitionTrialResponse {
            trial: Some(trial()),
        }))
    }
    async fn complete_trial(
        &self,
        _: Request<CompleteTrialRequest>,
    ) -> Result<Response<CompleteTrialResponse>, Status> {
        self.record("CompleteTrial");
        Ok(Response::new(CompleteTrialResponse {
            trial: Some(trial()),
        }))
    }
}

struct TestToken;
#[async_trait]
impl TokenProvider for TestToken {
    async fn token(&self, _: &str) -> Result<AccessToken, crate::Error> {
        AccessToken::new("test-token", SystemTime::now() + Duration::from_mins(5))
    }
}

fn client(transport: Arc<dyn RpcTransport>) -> Client {
    Client::with_transport(
        Config::builder(
            Environment::Development,
            Identity::new("t-1", "p-1", "principal-1").unwrap(),
            Arc::new(TestToken),
        )
        .build()
        .unwrap(),
        transport,
    )
}
fn submit(value: &str) -> SubmitOptions {
    SubmitOptions::new(value).unwrap()
}
fn digest(seed: char) -> String {
    format!("sha256:{}", seed.to_string().repeat(64))
}
fn artifact(seed: char) -> ArtifactRef {
    ArtifactRef {
        digest: digest(seed),
        integrity_digest: digest(seed),
        media_type: "application/json".into(),
        size_bytes: 7,
        ..Default::default()
    }
}
fn reference(kind: &str, name: &str) -> ResourceRef {
    ResourceRef {
        resource_type: kind.into(),
        resource_id: name.rsplit('/').next().unwrap().into(),
        tenant_id: "t-1".into(),
        project_id: "p-1".into(),
        resource_version: 1,
        name: name.into(),
        etag: digest('e'),
    }
}
fn experiment() -> Experiment {
    Experiment {
        name: EXPERIMENT.into(),
        revision: 1,
        etag: digest('e'),
        ..Default::default()
    }
}
fn study() -> Study {
    Study {
        name: STUDY.into(),
        revision: 1,
        etag: digest('e'),
        ..Default::default()
    }
}
fn trial() -> Trial {
    Trial {
        name: TRIAL.into(),
        revision: 1,
        etag: digest('e'),
        ..Default::default()
    }
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one exhaustive conformance path proves all fourteen generated experiment RPC routes"
)]
async fn all_fourteen_generated_experiment_rpcs_are_routed_through_the_facade() {
    let transport = Arc::new(ExperimentTransport::default());
    let sdk = client(transport.clone()).experiments();
    sdk.create(
        CreateExperimentCommand {
            experiment_id: "experiment-1".into(),
            display_name: "Experiment".into(),
            kind: ExperimentKind::Scientific as i32,
            intent_manifest: Some(artifact('a')),
            subjects: vec![reference("dataset", &format!("{PARENT}/datasets/d-1"))],
            use_policy: Some(reference("use_policy", &format!("{PARENT}/policies/p-1"))),
            policy_classification: "internal".into(),
            ..Default::default()
        },
        submit("experiment-create"),
    )
    .await
    .unwrap();
    sdk.get(EXPERIMENT, "", CallOptions::new()).await.unwrap();
    sdk.list(
        ListExperimentsRequest {
            page: Some(PageRequest {
                page_size: 10,
                page_token: "opaque".into(),
            }),
            ..Default::default()
        },
        CallOptions::new(),
    )
    .await
    .unwrap();
    sdk.update(
        UpdateExperimentCommand {
            experiment: Some(Experiment {
                name: EXPERIMENT.into(),
                revision: 1,
                etag: digest('e'),
                display_name: "Updated".into(),
                ..Default::default()
            }),
            update_mask: Some(FieldMask {
                paths: vec!["display_name".into()],
            }),
            etag: digest('e'),
            ..Default::default()
        },
        submit("experiment-update"),
    )
    .await
    .unwrap();
    sdk.transition(
        TransitionExperimentCommand {
            experiment: Some(reference("experiment", EXPERIMENT)),
            expected_state: ExperimentState::Draft as i32,
            target_state: ExperimentState::Active as i32,
            etag: digest('e'),
            reason_code: "APPROVED".into(),
            ..Default::default()
        },
        submit("experiment-transition"),
    )
    .await
    .unwrap();
    sdk.create_study(
        CreateStudyCommand {
            experiment: Some(reference("experiment", EXPERIMENT)),
            study_id: "study-1".into(),
            r#type: StudyType::Scientific as i32,
            study_manifest: Some(artifact('b')),
            base_configuration: Some(artifact('c')),
            search_space: Some(artifact('d')),
            objective_specification: Some(artifact('f')),
            budget: Some(StudyBudget {
                maximum_trials: 8,
                maximum_parallel_trials: 2,
                maximum_duration: Some(ProtoDuration {
                    seconds: 3600,
                    nanos: 0,
                }),
            }),
            ..Default::default()
        },
        submit("study-create"),
    )
    .await
    .unwrap();
    sdk.get_study(STUDY, "", CallOptions::new()).await.unwrap();
    sdk.list_studies(
        ListStudiesRequest {
            parent: EXPERIMENT.into(),
            page: Some(PageRequest {
                page_size: 10,
                page_token: "opaque".into(),
            }),
            ..Default::default()
        },
        CallOptions::new(),
    )
    .await
    .unwrap();
    sdk.transition_study(
        TransitionStudyCommand {
            study: Some(reference("study", STUDY)),
            expected_state: StudyState::Created as i32,
            target_state: StudyState::Running as i32,
            etag: digest('e'),
            reason_code: "STARTED".into(),
            ..Default::default()
        },
        submit("study-transition"),
    )
    .await
    .unwrap();
    sdk.create_trial(
        CreateTrialCommand {
            study: Some(reference("study", STUDY)),
            trial_id: "trial-1".into(),
            trial_number: 1,
            resolved_configuration: Some(artifact('1')),
            ..Default::default()
        },
        submit("trial-create"),
    )
    .await
    .unwrap();
    sdk.get_trial(TRIAL, "", CallOptions::new()).await.unwrap();
    sdk.list_trials(
        ListTrialsRequest {
            parent: STUDY.into(),
            page: Some(PageRequest {
                page_size: 10,
                page_token: "opaque".into(),
            }),
            ..Default::default()
        },
        CallOptions::new(),
    )
    .await
    .unwrap();
    sdk.transition_trial(
        TransitionTrialCommand {
            trial: Some(reference("trial", TRIAL)),
            expected_state: TrialState::Created as i32,
            target_state: TrialState::Admitted as i32,
            etag: digest('e'),
            reason_code: "ADMITTED".into(),
            ..Default::default()
        },
        submit("trial-transition"),
    )
    .await
    .unwrap();
    sdk.complete_trial(
        CompleteTrialCommand {
            trial: Some(reference("trial", TRIAL)),
            outcome: TrialOutcome::Succeeded as i32,
            result_manifest: Some(artifact('2')),
            etag: digest('e'),
            ..Default::default()
        },
        submit("trial-complete"),
    )
    .await
    .unwrap();
    assert_eq!(transport.calls.lock().unwrap().len(), 14);
}

#[tokio::test]
async fn scope_and_bounded_pagination_fail_before_transport() {
    let transport = Arc::new(ExperimentTransport::default());
    let sdk = client(transport.clone()).experiments();
    assert!(
        sdk.get(
            "tenants/other/projects/other/experiments/nope",
            "",
            CallOptions::new()
        )
        .await
        .is_err()
    );
    assert!(
        sdk.list(
            ListExperimentsRequest {
                page: Some(PageRequest {
                    page_size: 201,
                    ..Default::default()
                }),
                ..Default::default()
            },
            CallOptions::new()
        )
        .await
        .is_err()
    );
    assert!(transport.calls.lock().unwrap().is_empty());
}
