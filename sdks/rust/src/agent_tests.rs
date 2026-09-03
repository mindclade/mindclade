use std::{
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    agent::v1::{AgentDefinition, AgentRun, AgentStep, ToolReceipt},
    common::v1::{CommandContext, PageRequest, PageResponse, ResourceRef},
    internal::agent::v1::{
        CancelAgentRunRequest, CancelAgentRunResponse, CommitAgentStepRequest,
        CommitAgentStepResponse, CommitToolReceiptRequest, CommitToolReceiptResponse,
        CreateAgentDefinitionRequest, CreateAgentDefinitionResponse, GetAgentDefinitionRequest,
        GetAgentDefinitionResponse, GetAgentRunRequest, GetAgentRunResponse, GetAgentStepRequest,
        GetAgentStepResponse, ListAgentDefinitionsRequest, ListAgentDefinitionsResponse,
        ListAgentRunsRequest, ListAgentRunsResponse, ListAgentStepsRequest, ListAgentStepsResponse,
        StartAgentRunRequest, StartAgentRunResponse, UpdateAgentDefinitionRequest,
        UpdateAgentDefinitionResponse,
    },
    job::v1::LeaseFence,
    operation::v1::Operation,
};
use prost_types::{FieldMask, Timestamp};
use sha2::{Digest, Sha256};
use tonic::{Request, Response, Status, codegen::async_trait};

use crate::{
    AccessToken, CallOptions, Client, Config, Environment, Identity, RecordingTransport,
    RpcTransport, SubmitOptions, TokenProvider,
};

const PARENT: &str = "tenants/t-1/projects/p-1";
const DEFINITION: &str = "tenants/t-1/projects/p-1/agentDefinitions/definition-1";
const RUN: &str = "tenants/t-1/projects/p-1/agentRuns/run-1";
const STEP: &str = "tenants/t-1/projects/p-1/agentRuns/run-1/agentSteps/1";
const RECEIPT: &str = "tenants/t-1/projects/p-1/toolReceipts/receipt-1";

#[derive(Default)]
struct AgentTransport {
    methods: Mutex<Vec<&'static str>>,
    contexts: Mutex<Vec<CommandContext>>,
    leases: Mutex<Vec<Option<String>>>,
}

