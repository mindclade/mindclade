use std::{sync::Arc, time::SystemTime};

use mindclade_protocols::{
    agent::v1::{AgentDefinition, AgentRun, AgentStep, ToolReceipt},
    common::v1::ResourceRef,
    internal::agent::v1::{
        CancelAgentRunRequest, CommitAgentStepRequest, CommitToolReceiptRequest,
        CreateAgentDefinitionRequest, GetAgentDefinitionRequest, GetAgentRunRequest,
        GetAgentStepRequest, ListAgentDefinitionsRequest, ListAgentRunsRequest,
        ListAgentStepsRequest,
        StartAgentRunRequest, UpdateAgentDefinitionRequest,
    },
    job::v1::{LeaseFence, Operation},
};
use prost::Message;
use sha2::{Digest, Sha256};

use crate::{
    CallOptions, ClientCore, Error, Page, Pages, SubmitOptions,
    request::{initial_page_token, page_request},
    retry::registered_method_safety,
};

const MAXIMUM_PAGE_SIZE: u32 = 200;
const CREATE_DEFINITION: &str = "/mindclade.internal.agent.v1.AgentService/CreateAgentDefinition";
const UPDATE_DEFINITION: &str = "/mindclade.internal.agent.v1.AgentService/UpdateAgentDefinition";
const GET_DEFINITION: &str = "/mindclade.internal.agent.v1.AgentService/GetAgentDefinition";
const LIST_DEFINITIONS: &str = "/mindclade.internal.agent.v1.AgentService/ListAgentDefinitions";
const START_RUN: &str = "/mindclade.internal.agent.v1.AgentService/StartAgentRun";
const GET_RUN: &str = "/mindclade.internal.agent.v1.AgentService/GetAgentRun";
const LIST_RUNS: &str = "/mindclade.internal.agent.v1.AgentService/ListAgentRuns";
const CANCEL_RUN: &str = "/mindclade.internal.agent.v1.AgentService/CancelAgentRun";
const GET_STEP: &str = "/mindclade.internal.agent.v1.AgentService/GetAgentStep";
const LIST_STEPS: &str = "/mindclade.internal.agent.v1.AgentService/ListAgentSteps";
const COMMIT_STEP: &str = "/mindclade.internal.agent.v1.AgentService/CommitAgentStep";
const COMMIT_RECEIPT: &str = "/mindclade.internal.agent.v1.AgentService/CommitToolReceipt";

/// Generated-type-only private facade for bounded agent definitions, durable
/// runs, append-only steps, and immutable execution receipts.
#[derive(Clone)]
pub struct Agents {
    core: Arc<ClientCore>,
}

impl Agents {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Creates a generated agent definition and returns its durable operation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, server-managed input fields,
    /// credentials, retry metadata, transport failure, or malformed response.
    pub async fn create_definition(
        &self,
        mut request: CreateAgentDefinitionRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        request.parent = self.parent(&request.parent, "agent definition")?;
        valid_identifier("agent definition ID", &request.agent_definition_id)?;
        self.normalize_definition(
            request
                .agent_definition
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("agent definition is required"))?,
            true,
        )?;
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        set_context(&self.core, &mut request, &prepared, &options)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(CREATE_DEFINITION),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.create_agent_definition(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CreateAgentDefinition")
    }

