use std::{
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    artifact::v1::ArtifactRef,
    common::v1::{CommandContext, PageRequest, PageResponse},
    internal::job::v1::{
        AcquireAttemptLeaseRequest, AcquireAttemptLeaseResponse, CancelAttemptRequest,
        CancelAttemptResponse, CancelJobRequest, CancelJobResponse, CommitAttemptRequest,
        CommitAttemptResponse, GetAttemptRequest, GetAttemptResponse, GetJobRequest,
        GetJobResponse, GetRunRequest, GetRunResponse, HeartbeatAttemptRequest,
        HeartbeatAttemptResponse, ListAttemptsRequest, ListAttemptsResponse, ListJobsRequest,
        ListJobsResponse, ListRunsRequest, ListRunsResponse, RenewAttemptLeaseRequest,
        RenewAttemptLeaseResponse, RequestJobRequest, RequestJobResponse,
    },
    job::v1::{
        Attempt, AttemptState, Job, JobState, LeaseFence, Operation, OperationState,
        RequestJobCommand, Run, RunState,
    },
};
use prost::Message;
use prost_types::{FieldMask, Timestamp};
use sha2::{Digest, Sha256};
use tonic::{Request, Response, Status, codegen::async_trait, metadata::MetadataValue};

use crate::{
    AccessToken, CallOptions, Client, Config, Environment, Identity, LeaseCredential,
    RecordingTransport, RpcTransport, SubmitOptions, TokenProvider,
};

const TOKEN: &str = "opaque-worker-lease-capability-0123456789abcdef";
const TENANT: &str = "t-1";
const PROJECT: &str = "p-1";
const PARENT: &str = "tenants/t-1/projects/p-1";

#[derive(Default)]
struct JobRunTransport {
    methods: Mutex<Vec<&'static str>>,
    lease_headers: Mutex<Vec<String>>,
    contexts: Mutex<Vec<CommandContext>>,
}

impl JobRunTransport {
    fn mutation<T>(&self, method: &'static str, request: &Request<T>, context: &CommandContext) {
        self.methods.lock().unwrap().push(method);
        assert!(context.canonical_request_digest.starts_with("sha256:"));
        assert_eq!(context.tenant_id, TENANT);
        assert_eq!(context.project_id, PROJECT);
        self.contexts.lock().unwrap().push(context.clone());
        if let Some(value) = request
            .metadata()
            .get("x-mindclade-lease-token")
            .and_then(|value| value.to_str().ok())
        {
            self.lease_headers.lock().unwrap().push(value.to_owned());
        }
    }

    fn read(&self, method: &'static str) {
        self.methods.lock().unwrap().push(method);
    }
}

#[async_trait]
impl RpcTransport for JobRunTransport {
    async fn request_job(
        &self,
        request: Request<RequestJobRequest>,
    ) -> Result<Response<RequestJobResponse>, Status> {
        let context = request
            .get_ref()
            .command
            .as_ref()
            .and_then(|command| command.context.as_ref())
            .unwrap();
        self.mutation("RequestJob", &request, context);
        let mut unsigned = request.get_ref().command.clone().unwrap();
        unsigned.context = None;
        assert_eq!(context.canonical_request_digest, protobuf_digest(&unsigned));
        Ok(Response::new(RequestJobResponse {
            job: Some(job()),
            operation: Some(operation()),
        }))
    }

    async fn get_job(
        &self,
        request: Request<GetJobRequest>,
    ) -> Result<Response<GetJobResponse>, Status> {
        self.read("GetJob");
        assert_eq!(request.get_ref().name, "jobs/job-1");
        Ok(Response::new(GetJobResponse { job: Some(job()) }))
    }

    async fn list_jobs(
        &self,
        request: Request<ListJobsRequest>,
    ) -> Result<Response<ListJobsResponse>, Status> {
        self.read("ListJobs");
        assert_eq!(request.get_ref().parent, PARENT);
        Ok(Response::new(ListJobsResponse {
            jobs: vec![job()],
            page: Some(PageResponse {
                next_page_token: "jobs-next".to_owned(),
            }),
            read_time: None,
        }))
    }