impl AgentTransport {
    fn record<T>(
        &self,
        method: &'static str,
        request: &Request<T>,
        context: Option<&CommandContext>,
    ) {
        self.methods.lock().unwrap().push(method);
        if let Some(context) = context {
            self.contexts.lock().unwrap().push(context.clone());
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

fn operation() -> Operation {
    Operation {
        operation_id: "operations/agent-test".to_owned(),
        ..Operation::default()
    }
}

#[async_trait]
impl RpcTransport for AgentTransport {
    async fn create_agent_definition(
        &self,
        request: Request<CreateAgentDefinitionRequest>,
    ) -> Result<Response<CreateAgentDefinitionResponse>, Status> {
        self.record(
            "CreateAgentDefinition",
            &request,
            request.get_ref().context.as_ref(),
        );
        Ok(Response::new(CreateAgentDefinitionResponse {
            operation: Some(operation()),
        }))
    }

    async fn update_agent_definition(
        &self,
        request: Request<UpdateAgentDefinitionRequest>,
    ) -> Result<Response<UpdateAgentDefinitionResponse>, Status> {
        self.record(
            "UpdateAgentDefinition",
            &request,
            request.get_ref().context.as_ref(),
        );
        Ok(Response::new(UpdateAgentDefinitionResponse {
            operation: Some(operation()),
        }))
    }

    async fn get_agent_definition(
        &self,
        request: Request<GetAgentDefinitionRequest>,
    ) -> Result<Response<GetAgentDefinitionResponse>, Status> {
        self.record("GetAgentDefinition", &request, None);
        Ok(Response::new(GetAgentDefinitionResponse {
            agent_definition: Some(AgentDefinition {
                name: request.into_inner().name,
                ..AgentDefinition::default()
            }),
        }))
    }

    async fn list_agent_definitions(
        &self,
        request: Request<ListAgentDefinitionsRequest>,
    ) -> Result<Response<ListAgentDefinitionsResponse>, Status> {
        self.record("ListAgentDefinitions", &request, None);
        assert_eq!(
            request.get_ref().page.as_ref().unwrap().page_token,
            "opaque"
        );
        Ok(Response::new(ListAgentDefinitionsResponse {
            page: Some(PageResponse {
                next_page_token: "next-definition".to_owned(),
            }),
            ..ListAgentDefinitionsResponse::default()
        }))
    }

    async fn start_agent_run(
        &self,
        request: Request<StartAgentRunRequest>,
    ) -> Result<Response<StartAgentRunResponse>, Status> {
        self.record(
            "StartAgentRun",
            &request,
            request.get_ref().context.as_ref(),
        );
        Ok(Response::new(StartAgentRunResponse {
            operation: Some(operation()),
        }))
    }

    async fn get_agent_run(
        &self,
        request: Request<GetAgentRunRequest>,
    ) -> Result<Response<GetAgentRunResponse>, Status> {
        self.record("GetAgentRun", &request, None);
        Ok(Response::new(GetAgentRunResponse {
            agent_run: Some(AgentRun {
                name: request.into_inner().name,
                ..AgentRun::default()
            }),
        }))
    }

    async fn list_agent_runs(
        &self,
        request: Request<ListAgentRunsRequest>,
    ) -> Result<Response<ListAgentRunsResponse>, Status> {
        self.record("ListAgentRuns", &request, None);
        Ok(Response::new(ListAgentRunsResponse {
            page: Some(PageResponse {
                next_page_token: "next-run".to_owned(),
            }),
            ..ListAgentRunsResponse::default()
        }))
    }

    async fn cancel_agent_run(
        &self,
        request: Request<CancelAgentRunRequest>,
    ) -> Result<Response<CancelAgentRunResponse>, Status> {
        self.record(
            "CancelAgentRun",
            &request,
            request.get_ref().context.as_ref(),
        );
        Ok(Response::new(CancelAgentRunResponse {
            operation: Some(operation()),
        }))
    }

    async fn get_agent_step(
        &self,
        request: Request<GetAgentStepRequest>,
    ) -> Result<Response<GetAgentStepResponse>, Status> {
        self.record("GetAgentStep", &request, None);
        Ok(Response::new(GetAgentStepResponse {
            agent_step: Some(AgentStep {
                name: request.into_inner().name,
                sequence: 1,
                ..AgentStep::default()
            }),
        }))
    }

    async fn list_agent_steps(
        &self,
        request: Request<ListAgentStepsRequest>,
    ) -> Result<Response<ListAgentStepsResponse>, Status> {
        self.record("ListAgentSteps", &request, None);
        Ok(Response::new(ListAgentStepsResponse {
            page: Some(PageResponse {
                next_page_token: "next-step".to_owned(),
            }),
            ..ListAgentStepsResponse::default()
        }))
    }

    async fn commit_agent_step(
        &self,
        request: Request<CommitAgentStepRequest>,
    ) -> Result<Response<CommitAgentStepResponse>, Status> {
        self.record(
            "CommitAgentStep",
            &request,
            request.get_ref().context.as_ref(),
        );
        let mut step = request.get_ref().agent_step.clone().unwrap();
        step.name = STEP.to_owned();
        Ok(Response::new(CommitAgentStepResponse {
            agent_step: Some(step),
            agent_run: Some(AgentRun {
                name: RUN.to_owned(),
                next_step_sequence: 2,
                ..AgentRun::default()
            }),
        }))
    }

    async fn commit_tool_receipt(
        &self,
        request: Request<CommitToolReceiptRequest>,
    ) -> Result<Response<CommitToolReceiptResponse>, Status> {
        self.record(
            "CommitToolReceipt",
            &request,
            request.get_ref().context.as_ref(),
        );
        Ok(Response::new(CommitToolReceiptResponse {
            tool_receipt: request.get_ref().tool_receipt.clone(),
            agent_run: Some(AgentRun {
                name: RUN.to_owned(),
                ..AgentRun::default()
            }),
        }))
    }
}

struct TestTokenProvider;

#[async_trait]
impl TokenProvider for TestTokenProvider {
    async fn token(&self, _audience: &str) -> Result<AccessToken, crate::Error> {
        AccessToken::new(
            "short-lived-agent-test-token",
            SystemTime::now() + Duration::from_mins(5),
        )
    }
}

fn reference(resource_type: &str, collection: &str, id: &str) -> ResourceRef {
    ResourceRef {
        resource_type: resource_type.to_owned(),
        resource_id: id.to_owned(),
        name: format!("{PARENT}/{collection}/{id}"),
        ..ResourceRef::default()
    }
}

fn definition() -> AgentDefinition {
    AgentDefinition {
        workflow_definition: Some(reference(
            "workflow_definition",
            "workflowDefinitions",
            "workflow-1",
        )),
        evaluation_suite: Some(reference(
            "evaluation_suite",
            "evaluationSuites",
            "evaluation-1",
        )),
        eligible_tools: vec![reference("tool", "tools", "tool-1")],
        ..AgentDefinition::default()
    }
}

fn digest(value: &str) -> String {
    format!("sha256:{:x}", Sha256::digest(value.as_bytes()))
}

fn fence(token: &str) -> LeaseFence {
    let deadline = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .saturating_add(Duration::from_mins(1));
    LeaseFence {
        job_id: "jobs/job-1".to_owned(),
        run_id: "runs/run-1".to_owned(),
        attempt_id: "attempts/attempt-1".to_owned(),
        lease_epoch: 1,
        deadline: Some(Timestamp {
            seconds: i64::try_from(deadline.as_secs()).unwrap(),
            nanos: i32::try_from(deadline.subsec_nanos()).unwrap(),
        }),
        tenant_id: "t-1".to_owned(),
        project_id: "p-1".to_owned(),
        lease_token_digest: digest(token),
    }
}

fn submit(key: &str) -> SubmitOptions {
    SubmitOptions::new(key).unwrap()
}

fn fenced_submit(key: &str, token: &str) -> SubmitOptions {
    submit(key).with_call_options(CallOptions::new().with_lease_token(token).unwrap())
}

fn client(transport: Arc<dyn RpcTransport>) -> Client {
    let identity = Identity::new("t-1", "p-1", "worker-1").unwrap();
    let provider: Arc<dyn TokenProvider> = Arc::new(TestTokenProvider);
    let config = Config::builder(Environment::Development, identity, provider)
        .build()
        .unwrap();
    Client::with_transport(config, transport)
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "one end-to-end recording test deliberately exercises the complete agent RPC surface"
)]
async fn agent_facade_covers_every_rpc_and_fenced_metadata() {
    let inner = Arc::new(AgentTransport::default());
    let recording = Arc::new(RecordingTransport::new(Arc::clone(&inner)));
    let client = client(recording.clone());
    let agents = client.agents();

    let create = CreateAgentDefinitionRequest {
        agent_definition_id: "definition-1".to_owned(),
        agent_definition: Some(definition()),
        ..CreateAgentDefinitionRequest::default()
    };
    let original = create.clone();
    agents
        .create_definition(create, submit("create-1"))
        .await
        .unwrap();
    assert_eq!(original.context, None);

    let mut updated = definition();
    updated.name = DEFINITION.to_owned();
    agents
        .update_definition(
            UpdateAgentDefinitionRequest {
                agent_definition: Some(updated),
                update_mask: Some(FieldMask {
                    paths: vec!["purpose".to_owned()],
                }),
                etag: "etag-1".to_owned(),
                ..UpdateAgentDefinitionRequest::default()
            },
            submit("update-1"),
        )
        .await
        .unwrap();
    assert_eq!(
        agents
            .get_definition(DEFINITION, "", CallOptions::new())
            .await
            .unwrap()
            .name,
        DEFINITION
    );
    assert_eq!(
        agents
            .list_definitions(
                ListAgentDefinitionsRequest {
                    page: Some(PageRequest {
                        page_size: 10,
                        page_token: "opaque".to_owned(),
                    }),
                    ..ListAgentDefinitionsRequest::default()
                },
                CallOptions::new(),
            )
            .unwrap()
            .next_page()
            .await
            .unwrap()
            .unwrap()
            .next_page_token(),
        "next-definition"
    );

    agents
        .start_run(
            StartAgentRunRequest {
                agent_run_id: "run-1".to_owned(),
                agent_run: Some(AgentRun {
                    definition: Some(reference(
                        "agent_definition",
                        "agentDefinitions",
                        "definition-1",
                    )),
                    budget_reservation: Some(reference(
                        "budget_reservation",
                        "budgetReservations",
                        "budget-1",
                    )),
                    ..AgentRun::default()
                }),
                ..StartAgentRunRequest::default()
            },
            submit("start-1"),
        )
        .await
        .unwrap();
    assert_eq!(
        agents
            .get_run(RUN, "", CallOptions::new())
            .await
            .unwrap()
            .name,
        RUN
    );
    assert_eq!(
        agents
            .list_runs(ListAgentRunsRequest::default(), CallOptions::new())
            .unwrap()
            .next_page()
            .await
            .unwrap()
            .unwrap()
            .next_page_token(),
        "next-run"
    );
    agents
        .cancel_run(
            CancelAgentRunRequest {
                name: RUN.to_owned(),
                etag: "etag-2".to_owned(),
                reason: "operator request".to_owned(),
                ..CancelAgentRunRequest::default()
            },
            submit("cancel-1"),
        )
        .await
        .unwrap();
    assert_eq!(
        agents
            .get_step(STEP, CallOptions::new())
            .await
            .unwrap()
            .name,
        STEP
    );
    assert_eq!(
        agents
            .list_steps(
                ListAgentStepsRequest {
                    parent: RUN.to_owned(),
                    ..ListAgentStepsRequest::default()
                },
                CallOptions::new(),
            )
            .unwrap()
            .next_page()
            .await
            .unwrap()
            .unwrap()
            .next_page_token(),
        "next-step"
    );

    let token = "scheduler-issued-agent-token";
    let (step, run) = Box::pin(agents.commit_step(
        CommitAgentStepRequest {
            agent_step: Some(AgentStep {
                run: Some(reference("agent_run", "agentRuns", "run-1")),
                sequence: 1,
                ..AgentStep::default()
            }),
            fence: Some(fence(token)),
            run_etag: "etag-3".to_owned(),
            expected_next_step_sequence: 1,
            ..CommitAgentStepRequest::default()
        },
        fenced_submit("step-1", token),
    ))
    .await
    .unwrap();
    assert_eq!((step.name.as_str(), run.name.as_str()), (STEP, RUN));
    let (receipt, run) = agents
        .commit_tool_receipt(
            CommitToolReceiptRequest {
                tool_receipt: Some(ToolReceipt {
                    name: RECEIPT.to_owned(),
                    call_id: "call-1".to_owned(),
                    agent_run_name: RUN.to_owned(),
                    agent_step_name: STEP.to_owned(),
                    tool: Some(reference("tool", "tools", "tool-1")),
                    ..ToolReceipt::default()
                }),
                run_etag: "etag-4".to_owned(),
                fence: Some(fence(token)),
                ..CommitToolReceiptRequest::default()
            },
            fenced_submit("receipt-1", token),
        )
        .await
        .unwrap();
    assert_eq!((receipt.name.as_str(), run.name.as_str()), (RECEIPT, RUN));

    assert_eq!(inner.methods.lock().unwrap().len(), 12);
    let contexts = inner.contexts.lock().unwrap();
    assert_eq!(contexts.len(), 6);
    assert!(contexts.iter().all(|context| {
        context.tenant_id == "t-1"
            && context.project_id == "p-1"
            && context.principal_id == "worker-1"
            && !context.canonical_request_digest.is_empty()
            && !context.idempotency_key.is_empty()
    }));
    let leases = inner.leases.lock().unwrap();
    assert!(leases[..10].iter().all(Option::is_none));
    assert_eq!(leases[10].as_deref(), Some(token));
    assert_eq!(leases[11].as_deref(), Some(token));

    let recorded = recording.calls();
    assert_eq!(recorded.len(), 12);
    assert!(
        recorded[10]
            .metadata_keys
            .iter()
            .any(|key| key == "x-mindclade-lease-token")
    );
    assert!(!format!("{recorded:?}").contains(token));
    let options = CallOptions::new().with_lease_token(token).unwrap();
    assert!(!format!("{options:?}").contains(token));
}

#[tokio::test]
async fn fenced_agent_commit_requires_token_and_pages_are_bounded() {
    let client = client(Arc::new(AgentTransport::default()));
    let error = Box::pin(client.agents().commit_step(
        CommitAgentStepRequest {
            agent_step: Some(AgentStep {
                run: Some(reference("agent_run", "agentRuns", "run-1")),
                sequence: 1,
                ..AgentStep::default()
            }),
            fence: Some(fence("token")),
            run_etag: "etag".to_owned(),
            expected_next_step_sequence: 1,
            ..CommitAgentStepRequest::default()
        },
        submit("missing-token"),
    ))
    .await
    .unwrap_err();
    assert!(error.to_string().contains("lease token"));

    assert!(
        client
            .agents()
            .list_steps(
                ListAgentStepsRequest {
                    parent: RUN.to_owned(),
                    page: Some(PageRequest {
                        page_size: 201,
                        page_token: String::new(),
                    }),
                    ..ListAgentStepsRequest::default()
                },
                CallOptions::new(),
            )
            .is_err()
    );
    assert!(CallOptions::new().with_lease_token("bad token").is_err());
}
