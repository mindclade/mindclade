use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicI32, AtomicUsize, Ordering},
    },
    time::{Duration, SystemTime},
};

use mindclade_protocols::{
    common::v1::{PageRequest, ResourceRef},
    internal::workflow::v1::{
        CancelWorkflowRunRequest, CancelWorkflowRunResponse, CommitWorkflowTransitionRequest,
        CommitWorkflowTransitionResponse, ConsumeApprovalRequest, ConsumeApprovalResponse,
        CreateWorkflowDefinitionRequest, CreateWorkflowDefinitionResponse, DecideApprovalRequest,
        DecideApprovalResponse, GetApprovalRequestRequest, GetApprovalRequestResponse,
        GetWorkflowDefinitionRequest, GetWorkflowDefinitionResponse, GetWorkflowRunRequest,
        GetWorkflowRunResponse, ListApprovalRequestsRequest, ListApprovalRequestsResponse,
        ListWorkflowDefinitionsRequest, ListWorkflowDefinitionsResponse, ListWorkflowRunsRequest,
        ListWorkflowRunsResponse, RequestApprovalRequest, RequestApprovalResponse,
        StartWorkflowRunRequest, StartWorkflowRunResponse, UpdateWorkflowDefinitionRequest,
        UpdateWorkflowDefinitionResponse, WatchWorkflowRunRequest, WatchWorkflowRunResponse,
    },
    job::v1::{LeaseFence, Operation},
    workflow::v1::{
        ApprovalBinding, ApprovalDecisionValue, ApprovalReceipt, ApprovalRequest,
        WorkflowDefinition, WorkflowRun, WorkflowRunState,
    },
};
use prost::Message;
use prost_types::{FieldMask, Timestamp};
use sha2::{Digest, Sha256};
use tonic::{
    Request, Response, Status,
    codegen::{async_trait, tokio_stream},
};

use crate::{
    AccessToken, CallOptions, CancellationToken, Client, Config, Environment, Identity,
    RpcTransport, SubmitOptions, TokenProvider, WorkflowStream, WorkflowWatchOptions,
};

const PARENT: &str = "tenants/t-1/projects/p-1";
const DEFINITION: &str = "tenants/t-1/projects/p-1/workflowDefinitions/definition-1";
const RUN: &str = "tenants/t-1/projects/p-1/workflowRuns/run-1";
const APPROVAL: &str = "tenants/t-1/projects/p-1/approvalRequests/approval-1";
const RECEIPT: &str = "tenants/t-1/projects/p-1/approvalReceipts/receipt-1";

#[derive(Default)]
struct WorkflowTransport {
    methods: Mutex<Vec<&'static str>>,
    watch_calls: AtomicUsize,
    terminal_state: AtomicI32,
    lease_seen: Mutex<Vec<bool>>,
}

impl WorkflowTransport {
    fn record<T>(&self, method: &'static str, request: &Request<T>) {
        self.methods.lock().unwrap().push(method);
        self.lease_seen
            .lock()
            .unwrap()
            .push(request.metadata().get("x-mindclade-lease-token").is_some());
    }
}

fn operation() -> Operation {
    Operation {
        operation_id: "operations/workflow-1".to_owned(),
        ..Operation::default()
    }
}
fn run(sequence: u64, state: WorkflowRunState) -> WorkflowRun {
    WorkflowRun {
        name: RUN.to_owned(),
        tenant_id: "tenants/t-1".to_owned(),
        project_id: "projects/p-1".to_owned(),
        transition_sequence: sequence,
        state: state as i32,
        etag: "etag-1".to_owned(),
        ..WorkflowRun::default()
    }
}