    async fn cancel_job(
        &self,
        request: Request<CancelJobRequest>,
    ) -> Result<Response<CancelJobResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap();
        self.mutation("CancelJob", &request, context);
        verify_request_digest(request.get_ref(), context);
        Ok(Response::new(CancelJobResponse {
            operation: Some(operation()),
        }))
    }

    async fn get_run(
        &self,
        request: Request<GetRunRequest>,
    ) -> Result<Response<GetRunResponse>, Status> {
        self.read("GetRun");
        assert_eq!(request.get_ref().name, "runs/run-1");
        Ok(Response::new(GetRunResponse { run: Some(run()) }))
    }

    async fn list_runs(
        &self,
        request: Request<ListRunsRequest>,
    ) -> Result<Response<ListRunsResponse>, Status> {
        self.read("ListRuns");
        assert_eq!(request.get_ref().parent, "jobs/job-1");
        Ok(Response::new(ListRunsResponse {
            runs: vec![run()],
            page: Some(PageResponse {
                next_page_token: "runs-next".to_owned(),
            }),
            read_time: None,
        }))
    }

    async fn get_attempt(
        &self,
        request: Request<GetAttemptRequest>,
    ) -> Result<Response<GetAttemptResponse>, Status> {
        self.read("GetAttempt");
        assert_eq!(request.get_ref().name, "attempts/attempt-1");
        Ok(Response::new(GetAttemptResponse {
            attempt: Some(attempt(AttemptState::Leased)),
        }))
    }

    async fn list_attempts(
        &self,
        request: Request<ListAttemptsRequest>,
    ) -> Result<Response<ListAttemptsResponse>, Status> {
        self.read("ListAttempts");
        assert_eq!(request.get_ref().parent, "runs/run-1");
        Ok(Response::new(ListAttemptsResponse {
            attempts: vec![attempt(AttemptState::Leased)],
            page: Some(PageResponse {
                next_page_token: "attempts-next".to_owned(),
            }),
            read_time: None,
        }))
    }

    async fn acquire_attempt_lease(
        &self,
        request: Request<AcquireAttemptLeaseRequest>,
    ) -> Result<Response<AcquireAttemptLeaseResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap();
        self.mutation("AcquireAttemptLease", &request, context);
        assert!(request.metadata().get("x-mindclade-lease-token").is_none());
        verify_request_digest(request.get_ref(), context);
        let mut response = Response::new(AcquireAttemptLeaseResponse {
            attempt: Some(attempt(AttemptState::Leased)),
            fence: Some(fence()),
        });
        response.metadata_mut().insert(
            "x-mindclade-lease-token",
            MetadataValue::try_from(TOKEN).unwrap(),
        );
        Ok(response)
    }

    async fn renew_attempt_lease(
        &self,
        request: Request<RenewAttemptLeaseRequest>,
    ) -> Result<Response<RenewAttemptLeaseResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap();
        self.mutation("RenewAttemptLease", &request, context);
        verify_request_digest(request.get_ref(), context);
        Ok(Response::new(RenewAttemptLeaseResponse {
            attempt: Some(attempt(AttemptState::Leased)),
            fence: Some(fence()),
        }))
    }

    async fn heartbeat_attempt(
        &self,
        request: Request<HeartbeatAttemptRequest>,
    ) -> Result<Response<HeartbeatAttemptResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap();
        self.mutation("HeartbeatAttempt", &request, context);
        verify_request_digest(request.get_ref(), context);
        Ok(Response::new(HeartbeatAttemptResponse {
            attempt: Some(attempt(AttemptState::Leased)),
            fence: Some(fence()),
            observed_at: Some(now_timestamp()),
        }))
    }

    async fn cancel_attempt(
        &self,
        request: Request<CancelAttemptRequest>,
    ) -> Result<Response<CancelAttemptResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap();
        self.mutation("CancelAttempt", &request, context);
        verify_request_digest(request.get_ref(), context);
        Ok(Response::new(CancelAttemptResponse {
            attempt: Some(attempt(AttemptState::Cancelled)),
            run: Some(run()),
        }))
    }

    async fn commit_attempt(
        &self,
        request: Request<CommitAttemptRequest>,
    ) -> Result<Response<CommitAttemptResponse>, Status> {
        let context = request.get_ref().context.as_ref().unwrap();
        self.mutation("CommitAttempt", &request, context);
        verify_request_digest(request.get_ref(), context);
        Ok(Response::new(CommitAttemptResponse {
            attempt: Some(attempt(AttemptState::Succeeded)),
            run: Some(run()),
        }))
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
    let provider: Arc<dyn TokenProvider> = Arc::new(TestTokenProvider);
    Client::with_transport(
        Config::builder(
            Environment::Development,
            Identity::new(TENANT, PROJECT, "worker-1").unwrap(),
            provider,
        )
        .build()
        .unwrap(),
        transport,
    )
}

fn submit(key: &str) -> SubmitOptions {
    SubmitOptions::new(key).unwrap()
}

fn digest(value: &str) -> String {
    format!("sha256:{:x}", Sha256::digest(value.as_bytes()))
}

