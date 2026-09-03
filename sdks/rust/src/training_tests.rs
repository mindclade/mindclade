use std::{
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    artifact::v1::{ArtifactRef, EvidenceRef},
    common::v1::{CommandContext, PageRequest, PageResponse, ResourceRef},
    internal::training::v1::{
        CancelTrainingRunRequest, CancelTrainingRunResponse, CommitCheckpointRequest,
        CommitCheckpointResponse, CommitTrainingProgressRequest, CommitTrainingProgressResponse,
        CompleteTrainingRunRequest, CompleteTrainingRunResponse, CreateTrainingRunRequest,
        CreateTrainingRunResponse, GetCheckpointRequest, GetCheckpointResponse,
        GetTrainingRunRequest, GetTrainingRunResponse, ListCheckpointsRequest,
        ListCheckpointsResponse, ListTrainingRunsRequest, ListTrainingRunsResponse,
        PrepareCheckpointRequest, PrepareCheckpointResponse, ResumeTrainingAttemptRequest,
        ResumeTrainingAttemptResponse, StartTrainingAttemptRequest, StartTrainingAttemptResponse,
        WatchTrainingRunRequest, WatchTrainingRunResponse,
    },
    job::v1::LeaseFence,
    operation::v1::Operation,
    training::v1::{
        CancelTrainingRunCommand, Checkpoint, CommitCheckpointCommand,
        CommitTrainingProgressCommand, CompleteTrainingRunCommand, CreateTrainingRunCommand,
        PrepareCheckpointCommand, ResumeTrainingAttemptCommand, StartTrainingAttemptCommand,
        TrainingProgress, TrainingRun, TrainingRunState, TrainingTerminalClassification,
    },
};
use prost_types::Timestamp;
use tonic::{Request, Response, Status, codegen::async_trait};

use crate::{
    AccessToken, CallOptions, CancellationToken, Client, Config, Environment, Identity,
    RecordingTransport, RpcTransport, SubmitOptions, TokenProvider, TrainingStream,
    TrainingWatchOptions,
};

const PARENT: &str = "tenants/t-1/projects/p-1";
const RUN: &str = "tenants/t-1/projects/p-1/trainingRuns/run-1";
const CHECKPOINT: &str = "tenants/t-1/projects/p-1/trainingRuns/run-1/checkpoints/checkpoint-1";

#[derive(Default)]
struct TrainingTransport {
    contexts: Mutex<Vec<CommandContext>>,
    leases: Mutex<Vec<Option<String>>>,
}

impl TrainingTransport {
    fn record<T>(&self, request: &Request<T>, context: Option<&CommandContext>) {
        if let Some(value) = context {
            self.contexts.lock().unwrap().push(value.clone());
        }
        self.leases.lock().unwrap().push(
            request
                .metadata()
                .get("x-mindclade-lease-token")
                .and_then(|value| value.to_str().ok())
                .map(str::to_owned),
        );
    }
}