#[async_trait]
impl RpcTransport for WorkflowTransport {
    async fn create_workflow_definition(
        &self,
        request: Request<CreateWorkflowDefinitionRequest>,
    ) -> Result<Response<CreateWorkflowDefinitionResponse>, Status> {
        self.record("CreateWorkflowDefinition", &request);
        Ok(Response::new(CreateWorkflowDefinitionResponse {
            operation: Some(operation()),
        }))
    }
    async fn update_workflow_definition(
        &self,
        request: Request<UpdateWorkflowDefinitionRequest>,
    ) -> Result<Response<UpdateWorkflowDefinitionResponse>, Status> {
        self.record("UpdateWorkflowDefinition", &request);
        Ok(Response::new(UpdateWorkflowDefinitionResponse {
            operation: Some(operation()),
        }))
    }
    async fn get_workflow_definition(
        &self,
        request: Request<GetWorkflowDefinitionRequest>,
    ) -> Result<Response<GetWorkflowDefinitionResponse>, Status> {
        self.record("GetWorkflowDefinition", &request);
        Ok(Response::new(GetWorkflowDefinitionResponse {
            workflow_definition: Some(WorkflowDefinition {
                name: request.into_inner().name,
                ..WorkflowDefinition::default()
            }),
        }))
    }
    async fn list_workflow_definitions(
        &self,
        request: Request<ListWorkflowDefinitionsRequest>,
    ) -> Result<Response<ListWorkflowDefinitionsResponse>, Status> {
        self.record("ListWorkflowDefinitions", &request);
        assert_eq!(
            request.get_ref().page.as_ref().unwrap().page_token,
            "opaque-definition"
        );
        Ok(Response::new(ListWorkflowDefinitionsResponse::default()))
    }
    async fn start_workflow_run(
        &self,
        request: Request<StartWorkflowRunRequest>,
    ) -> Result<Response<StartWorkflowRunResponse>, Status> {
        self.record("StartWorkflowRun", &request);
        Ok(Response::new(StartWorkflowRunResponse {
            operation: Some(operation()),
        }))
    }
    async fn get_workflow_run(
        &self,
        request: Request<GetWorkflowRunRequest>,
    ) -> Result<Response<GetWorkflowRunResponse>, Status> {
        self.record("GetWorkflowRun", &request);
        Ok(Response::new(GetWorkflowRunResponse {
            workflow_run: Some(run(0, WorkflowRunState::Running)),
        }))
    }
    async fn list_workflow_runs(
        &self,
        request: Request<ListWorkflowRunsRequest>,
    ) -> Result<Response<ListWorkflowRunsResponse>, Status> {
        self.record("ListWorkflowRuns", &request);
        Ok(Response::new(ListWorkflowRunsResponse::default()))
    }
    async fn cancel_workflow_run(
        &self,
        request: Request<CancelWorkflowRunRequest>,
    ) -> Result<Response<CancelWorkflowRunResponse>, Status> {
        self.record("CancelWorkflowRun", &request);
        Ok(Response::new(CancelWorkflowRunResponse {
            operation: Some(operation()),
        }))
    }
    async fn commit_workflow_transition(
        &self,
        request: Request<CommitWorkflowTransitionRequest>,
    ) -> Result<Response<CommitWorkflowTransitionResponse>, Status> {
        self.record("CommitWorkflowTransition", &request);
        let sequence = request.get_ref().expected_transition_sequence + 1;
        Ok(Response::new(CommitWorkflowTransitionResponse {
            workflow_run: Some(run(sequence, WorkflowRunState::Running)),
        }))
    }
    async fn watch_workflow_run(
        &self,
        request: Request<WatchWorkflowRunRequest>,
    ) -> Result<Response<WorkflowStream>, Status> {
        self.record("WatchWorkflowRun", &request);
        let call = self.watch_calls.fetch_add(1, Ordering::SeqCst);
        assert_eq!(request.get_ref().after_transition_sequence, call as u64);
        let configured = self.terminal_state.load(Ordering::SeqCst);
        let terminal = if configured == WorkflowRunState::Unspecified as i32 {
            WorkflowRunState::Succeeded
        } else {
            WorkflowRunState::try_from(configured).unwrap_or(WorkflowRunState::Succeeded)
        };
        let updates = if call == 0 {
            vec![Ok(WatchWorkflowRunResponse {
                workflow_run: Some(run(1, WorkflowRunState::Running)),
            })]
        } else {
            vec![Ok(WatchWorkflowRunResponse {
                workflow_run: Some(run(2, terminal)),
            })]
        };
        Ok(Response::new(Box::pin(tokio_stream::iter(updates))))
    }
    async fn request_approval(
        &self,
        request: Request<RequestApprovalRequest>,
    ) -> Result<Response<RequestApprovalResponse>, Status> {
        self.record("RequestApproval", &request);
        let mut value = request.into_inner().approval_request.unwrap();
        value.name = APPROVAL.to_owned();
        Ok(Response::new(RequestApprovalResponse {
            approval_request: Some(value),
        }))
    }
    async fn get_approval_request(
        &self,
        request: Request<GetApprovalRequestRequest>,
    ) -> Result<Response<GetApprovalRequestResponse>, Status> {
        self.record("GetApprovalRequest", &request);
        Ok(Response::new(GetApprovalRequestResponse {
            approval_request: Some(ApprovalRequest {
                name: request.into_inner().name,
                ..ApprovalRequest::default()
            }),
        }))
    }
    async fn list_approval_requests(
        &self,
        request: Request<ListApprovalRequestsRequest>,
    ) -> Result<Response<ListApprovalRequestsResponse>, Status> {
        self.record("ListApprovalRequests", &request);
        Ok(Response::new(ListApprovalRequestsResponse::default()))
    }
    async fn decide_approval(
        &self,
        request: Request<DecideApprovalRequest>,
    ) -> Result<Response<DecideApprovalResponse>, Status> {
        self.record("DecideApproval", &request);
        let value = request.into_inner();
        Ok(Response::new(DecideApprovalResponse {
            approval_receipt: Some(ApprovalReceipt {
                name: RECEIPT.to_owned(),
                request: Some(ResourceRef {
                    name: value.name,
                    ..ResourceRef::default()
                }),
                binding: Some(binding()),
                decision: value.decision,
                reason_code: value.reason_code,
                safe_reason: value.safe_reason,
                decided_at: Some(Timestamp {
                    seconds: 1,
                    nanos: 0,
                }),
                receipt_digest: digest(),
                ..ApprovalReceipt::default()
            }),
        }))
    }
    async fn consume_approval(
        &self,
        request: Request<ConsumeApprovalRequest>,
    ) -> Result<Response<ConsumeApprovalResponse>, Status> {
        self.record("ConsumeApproval", &request);
        let value = request.into_inner();
        let mut binding = binding();
        binding.binding_digest = value.binding_digest;
        Ok(Response::new(ConsumeApprovalResponse {
            approval_receipt: Some(ApprovalReceipt {
                name: value.receipt_name,
                binding: Some(binding),
                consumed_at: Some(Timestamp {
                    seconds: 1,
                    nanos: 0,
                }),
                consumed_by_call_id: value.call_id,
                receipt_digest: digest(),
                ..ApprovalReceipt::default()
            }),
        }))
    }
}