fn protobuf_digest(value: &impl Message) -> String {
    format!("sha256:{:x}", Sha256::digest(value.encode_to_vec()))
}

fn verify_request_digest<T>(request: &T, context: &CommandContext)
where
    T: Message + Clone + ClearContext,
{
    let mut unsigned = request.clone();
    unsigned.clear_context();
    assert_eq!(context.canonical_request_digest, protobuf_digest(&unsigned));
}

trait ClearContext {
    fn clear_context(&mut self);
}

macro_rules! clear_context {
    ($($request:ty),+ $(,)?) => {
        $(impl ClearContext for $request {
            fn clear_context(&mut self) {
                self.context = None;
            }
        })+
    };
}

clear_context!(
    CancelJobRequest,
    AcquireAttemptLeaseRequest,
    RenewAttemptLeaseRequest,
    HeartbeatAttemptRequest,
    CancelAttemptRequest,
    CommitAttemptRequest,
);

fn artifact() -> ArtifactRef {
    ArtifactRef {
        digest: digest("configuration"),
        media_type: "application/vnd.mindclade.training+json".to_owned(),
        size_bytes: 42,
        ..ArtifactRef::default()
    }
}

fn job() -> Job {
    Job {
        job_id: "jobs/job-1".to_owned(),
        operation_id: "operations/operation-1".to_owned(),
        tenant_id: TENANT.to_owned(),
        project_id: PROJECT.to_owned(),
        state: JobState::Accepted as i32,
        resource_version: 1,
        ..Job::default()
    }
}

fn operation() -> Operation {
    Operation {
        operation_id: "operations/operation-1".to_owned(),
        job_id: "jobs/job-1".to_owned(),
        tenant_id: TENANT.to_owned(),
        project_id: PROJECT.to_owned(),
        state: OperationState::Pending as i32,
        resource_version: 1,
        ..Operation::default()
    }
}

fn run() -> Run {
    Run {
        run_id: "runs/run-1".to_owned(),
        job_id: "jobs/job-1".to_owned(),
        tenant_id: TENANT.to_owned(),
        project_id: PROJECT.to_owned(),
        state: RunState::Executing as i32,
        resource_version: 1,
        lease_epoch: 1,
        ..Run::default()
    }
}

fn attempt(state: AttemptState) -> Attempt {
    Attempt {
        attempt_id: "attempts/attempt-1".to_owned(),
        run_id: "runs/run-1".to_owned(),
        job_id: "jobs/job-1".to_owned(),
        tenant_id: TENANT.to_owned(),
        project_id: PROJECT.to_owned(),
        state: state as i32,
        lease_epoch: 1,
        resource_version: 1,
        ..Attempt::default()
    }
}

fn fence() -> LeaseFence {
    LeaseFence {
        job_id: "jobs/job-1".to_owned(),
        run_id: "runs/run-1".to_owned(),
        attempt_id: "attempts/attempt-1".to_owned(),
        lease_epoch: 1,
        deadline: Some(future_timestamp()),
        tenant_id: TENANT.to_owned(),
        project_id: PROJECT.to_owned(),
        lease_token_digest: digest(TOKEN),
    }
}

fn now_timestamp() -> Timestamp {
    timestamp(SystemTime::now())
}

fn future_timestamp() -> Timestamp {
    timestamp(SystemTime::now() + Duration::from_mins(5))
}

fn timestamp(value: SystemTime) -> Timestamp {
    let value = value.duration_since(UNIX_EPOCH).unwrap();
    Timestamp {
        seconds: i64::try_from(value.as_secs()).unwrap(),
        nanos: i32::try_from(value.subsec_nanos()).unwrap(),
    }
}