#[async_trait]
impl RpcTransport for TrainingTransport {
    async fn create_training_run(
        &self,
        request: Request<CreateTrainingRunRequest>,
    ) -> Result<Response<CreateTrainingRunResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(CreateTrainingRunResponse {
            operation: Some(Operation {
                operation_id: "operations/create-training".to_owned(),
                ..Operation::default()
            }),
        }))
    }

    async fn get_training_run(
        &self,
        request: Request<GetTrainingRunRequest>,
    ) -> Result<Response<GetTrainingRunResponse>, Status> {
        self.record(&request, None);
        let name = request.get_ref().name.clone();
        Ok(Response::new(GetTrainingRunResponse {
            training_run: Some(TrainingRun {
                name,
                uid: "run-uid".to_owned(),
                state: TrainingRunState::Running as i32,
                ..TrainingRun::default()
            }),
        }))
    }

    async fn list_training_runs(
        &self,
        request: Request<ListTrainingRunsRequest>,
    ) -> Result<Response<ListTrainingRunsResponse>, Status> {
        self.record(&request, None);
        assert_eq!(request.get_ref().parent, PARENT);
        Ok(Response::new(ListTrainingRunsResponse {
            training_runs: vec![run(TrainingRunState::Running)],
            page: Some(PageResponse {
                next_page_token: "next".to_owned(),
            }),
            read_time: None,
        }))
    }

    async fn start_training_attempt(
        &self,
        request: Request<StartTrainingAttemptRequest>,
    ) -> Result<Response<StartTrainingAttemptResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(StartTrainingAttemptResponse {
            training_run: Some(run(TrainingRunState::Running)),
        }))
    }

    async fn resume_training_attempt(
        &self,
        request: Request<ResumeTrainingAttemptRequest>,
    ) -> Result<Response<ResumeTrainingAttemptResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(ResumeTrainingAttemptResponse {
            training_run: Some(run(TrainingRunState::Running)),
        }))
    }

    async fn commit_training_progress(
        &self,
        request: Request<CommitTrainingProgressRequest>,
    ) -> Result<Response<CommitTrainingProgressResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(CommitTrainingProgressResponse {
            progress: Some(progress()),
            training_run: Some(run(TrainingRunState::Running)),
        }))
    }

    async fn prepare_checkpoint(
        &self,
        request: Request<PrepareCheckpointRequest>,
    ) -> Result<Response<PrepareCheckpointResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(PrepareCheckpointResponse {
            checkpoint: Some(checkpoint()),
        }))
    }

    async fn commit_checkpoint(
        &self,
        request: Request<CommitCheckpointRequest>,
    ) -> Result<Response<CommitCheckpointResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(CommitCheckpointResponse {
            checkpoint: Some(checkpoint()),
            training_run: Some(run(TrainingRunState::Running)),
        }))
    }

    async fn complete_training_run(
        &self,
        request: Request<CompleteTrainingRunRequest>,
    ) -> Result<Response<CompleteTrainingRunResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(CompleteTrainingRunResponse {
            training_run: Some(run(TrainingRunState::Completed)),
        }))
    }

    async fn cancel_training_run(
        &self,
        request: Request<CancelTrainingRunRequest>,
    ) -> Result<Response<CancelTrainingRunResponse>, Status> {
        self.record(
            &request,
            request
                .get_ref()
                .command
                .as_ref()
                .and_then(|v| v.context.as_ref()),
        );
        Ok(Response::new(CancelTrainingRunResponse {
            training_run: Some(run(TrainingRunState::Cancelled)),
        }))
    }

    async fn get_checkpoint(
        &self,
        request: Request<GetCheckpointRequest>,
    ) -> Result<Response<GetCheckpointResponse>, Status> {
        self.record(&request, None);
        Ok(Response::new(GetCheckpointResponse {
            checkpoint: Some(checkpoint()),
        }))
    }

    async fn list_checkpoints(
        &self,
        request: Request<ListCheckpointsRequest>,
    ) -> Result<Response<ListCheckpointsResponse>, Status> {
        self.record(&request, None);
        Ok(Response::new(ListCheckpointsResponse {
            checkpoints: vec![checkpoint()],
            page: None,
            read_time: None,
        }))
    }

    async fn watch_training_run(
        &self,
        request: Request<WatchTrainingRunRequest>,
    ) -> Result<Response<TrainingStream>, Status> {
        self.record(&request, None);
        let sequence = request.get_ref().after_sequence + 1;
        let stream: TrainingStream = Box::pin(tonic::codegen::tokio_stream::iter([Ok(
            WatchTrainingRunResponse {
                training_run: Some(run(TrainingRunState::Completed)),
                progress: Some(progress()),
                sequence,
                observed_at: None,
            },
        )]));
        Ok(Response::new(stream))
    }
}

struct TestTokenProvider;

#[async_trait]
impl TokenProvider for TestTokenProvider {
    async fn token(&self, _audience: &str) -> Result<AccessToken, crate::Error> {
        AccessToken::new(
            "short-lived-test-token",
            SystemTime::now() + Duration::from_mins(5),
        )
    }
}

fn client(transport: Arc<dyn RpcTransport>) -> Client {
    let identity = Identity::new("t-1", "p-1", "worker-1").unwrap();
    let provider: Arc<dyn TokenProvider> = Arc::new(TestTokenProvider);
    Client::with_transport(
        Config::builder(Environment::Development, identity, provider)
            .build()
            .unwrap(),
        transport,
    )
}

fn submit(key: &str) -> SubmitOptions {
    SubmitOptions::new(key).unwrap()
}

fn fenced(key: &str) -> SubmitOptions {
    submit(key).with_call_options(CallOptions::new().with_lease_token("opaque-lease").unwrap())
}

fn digest(character: char) -> String {
    format!("sha256:{}", character.to_string().repeat(64))
}

fn timestamp(offset: Duration) -> Timestamp {
    let value = SystemTime::now().duration_since(UNIX_EPOCH).unwrap() + offset;
    Timestamp {
        seconds: i64::try_from(value.as_secs()).unwrap(),
        nanos: i32::try_from(value.subsec_nanos()).unwrap(),
    }
}