    /// Updates a generated definition under a field mask and `ETag`.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/concurrency metadata, credentials,
    /// transport failure, or malformed response.
    pub async fn update_definition(
        &self,
        mut request: UpdateAgentDefinitionRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let definition = request
            .agent_definition
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("agent definition is required"))?;
        self.normalize_definition(definition, false)?;
        if request.etag.trim().is_empty()
            || request
                .update_mask
                .as_ref()
                .is_none_or(|mask| mask.paths.is_empty() || mask.paths.len() > 32)
        {
            return Err(Error::invalid_argument(
                "agent update requires an ETag and one to 32 field-mask paths",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        set_context(&self.core, &mut request, &prepared, &options)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(UPDATE_DEFINITION),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.update_agent_definition(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "UpdateAgentDefinition")
    }

    /// Reads one generated definition revision.
    ///
    /// # Errors
    ///
    /// Returns an error for scope mismatch, transport failure, or identity
    /// drift in the response.
    pub async fn get_definition(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<AgentDefinition, Error> {
        let name = self.scoped_name(name.into(), "agentDefinitions")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetAgentDefinitionRequest {
                    name: name.clone(),
                    if_none_match: if_none_match.into().trim().to_owned(),
                },
                &prepared,
                registered_method_safety(GET_DEFINITION),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_agent_definition(request).await })
                },
            )
            .await?
            .into_inner();
        let value = response
            .agent_definition
            .ok_or_else(|| Error::protocol("GetAgentDefinition response omitted its definition"))?;
        if value.name != name {
            return Err(Error::protocol(
                "GetAgentDefinition response changed resource identity",
            ));
        }
        Ok(value)
    }

    /// Lists one bounded definition page using an opaque server-issued token.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/page policy or transport failure.
    pub fn list_definitions(
        &self,
        mut request: ListAgentDefinitionsRequest,
        options: CallOptions,
    ) -> Result<Pages<AgentDefinition>, Error> {
        request.parent = self.parent(&request.parent, "agent definition list")?;
        validate_page(request.page.as_ref())?;
        let core = Arc::clone(&self.core);
        let token = initial_page_token(request.page.as_ref());
        Ok(Pages::new(
            move |page_token| {
                let core = Arc::clone(&core);
                let options = options.clone();
                let mut request = request.clone();
                async move {
                    request.page = Some(page_request(request.page.as_ref(), page_token));
                    let prepared = options.prepare(&core.config);
                    let response = core
                        .unary(
                            request,
                            &prepared,
                            registered_method_safety(LIST_DEFINITIONS),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_agent_definitions(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.agent_definitions,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Starts a generated durable agent run and returns its operation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/intent, credentials, transport
    /// failure, or malformed response.
    pub async fn start_run(
        &self,
        mut request: StartAgentRunRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        request.parent = self.parent(&request.parent, "agent run")?;
        valid_identifier("agent run ID", &request.agent_run_id)?;
        let run = request
            .agent_run
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("agent run intent is required"))?;
        self.normalize_reference(
            run.definition
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("agent definition reference is required"))?,
            Some("agent_definition"),
            Some("agentDefinitions"),
        )?;
        if let Some(workflow) = run.workflow_run.as_mut() {
            self.normalize_reference(workflow, Some("workflow_run"), Some("workflowRuns"))?;
        }
        self.normalize_reference(
            run.budget_reservation.as_mut().ok_or_else(|| {
                Error::invalid_argument("agent budget reservation reference is required")
            })?,
            None,
            None,
        )?;
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        set_context(&self.core, &mut request, &prepared, &options)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(START_RUN),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.start_agent_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "StartAgentRun")
    }

    /// Reads one durable generated run.
    ///
    /// # Errors
    ///
    /// Returns an error for scope mismatch, transport failure, or identity
    /// drift in the response.
    pub async fn get_run(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<AgentRun, Error> {
        let name = self.scoped_name(name.into(), "agentRuns")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetAgentRunRequest {
                    name: name.clone(),
                    if_none_match: if_none_match.into().trim().to_owned(),
                },
                &prepared,
                registered_method_safety(GET_RUN),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_agent_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_run(response.agent_run, &name, "GetAgentRun")
    }

    /// Lists one bounded run page.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/page policy or transport failure.
    pub fn list_runs(
        &self,
        mut request: ListAgentRunsRequest,
        options: CallOptions,
    ) -> Result<Pages<AgentRun>, Error> {
        request.parent = self.parent(&request.parent, "agent run list")?;
        validate_page(request.page.as_ref())?;
        let core = Arc::clone(&self.core);
        let token = initial_page_token(request.page.as_ref());
        Ok(Pages::new(
            move |page_token| {
                let core = Arc::clone(&core);
                let options = options.clone();
                let mut request = request.clone();
                async move {
                    request.page = Some(page_request(request.page.as_ref(), page_token));
                    let prepared = options.prepare(&core.config);
                    let response = core
                        .unary(
                            request,
                            &prepared,
                            registered_method_safety(LIST_RUNS),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_agent_runs(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.agent_runs,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Records monotonic cancellation under an explicit `ETag`.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/concurrency metadata, credentials,
    /// transport failure, or malformed response.
    pub async fn cancel_run(
        &self,
        mut request: CancelAgentRunRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        self.scoped_name(request.name.clone(), "agentRuns")?;
        if request.etag.trim().is_empty()
            || request.reason.trim().is_empty()
            || request.reason.len() > 1024
        {
            return Err(Error::invalid_argument(
                "agent cancellation requires an ETag and bounded reason",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        set_context(&self.core, &mut request, &prepared, &options)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(CANCEL_RUN),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.cancel_agent_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CancelAgentRun")
    }

    /// Reads one immutable generated step.
    ///
    /// # Errors
    ///
    /// Returns an error for scope mismatch, transport failure, or identity
    /// drift in the response.
    pub async fn get_step(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<AgentStep, Error> {
        let name = self.step_name(name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetAgentStepRequest { name: name.clone() },
                &prepared,
                registered_method_safety(GET_STEP),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_agent_step(request).await })
                },
            )
            .await?
            .into_inner();
        let step = response
            .agent_step
            .ok_or_else(|| Error::protocol("GetAgentStep response omitted its step"))?;
        if step.name != name {
            return Err(Error::protocol(
                "GetAgentStep response changed resource identity",
            ));
        }
        Ok(step)
    }

    /// Lists append-only run history after an optional durable sequence.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/page policy or transport failure.
    pub fn list_steps(
        &self,
        request: ListAgentStepsRequest,
        options: CallOptions,
    ) -> Result<Pages<AgentStep>, Error> {
        self.scoped_name(request.parent.clone(), "agentRuns")?;
        validate_page(request.page.as_ref())?;
        let core = Arc::clone(&self.core);
        let token = initial_page_token(request.page.as_ref());
        Ok(Pages::new(
            move |page_token| {
                let core = Arc::clone(&core);
                let options = options.clone();
                let mut request = request.clone();
                async move {
                    request.page = Some(page_request(request.page.as_ref(), page_token));
                    let prepared = options.prepare(&core.config);
                    let response = core
                        .unary(
                            request,
                            &prepared,
                            registered_method_safety(LIST_STEPS),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_agent_steps(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.agent_steps,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Appends one generated step under an authenticated raw lease credential
    /// and protobuf fence. The raw token is sensitive transport metadata only.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/sequence/fence, a missing raw lease
    /// token, credentials, transport failure, or inconsistent durable state.
    pub async fn commit_step(
        &self,
        mut request: CommitAgentStepRequest,
        options: SubmitOptions,
    ) -> Result<(AgentStep, AgentRun), Error> {
        if request.run_etag.trim().is_empty() || request.expected_next_step_sequence == 0 {
            return Err(Error::invalid_argument(
                "agent step commit requires a run ETag and next sequence",
            ));
        }
        let step = request
            .agent_step
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("agent step is required"))?;
        if step.sequence != request.expected_next_step_sequence {
            return Err(Error::invalid_argument(
                "agent step sequence must equal expected next sequence",
            ));
        }
        self.normalize_reference(
            step.run
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("agent step run is required"))?,
            Some("agent_run"),
            Some("agentRuns"),
        )?;
        let expected_run = step.run.as_ref().map_or("", |value| &value.name).to_owned();
        validate_fence(
            &self.core,
            request
                .fence
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("agent fence is required"))?,
        )?;
        request.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        set_context(&self.core, &mut request, &prepared, &options)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(COMMIT_STEP),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_agent_step(request).await })
                },
            )
            .await?
            .into_inner();
        let accepted = response
            .agent_step
            .ok_or_else(|| Error::protocol("CommitAgentStep response omitted its step"))?;
        let run = require_run(response.agent_run, &expected_run, "CommitAgentStep")?;
        if accepted.sequence != request_sequence(&accepted, &run)?
            || accepted.run.as_ref().map_or("", |value| &value.name) != expected_run
        {
            return Err(Error::protocol(
                "CommitAgentStep returned inconsistent durable state",
            ));
        }
        Ok((accepted, run))
    }

    /// Appends an immutable generated tool receipt under the current fence.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid evidence/scope/fence, a missing raw lease
    /// token, credentials, transport failure, or inconsistent durable state.
    pub async fn commit_tool_receipt(
        &self,
        mut request: CommitToolReceiptRequest,
        options: SubmitOptions,
    ) -> Result<(ToolReceipt, AgentRun), Error> {
        if request.run_etag.trim().is_empty() {
            return Err(Error::invalid_argument(
                "tool receipt commit requires a run ETag",
            ));
        }
        let receipt = request
            .tool_receipt
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("tool receipt is required"))?;
        let expected_name = self.scoped_name(receipt.name.clone(), "toolReceipts")?;
        let expected_run = self.scoped_name(receipt.agent_run_name.clone(), "agentRuns")?;
        self.step_name(receipt.agent_step_name.clone())?;
        self.normalize_reference(
            receipt
                .tool
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("tool reference is required"))?,
            None,
            None,
        )?;
        let expected_call = receipt.call_id.clone();
        validate_fence(
            &self.core,
            request
                .fence
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("agent fence is required"))?,
        )?;
        request.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        set_context(&self.core, &mut request, &prepared, &options)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(COMMIT_RECEIPT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_tool_receipt(request).await })
                },
            )
            .await?
            .into_inner();
        let accepted = response
            .tool_receipt
            .ok_or_else(|| Error::protocol("CommitToolReceipt response omitted its receipt"))?;
        let run = require_run(response.agent_run, &expected_run, "CommitToolReceipt")?;
        if accepted.name != expected_name || accepted.call_id != expected_call {
            return Err(Error::protocol(
                "CommitToolReceipt returned inconsistent durable evidence",
            ));
        }
        Ok((accepted, run))
    }

    fn parent(&self, value: &str, label: &str) -> Result<String, Error> {
        let expected = project_name(&self.core);
        if !value.is_empty() && value != expected {
            return Err(Error::invalid_argument(format!(
                "{label} parent must match the configured project"
            )));
        }
        Ok(expected)
    }

    fn scoped_name(&self, value: String, collection: &str) -> Result<String, Error> {
        let prefix = format!("{}/{collection}/", project_name(&self.core));
        let suffix = value.strip_prefix(&prefix).unwrap_or_default();
        if suffix.is_empty() || suffix.contains('/') {
            return Err(Error::invalid_argument(format!(
                "{collection} name must be scoped to the configured project"
            )));
        }
        valid_identifier(collection, suffix)?;
        Ok(value)
    }

    fn step_name(&self, value: String) -> Result<String, Error> {
        let prefix = format!("{}/agentRuns/", project_name(&self.core));
        let suffix = value.strip_prefix(&prefix).unwrap_or_default();
        let Some((run, sequence)) = suffix.split_once("/agentSteps/") else {
            return Err(Error::invalid_argument(
                "agent step name must be scoped to a configured-project run",
            ));
        };
        if run.contains('/') || sequence.contains('/') {
            return Err(Error::invalid_argument(
                "agent step name must be scoped to a configured-project run",
            ));
        }
        valid_identifier("agent run ID", run)?;
        valid_identifier("agent step ID", sequence)?;
        Ok(value)
    }

    fn normalize_reference(
        &self,
        reference: &mut ResourceRef,
        resource_type: Option<&str>,
        collection: Option<&str>,
    ) -> Result<(), Error> {
        if let Some(collection) = collection {
            let name = self.scoped_name(reference.name.clone(), collection)?;
            let id = name.rsplit('/').next().unwrap_or_default();
            if !reference.resource_id.is_empty() && reference.resource_id != id {
                return Err(Error::invalid_argument(
                    "resource reference ID conflicts with its name",
                ));
            }
            id.clone_into(&mut reference.resource_id);
        } else if reference.name.trim().is_empty()
            || reference.resource_id.trim().is_empty()
            || !reference.name.starts_with(&project_name(&self.core))
        {
            return Err(Error::invalid_argument(
                "resource reference must be complete and project scoped",
            ));
        }
        if let Some(expected) = resource_type {
            if !reference.resource_type.is_empty() && reference.resource_type != expected {
                return Err(Error::invalid_argument(
                    "resource reference type conflicts with generated semantics",
                ));
            }
            expected.clone_into(&mut reference.resource_type);
        } else if reference.resource_type.trim().is_empty() {
            return Err(Error::invalid_argument(
                "resource reference type is required",
            ));
        }
        normalize_scope(
            &self.core,
            &mut reference.tenant_id,
            &mut reference.project_id,
        )
    }

    fn normalize_definition(
        &self,
        definition: &mut AgentDefinition,
        creating: bool,
    ) -> Result<(), Error> {
        if creating
            && (!definition.name.is_empty()
                || !definition.uid.is_empty()
                || definition.revision != 0
                || !definition.etag.is_empty()
                || !definition.tenant_id.is_empty()
                || !definition.project_id.is_empty()
                || definition.create_time.is_some()
                || definition.update_time.is_some()
                || definition.delete_time.is_some())
        {
            return Err(Error::invalid_argument(
                "server-managed agent definition fields must be unset",
            ));
        }
        if !creating {
            self.scoped_name(definition.name.clone(), "agentDefinitions")?;
            normalize_scope(
                &self.core,
                &mut definition.tenant_id,
                &mut definition.project_id,
            )?;
        }
        self.normalize_reference(
            definition
                .workflow_definition
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("workflow definition is required"))?,
            Some("workflow_definition"),
            Some("workflowDefinitions"),
        )?;
        self.normalize_reference(
            definition
                .evaluation_suite
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("evaluation suite is required"))?,
            None,
            None,
        )?;
        if definition.eligible_tools.is_empty() {
            return Err(Error::invalid_argument(
                "agent definition requires at least one allowlisted tool",
            ));
        }
        for tool in &mut definition.eligible_tools {
            self.normalize_reference(tool, None, None)?;
        }
        Ok(())
    }
}

fn project_name(core: &ClientCore) -> String {
    let tenant = if core.config.identity.tenant_id().starts_with("tenants/") {
        core.config.identity.tenant_id().to_owned()
    } else {
        format!("tenants/{}", core.config.identity.tenant_id())
    };
    let project = core.config.identity.project_id();
    if project.starts_with("tenants/") {
        project.to_owned()
    } else if project.starts_with("projects/") {
        format!("{tenant}/{project}")
    } else {
        format!("{tenant}/projects/{project}")
    }
}

fn normalize_scope(
    core: &ClientCore,
    tenant_id: &mut String,
    project_id: &mut String,
) -> Result<(), Error> {
    if (!tenant_id.is_empty() && tenant_id != core.config.identity.tenant_id())
        || (!project_id.is_empty() && project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "resource scope conflicts with client identity",
        ));
    }
    core.config.identity.tenant_id().clone_into(tenant_id);
    core.config.identity.project_id().clone_into(project_id);
    Ok(())
}

fn valid_identifier(label: &str, value: &str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_alphanumeric() || index > 0 && matches!(byte, b'.' | b'_' | b'~' | b'-')
        })
    {
        return Err(Error::invalid_argument(format!("{label} is invalid")));
    }
    Ok(())
}