#[tokio::test]
#[allow(clippy::too_many_lines)] // One end-to-end narrative proves the exact thirteen-RPC surface.
async fn job_and_run_facades_cover_every_ergonomic_rpc_and_hide_lease_tokens() {
    let inner = Arc::new(JobRunTransport::default());
    let recording = Arc::new(RecordingTransport::new(Arc::clone(&inner)));
    let sdk = client(recording.clone());

    let (job, operation) = sdk
        .jobs()
        .request(
            RequestJobCommand {
                context: Some(CommandContext {
                    tenant_id: "forged".to_owned(),
                    ..CommandContext::default()
                }),
                job_kind: "training".to_owned(),
                configuration: Some(artifact()),
                requested_job_id: "job-1".to_owned(),
                ..RequestJobCommand::default()
            },
            submit("request-job"),
        )
        .await
        .unwrap();
    assert_eq!(job.operation_id, operation.operation_id);
    sdk.jobs()
        .get("job-1", "", CallOptions::new())
        .await
        .unwrap();
    sdk.jobs()
        .list(
            ListJobsRequest {
                page: Some(PageRequest {
                    page_size: 25,
                    page_token: "jobs-token".to_owned(),
                }),
                ..ListJobsRequest::default()
            },
            CallOptions::new(),
        )
        .unwrap()
        .next_page()
        .await
        .unwrap()
        .unwrap();
    sdk.jobs()
        .cancel(
            CancelJobRequest {
                name: "job-1".to_owned(),
                etag: "etag-1".to_owned(),
                reason: "test".to_owned(),
                ..CancelJobRequest::default()
            },
            submit("cancel-job"),
        )
        .await
        .unwrap();

    sdk.runs()
        .get_run("run-1", CallOptions::new())
        .await
        .unwrap();
    sdk.runs()
        .list_runs(
            ListRunsRequest {
                parent: "job-1".to_owned(),
                ..ListRunsRequest::default()
            },
            CallOptions::new(),
        )
        .unwrap()
        .next_page()
        .await
        .unwrap()
        .unwrap();
    sdk.runs()
        .get_attempt("attempt-1", CallOptions::new())
        .await
        .unwrap();
    sdk.runs()
        .list_attempts(
            ListAttemptsRequest {
                parent: "run-1".to_owned(),
                ..ListAttemptsRequest::default()
            },
            CallOptions::new(),
        )
        .unwrap()
        .next_page()
        .await
        .unwrap()
        .unwrap();

    let acquired = sdk
        .runs()
        .acquire(
            AcquireAttemptLeaseRequest {
                run_name: "run-1".to_owned(),
                attempt_id: "attempt-1".to_owned(),
                lease_duration: Some(prost_types::Duration {
                    seconds: 120,
                    nanos: 0,
                }),
                ..AcquireAttemptLeaseRequest::default()
            },
            submit("acquire"),
        )
        .await
        .unwrap();
    assert_eq!(
        format!("{:?}", acquired.credential()),
        "LeaseCredential([REDACTED])"
    );
    assert!(!format!("{}", acquired.credential()).contains(TOKEN));
    let mut detached_attempt = acquired.attempt();
    detached_attempt.attempt_id = "attempts/tampered".to_owned();
    assert_eq!(acquired.attempt().attempt_id, "attempts/attempt-1");
    let credential: LeaseCredential = acquired.credential();
    let request_fence = acquired.fence();

    sdk.runs()
        .renew(
            RenewAttemptLeaseRequest {
                fence: Some(request_fence.clone()),
                lease_duration: Some(prost_types::Duration {
                    seconds: 120,
                    nanos: 0,
                }),
                expected_resource_version: 1,
                ..RenewAttemptLeaseRequest::default()
            },
            &credential,
            submit("renew"),
        )
        .await
        .unwrap();
    sdk.runs()
        .heartbeat(
            HeartbeatAttemptRequest {
                fence: Some(request_fence.clone()),
                lease_duration: Some(prost_types::Duration {
                    seconds: 120,
                    nanos: 0,
                }),
                expected_resource_version: 1,
                ..HeartbeatAttemptRequest::default()
            },
            &credential,
            submit("heartbeat"),
        )
        .await
        .unwrap();
    sdk.runs()
        .cancel_attempt(
            CancelAttemptRequest {
                fence: Some(request_fence.clone()),
                expected_resource_version: 1,
                reason: "worker shutdown".to_owned(),
                ..CancelAttemptRequest::default()
            },
            &credential,
            submit("cancel-attempt"),
        )
        .await
        .unwrap();
    sdk.runs()
        .commit_attempt(
            CommitAttemptRequest {
                attempt: Some(attempt(AttemptState::Succeeded)),
                fence: Some(request_fence),
                update_mask: Some(FieldMask {
                    paths: vec!["state".to_owned()],
                }),
                expected_resource_version: 1,
                ..CommitAttemptRequest::default()
            },
            &credential,
            submit("commit"),
        )
        .await
        .unwrap();

    assert_eq!(
        *inner.methods.lock().unwrap(),
        [
            "RequestJob",
            "GetJob",
            "ListJobs",
            "CancelJob",
            "GetRun",
            "ListRuns",
            "GetAttempt",
            "ListAttempts",
            "AcquireAttemptLease",
            "RenewAttemptLease",
            "HeartbeatAttempt",
            "CancelAttempt",
            "CommitAttempt",
        ]
    );
    assert_eq!(inner.lease_headers.lock().unwrap().as_slice(), [TOKEN; 4]);
    assert!(recording.calls().iter().all(|call| {
        call.method != "/mindclade.internal.job.v1.RunService/ExpireAttemptLeases"
    }));
}