struct TestToken;
#[async_trait]
impl TokenProvider for TestToken {
    async fn token(&self, _audience: &str) -> Result<AccessToken, crate::Error> {
        AccessToken::new(
            "short-lived-token",
            SystemTime::now() + Duration::from_mins(5),
        )
    }
}

fn client(transport: Arc<WorkflowTransport>) -> Client {
    let identity = Identity::new("tenants/t-1", "projects/p-1", "principals/worker-1").unwrap();
    let provider: Arc<dyn TokenProvider> = Arc::new(TestToken);
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
fn digest() -> String {
    format!("sha256:{}", "a".repeat(64))
}
fn binding() -> ApprovalBinding {
    let mut value = ApprovalBinding {
        action: "workflow.transition".to_owned(),
        intent_digest: digest(),
        parameters_digest: digest(),
        ..ApprovalBinding::default()
    };
    value.binding_digest = format!("sha256:{:x}", Sha256::digest(value.encode_to_vec()));
    value
}

#[tokio::test]
#[allow(clippy::too_many_lines)]
async fn workflow_and_approval_facades_cover_all_generated_rpcs() {
    let transport = Arc::new(WorkflowTransport::default());
    let client = client(Arc::clone(&transport));
    let definition = WorkflowDefinition {
        name: DEFINITION.to_owned(),
        tenant_id: "attacker".to_owned(),
        project_id: "attacker".to_owned(),
        ..WorkflowDefinition::default()
    };
    // Caller scope is rejected, not silently trusted.
    assert!(
        client
            .workflows()
            .create_definition(
                CreateWorkflowDefinitionRequest {
                    parent: PARENT.to_owned(),
                    workflow_definition_id: "definition-1".to_owned(),
                    workflow_definition: Some(definition),
                    ..CreateWorkflowDefinitionRequest::default()
                },
                submit("bad")
            )
            .await
            .is_err()
    );
    let definition = WorkflowDefinition {
        name: DEFINITION.to_owned(),
        ..WorkflowDefinition::default()
    };
    client
        .workflows()
        .create_definition(
            CreateWorkflowDefinitionRequest {
                parent: String::new(),
                workflow_definition_id: "definition-1".to_owned(),
                workflow_definition: Some(definition.clone()),
                ..CreateWorkflowDefinitionRequest::default()
            },
            submit("create-definition"),
        )
        .await
        .unwrap();
    client
        .workflows()
        .update_definition(
            UpdateWorkflowDefinitionRequest {
                workflow_definition: Some(definition),
                update_mask: Some(FieldMask {
                    paths: vec!["display_name".to_owned()],
                }),
                etag: "etag-1".to_owned(),
                ..UpdateWorkflowDefinitionRequest::default()
            },
            submit("update-definition"),
        )
        .await
        .unwrap();
    client
        .workflows()
        .get_definition(DEFINITION, "", CallOptions::new())
        .await
        .unwrap();
    client
        .workflows()
        .list_definitions(
            ListWorkflowDefinitionsRequest {
                page: Some(PageRequest {
                    page_size: 20,
                    page_token: "opaque-definition".to_owned(),
                }),
                ..ListWorkflowDefinitionsRequest::default()
            },
            CallOptions::new(),
        )
        .unwrap()
        .next_page()
        .await
        .unwrap()
        .unwrap();
    let workflow_run = run(0, WorkflowRunState::Created);
    let mut workflow_run = WorkflowRun {
        definition: Some(ResourceRef {
            resource_type: "workflow_definition".to_owned(),
            resource_id: "definition-1".to_owned(),
            name: DEFINITION.to_owned(),
            ..ResourceRef::default()
        }),
        ..workflow_run
    };
    workflow_run.name.clear();
    client
        .workflows()
        .start_run(
            StartWorkflowRunRequest {
                workflow_run_id: "run-1".to_owned(),
                workflow_run: Some(workflow_run),
                ..StartWorkflowRunRequest::default()
            },
            submit("start-run"),
        )
        .await
        .unwrap();
    client
        .workflows()
        .get_run(RUN, "", CallOptions::new())
        .await
        .unwrap();
    client
        .workflows()
        .list_runs(ListWorkflowRunsRequest::default(), CallOptions::new())
        .unwrap()
        .next_page()
        .await
        .unwrap()
        .unwrap();
    client
        .workflows()
        .cancel_run(
            CancelWorkflowRunRequest {
                name: RUN.to_owned(),
                etag: "etag-1".to_owned(),
                reason: "operator request".to_owned(),
                ..CancelWorkflowRunRequest::default()
            },
            submit("cancel-run"),
        )
        .await
        .unwrap();
    let deadline = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 60;
    let call = CallOptions::new()
        .with_lease_token("opaque-lease-token")
        .unwrap();
    client
        .workflows()
        .commit_transition(
            CommitWorkflowTransitionRequest {
                workflow_run: Some(run(0, WorkflowRunState::Running)),
                expected_transition_sequence: 0,
                fence: Some(LeaseFence {
                    job_id: "job-1".to_owned(),
                    run_id: "run-1".to_owned(),
                    attempt_id: "attempt-1".to_owned(),
                    lease_epoch: 1,
                    deadline: Some(Timestamp {
                        seconds: i64::try_from(deadline).unwrap(),
                        nanos: 0,
                    }),
                    lease_token_digest: digest(),
                    ..LeaseFence::default()
                }),
                etag: "etag-1".to_owned(),
                ..CommitWorkflowTransitionRequest::default()
            },
            submit("commit-transition").with_call_options(call),
        )
        .await
        .unwrap();
    let approval = client
        .approvals()
        .request(
            ApprovalRequest {
                binding: Some(binding()),
                ..ApprovalRequest::default()
            },
            submit("request-approval"),
        )
        .await
        .unwrap();
    assert_eq!(approval.name, APPROVAL);
    client
        .approvals()
        .get(APPROVAL, CallOptions::new())
        .await
        .unwrap();
    client
        .approvals()
        .list(ListApprovalRequestsRequest::default(), CallOptions::new())
        .unwrap()
        .next_page()
        .await
        .unwrap()
        .unwrap();
    client
        .approvals()
        .decide(
            DecideApprovalRequest {
                name: APPROVAL.to_owned(),
                etag: "etag-1".to_owned(),
                decision: ApprovalDecisionValue::Approve as i32,
                reason_code: "reviewed".to_owned(),
                safe_reason: "approved".to_owned(),
                ..DecideApprovalRequest::default()
            },
            submit("decide-approval"),
        )
        .await
        .unwrap();
    client
        .approvals()
        .consume(
            ConsumeApprovalRequest {
                receipt_name: RECEIPT.to_owned(),
                binding_digest: binding().binding_digest,
                call_id: "call-1".to_owned(),
                ..ConsumeApprovalRequest::default()
            },
            submit("consume-approval"),
        )
        .await
        .unwrap();
    let result = client
        .workflows()
        .wait(
            RUN,
            0,
            WorkflowWatchOptions::new()
                .with_timeout(Duration::from_secs(5))
                .unwrap(),
            CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(result.state, WorkflowRunState::Succeeded as i32);
    assert_eq!(transport.watch_calls.load(Ordering::SeqCst), 2);
    let methods = transport.methods.lock().unwrap();
    for method in [
        "CreateWorkflowDefinition",
        "UpdateWorkflowDefinition",
        "GetWorkflowDefinition",
        "ListWorkflowDefinitions",
        "StartWorkflowRun",
        "GetWorkflowRun",
        "ListWorkflowRuns",
        "CancelWorkflowRun",
        "CommitWorkflowTransition",
        "WatchWorkflowRun",
        "RequestApproval",
        "GetApprovalRequest",
        "ListApprovalRequests",
        "DecideApproval",
        "ConsumeApproval",
    ] {
        assert!(methods.contains(&method), "missing {method}");
    }
    let leases = transport.lease_seen.lock().unwrap();
    assert_eq!(leases.iter().filter(|seen| **seen).count(), 1);
}

#[tokio::test]
async fn workflow_wait_returns_typed_generated_failure_and_cancellation_wins() {
    let transport = Arc::new(WorkflowTransport::default());
    transport
        .terminal_state
        .store(WorkflowRunState::Failed as i32, Ordering::SeqCst);
    let client = client(Arc::clone(&transport));
    let error = client
        .workflows()
        .wait(
            RUN,
            0,
            WorkflowWatchOptions::new()
                .with_timeout(Duration::from_secs(5))
                .unwrap(),
            CancellationToken::new(),
        )
        .await
        .unwrap_err();
    assert!(
        matches!(error, crate::WorkflowWaitError::Workflow(value) if value.run().state == WorkflowRunState::Failed as i32)
    );

    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let error = client
        .workflows()
        .wait(RUN, 0, WorkflowWatchOptions::new(), cancellation)
        .await
        .unwrap_err();
    assert!(
        matches!(error, crate::WorkflowWaitError::Sdk(value) if value.kind() == crate::ErrorKind::Cancelled)
    );
}

/// The workflow wait error exposes the same accessors and error source as the
/// operation wait error, so the two long-running domains behave alike.
#[tokio::test]
async fn workflow_wait_error_exposes_its_source_and_accessors() {
    let transport = Arc::new(WorkflowTransport::default());
    transport
        .terminal_state
        .store(WorkflowRunState::Failed as i32, Ordering::SeqCst);
    let client = client(Arc::clone(&transport));
    let error = client
        .workflows()
        .wait(
            RUN,
            0,
            WorkflowWatchOptions::new(),
            CancellationToken::new(),
        )
        .await
        .unwrap_err();
    let failure = error.workflow_failure().unwrap();
    assert_eq!(failure.run().state, WorkflowRunState::Failed as i32);
    assert!(error.sdk_error().is_none());
    assert!(std::error::Error::source(&error).is_some());
    assert!(!format!("{failure:?}").contains("ErrorDetail"));

    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let error = client
        .workflows()
        .wait(RUN, 0, WorkflowWatchOptions::new(), cancellation)
        .await
        .unwrap_err();
    assert!(error.workflow_failure().is_none());
    assert_eq!(
        error.sdk_error().map(crate::Error::kind),
        Some(crate::ErrorKind::Cancelled)
    );
}