fn fence() -> LeaseFence {
    LeaseFence {
        job_id: "jobs/j-1".to_owned(),
        run_id: "runs/r-1".to_owned(),
        attempt_id: "attempts/a-1".to_owned(),
        lease_epoch: 1,
        deadline: Some(timestamp(Duration::from_mins(5))),
        lease_token_digest: digest('a'),
        ..LeaseFence::default()
    }
}

fn reference(kind: &str, name: &str) -> ResourceRef {
    ResourceRef {
        resource_type: kind.to_owned(),
        name: name.to_owned(),
        ..ResourceRef::default()
    }
}

fn run(state: TrainingRunState) -> TrainingRun {
    TrainingRun {
        name: RUN.to_owned(),
        uid: "run-uid".to_owned(),
        state: state as i32,
        ..TrainingRun::default()
    }
}

fn progress() -> TrainingProgress {
    TrainingProgress {
        training_run_name: RUN.to_owned(),
        progress_revision: 1,
        ..TrainingProgress::default()
    }
}

fn checkpoint() -> Checkpoint {
    Checkpoint {
        name: CHECKPOINT.to_owned(),
        training_run_name: RUN.to_owned(),
        snapshot_epoch: 1,
        ..Checkpoint::default()
    }
}

fn artifact() -> ArtifactRef {
    ArtifactRef {
        digest: digest('b'),
        ..ArtifactRef::default()
    }
}

#[tokio::test]
async fn authoritative_training_resource_leaf_law() {
    let training = client(Arc::new(TrainingTransport::default())).training();
    for leaf in ["01", "A", "a.b_c~d-1"] {
        let name = format!("{PARENT}/trainingRuns/{leaf}");
        assert_eq!(
            training
                .get(&name, "", CallOptions::new())
                .await
                .unwrap()
                .name,
            name
        );
    }
    for leaf in [
        ".leading".to_owned(),
        "~leading".to_owned(),
        "\0control".to_owned(),
        "a".repeat(129),
    ] {
        let name = format!("{PARENT}/trainingRuns/{leaf}");
        assert!(training.get(name, "", CallOptions::new()).await.is_err());
    }
}