fn validate_page(page: Option<&mindclade_protocols::common::v1::PageRequest>) -> Result<(), Error> {
    if page.is_some_and(|value| value.page_size > MAXIMUM_PAGE_SIZE) {
        return Err(Error::invalid_argument("agent page size cannot exceed 200"));
    }
    Ok(())
}

fn valid_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn validate_fence(core: &ClientCore, fence: &mut LeaseFence) -> Result<(), Error> {
    if fence.job_id.trim().is_empty()
        || fence.run_id.trim().is_empty()
        || fence.attempt_id.trim().is_empty()
        || fence.lease_epoch == 0
        || !valid_digest(&fence.lease_token_digest)
    {
        return Err(Error::invalid_argument("agent fence is incomplete"));
    }
    let deadline = fence
        .deadline
        .as_ref()
        .ok_or_else(|| Error::invalid_argument("agent fence deadline is required"))?;
    let deadline = u64::try_from(deadline.seconds)
        .ok()
        .and_then(|seconds| {
            SystemTime::UNIX_EPOCH.checked_add(std::time::Duration::from_secs(seconds))
        })
        .and_then(|value| {
            value.checked_add(std::time::Duration::from_nanos(u64::from(
                deadline.nanos.max(0).cast_unsigned(),
            )))
        })
        .ok_or_else(|| Error::invalid_argument("agent fence deadline is invalid"))?;
    if deadline <= SystemTime::now() {
        return Err(Error::invalid_argument("agent fence is expired"));
    }
    normalize_scope(core, &mut fence.tenant_id, &mut fence.project_id)
}