#[tokio::test]
#[allow(clippy::too_many_lines)]
async fn training_facade_covers_all_generated_routes_and_authority_metadata() {
    let inner = Arc::new(TrainingTransport::default());
    let recording = Arc::new(RecordingTransport::new(Arc::clone(&inner)));
    let training = client(recording.clone()).training();
    training
        .submit(CreateTrainingRunCommand::default(), submit("create"))
        .await
        .unwrap();
    training.get(RUN, "", CallOptions::new()).await.unwrap();
    assert_eq!(
        training
            .list_runs(
                ListTrainingRunsRequest {
                    page: Some(PageRequest {
                        page_size: 20,
                        page_token: "opaque".to_owned(),
                    }),
                    ..ListTrainingRunsRequest::default()
                },
                CallOptions::new(),
            )
            .unwrap()
            .next_page()
            .await
            .unwrap()
            .unwrap()
            .next_page_token(),
        "next"
    );
    training
        .start_attempt(
            StartTrainingAttemptCommand {
                training_run: Some(reference("training_run", RUN)),
                fence: Some(fence()),
                deadline: Some(timestamp(Duration::from_mins(5))),
                ..StartTrainingAttemptCommand::default()
            },
            fenced("start"),
        )
        .await
        .unwrap();
    training
        .resume_attempt(
            ResumeTrainingAttemptCommand {
                training_run: Some(reference("training_run", RUN)),
                checkpoint: Some(reference("checkpoint", CHECKPOINT)),
                fence: Some(fence()),
                deadline: Some(timestamp(Duration::from_mins(5))),
                ..ResumeTrainingAttemptCommand::default()
            },
            fenced("resume"),
        )
        .await
        .unwrap();
    training
        .commit_progress(
            CommitTrainingProgressCommand {
                training_run_name: RUN.to_owned(),
                fence: Some(fence()),
                progress: Some(progress()),
                ..CommitTrainingProgressCommand::default()
            },
            fenced("progress"),
        )
        .await
        .unwrap();
    training
        .prepare_checkpoint(
            PrepareCheckpointCommand {
                training_run_name: RUN.to_owned(),
                fence: Some(fence()),
                snapshot_epoch: 1,
                logical_state_descriptor: Some(artifact()),
                committed_progress: Some(progress()),
                ..PrepareCheckpointCommand::default()
            },
            fenced("prepare"),
        )
        .await
        .unwrap();
    training
        .commit_checkpoint(
            CommitCheckpointCommand {
                training_run_name: RUN.to_owned(),
                fence: Some(fence()),
                snapshot_epoch: 1,
                checkpoint_manifest: Some(artifact()),
                logical_state_descriptor: Some(artifact()),
                committed_progress: Some(progress()),
                verification_evidence: Some(EvidenceRef {
                    digest: digest('c'),
                    ..EvidenceRef::default()
                }),
                committed_at: Some(timestamp(Duration::ZERO)),
                ..CommitCheckpointCommand::default()
            },
            fenced("checkpoint"),
        )
        .await
        .unwrap();
    training
        .complete(
            CompleteTrainingRunCommand {
                training_run_name: RUN.to_owned(),
                fence: Some(fence()),
                classification: TrainingTerminalClassification::Succeeded as i32,
                completed_at: Some(timestamp(Duration::ZERO)),
                ..CompleteTrainingRunCommand::default()
            },
            fenced("complete"),
        )
        .await
        .unwrap();
    training
        .cancel(
            CancelTrainingRunCommand {
                training_run_name: RUN.to_owned(),
                etag: "etag".to_owned(),
                reason: "operator request".to_owned(),
                ..CancelTrainingRunCommand::default()
            },
            submit("cancel"),
        )
        .await
        .unwrap();
    training
        .get_checkpoint(CHECKPOINT, CallOptions::new())
        .await
        .unwrap();
    training
        .list_checkpoints(
            ListCheckpointsRequest {
                parent: RUN.to_owned(),
                ..ListCheckpointsRequest::default()
            },
            CallOptions::new(),
        )
        .unwrap()
        .next_page()
        .await
        .unwrap()
        .unwrap();
    let mut watch = training
        .watch(
            RUN,
            0,
            &TrainingWatchOptions::new(),
            CancellationToken::new(),
        )
        .unwrap();
    assert_eq!(watch.next().await.unwrap().unwrap().sequence, 1);

    let methods = recording
        .calls()
        .into_iter()
        .map(|call| call.method)
        .collect::<Vec<_>>();
    assert_eq!(methods.len(), 13);
    assert_eq!(
        methods.first().copied(),
        Some("/mindclade.internal.training.v1.TrainingService/CreateTrainingRun")
    );
    assert_eq!(
        methods.last().copied(),
        Some("/mindclade.internal.training.v1.TrainingService/WatchTrainingRun")
    );
    let contexts = inner.contexts.lock().unwrap();
    assert_eq!(contexts.len(), 8);
    assert!(contexts.iter().all(|value| value.tenant_id == "t-1"
        && value.project_id == "p-1"
        && value.principal_id == "worker-1"
        && value.canonical_request_digest.starts_with("sha256:")));
    let leases = inner.leases.lock().unwrap();
    assert!(
        leases[3..=8]
            .iter()
            .all(|value| value.as_deref() == Some("opaque-lease"))
    );
}

/// The uniform resume verb continues from the caller's durable sequence and
/// the stream adapter yields exactly the same update.
#[tokio::test]
async fn training_resume_watch_continues_from_a_supplied_sequence() {
    use tonic::codegen::tokio_stream::StreamExt as _;

    let transport = Arc::new(TrainingTransport::default());
    let client = client(Arc::clone(&transport) as Arc<dyn RpcTransport>);
    let mut watch = client
        .training()
        .resume_watch(
            RUN,
            41,
            &TrainingWatchOptions::new(),
            CancellationToken::new(),
        )
        .unwrap();
    let update = watch.next().await.unwrap().unwrap();
    assert_eq!(update.sequence, 42);
    assert_eq!(watch.last_sequence(), 42);
    assert!(watch.next().await.unwrap().is_none());

    let mut stream = client
        .training()
        .resume_watch(
            RUN,
            41,
            &TrainingWatchOptions::new(),
            CancellationToken::new(),
        )
        .unwrap()
        .into_stream();
    let streamed = stream.next().await.unwrap().unwrap();
    assert_eq!(streamed.sequence, 42);
    assert!(stream.next().await.is_none());
}

/// The uniform training wait verb returns the terminal generated run.
#[tokio::test]
async fn training_wait_returns_the_terminal_run() {
    let transport = Arc::new(TrainingTransport::default());
    let client = client(Arc::clone(&transport) as Arc<dyn RpcTransport>);
    let run = client
        .training()
        .wait(
            RUN,
            0,
            &TrainingWatchOptions::new(),
            CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(run.name, RUN);
    assert_eq!(run.state, TrainingRunState::Completed as i32);
}