fn protobuf_digest<T: Message>(value: &T) -> String {
    let digest = Sha256::digest(value.encode_to_vec());
    format!("sha256:{digest:x}")
}

trait ContextMutation: Message + Clone {
    fn context_mut(&mut self) -> &mut Option<mindclade_protocols::common::v1::CommandContext>;
}

macro_rules! context_mutation {
    ($($type:ty),+ $(,)?) => {$(
        impl ContextMutation for $type {
            fn context_mut(&mut self) -> &mut Option<mindclade_protocols::common::v1::CommandContext> {
                &mut self.context
            }
        }
    )+};
}

context_mutation!(
    CreateAgentDefinitionRequest,
    UpdateAgentDefinitionRequest,
    StartAgentRunRequest,
    CancelAgentRunRequest,
    CommitAgentStepRequest,
    CommitToolReceiptRequest,
);

fn set_context<T: ContextMutation>(
    core: &ClientCore,
    request: &mut T,
    prepared: &crate::request::PreparedCall,
    options: &SubmitOptions,
) -> Result<(), Error> {
    *request.context_mut() = None;
    let digest = protobuf_digest(request);
    let mut context = prepared.command_context(&core.config, options)?;
    context.canonical_request_digest = digest;
    *request.context_mut() = Some(context);
    Ok(())
}

fn require_operation(value: Option<Operation>, method: &str) -> Result<Operation, Error> {
    let operation = value.ok_or_else(|| {
        Error::protocol(format!("{method} response omitted its durable operation"))
    })?;
    if operation.operation_id.trim().is_empty() {
        return Err(Error::protocol(format!(
            "{method} response returned an invalid operation"
        )));
    }
    Ok(operation)
}

fn require_run(value: Option<AgentRun>, name: &str, method: &str) -> Result<AgentRun, Error> {
    let run = value.ok_or_else(|| Error::protocol(format!("{method} response omitted its run")))?;
    if run.name != name {
        return Err(Error::protocol(format!(
            "{method} response changed run identity"
        )));
    }
    Ok(run)
}

fn request_sequence(step: &AgentStep, run: &AgentRun) -> Result<u64, Error> {
    run.next_step_sequence
        .checked_sub(1)
        .filter(|value| *value == step.sequence)
        .ok_or_else(|| Error::protocol("CommitAgentStep returned an invalid run sequence"))
}
