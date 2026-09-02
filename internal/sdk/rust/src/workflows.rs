use std::{
    fmt,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    common::v1::{PageRequest, ResourceRef},
    internal::workflow::v1::{
        CancelWorkflowRunRequest, CommitWorkflowTransitionRequest, CreateWorkflowDefinitionRequest,
        GetWorkflowDefinitionRequest, GetWorkflowRunRequest, ListWorkflowDefinitionsRequest,
        ListWorkflowRunsRequest, StartWorkflowRunRequest, UpdateWorkflowDefinitionRequest,
        WatchWorkflowRunRequest, WatchWorkflowRunResponse,
    },
    job::v1::{LeaseFence, Operation},
    workflow::v1::{WorkflowDefinition, WorkflowRun, WorkflowRunState},
};
use prost::Message;
use sha2::{Digest, Sha256};

use crate::{
    CallOptions, CancellationToken, ClientCore, Error, Page, Pages, SubmitOptions, WatchNext,
    WatchOptions, WatchStream,
    operations::{NextUpdate, OpenFuture, ResumableWatch, WatchAction, Watcher},
    request::{PreparedCall, initial_page_token, page_request},
    retry::registered_method_policy,
};

const CREATE: &str = "/mindclade.internal.workflow.v1.WorkflowService/CreateWorkflowDefinition";
const UPDATE: &str = "/mindclade.internal.workflow.v1.WorkflowService/UpdateWorkflowDefinition";
const GET_DEFINITION: &str =
    "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowDefinition";
const LIST_DEFINITIONS: &str =
    "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowDefinitions";
const START: &str = "/mindclade.internal.workflow.v1.WorkflowService/StartWorkflowRun";
const GET_RUN: &str = "/mindclade.internal.workflow.v1.WorkflowService/GetWorkflowRun";
const LIST_RUNS: &str = "/mindclade.internal.workflow.v1.WorkflowService/ListWorkflowRuns";
const CANCEL: &str = "/mindclade.internal.workflow.v1.WorkflowService/CancelWorkflowRun";
const COMMIT: &str = "/mindclade.internal.workflow.v1.WorkflowService/CommitWorkflowTransition";
const WATCH: &str = "/mindclade.internal.workflow.v1.WorkflowService/WatchWorkflowRun";
const MAX_PAGE_SIZE: u32 = 200;
const DEFAULT_WATCH_TIMEOUT: Duration = Duration::from_mins(30);

/// A generated workflow run that reached a non-success terminal state. Debug
/// and display intentionally omit the generated failure payload.
pub struct WorkflowRunFailure {
    run: WorkflowRun,
}

impl WorkflowRunFailure {
    #[must_use]
    pub fn run(&self) -> &WorkflowRun {
        &self.run
    }

    #[must_use]
    pub fn into_run(self) -> WorkflowRun {
        self.run
    }
}

impl WorkflowRunFailure {
    /// Projects this durable failure onto the sanitized SDK error hierarchy.
    ///
    /// The generated workflow run stays authoritative; only bounded,
    /// non-secret fields of its structured detail are copied out, and the
    /// server's own message text is never used.
    #[must_use]
    pub fn as_error(&self) -> Error {
        // A workflow run is not an operation, so no operation identity is
        // asserted here; one is adopted only if the server's structured detail
        // names an operation subject itself.
        Error::operation_failed("", self.run.failure.as_ref())
    }
}

impl fmt::Debug for WorkflowRunFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("WorkflowRunFailure")
            .field("name", &self.run.name)
            .field("state", &self.run.state)
            .field("failure", &self.run.failure.as_ref().map(|_| "<redacted>"))
            .finish()
    }
}

impl fmt::Display for WorkflowRunFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "mindclade workflow {} terminated unsuccessfully (state={})",
            self.run.name, self.run.state
        )
    }
}

impl std::error::Error for WorkflowRunFailure {}

/// Terminal wait error preserving either normalized SDK state or a generated
/// failed workflow run.
#[derive(Debug)]
pub enum WorkflowWaitError {
    Sdk(Error),
    Workflow(Box<WorkflowRunFailure>),
}

impl From<Error> for WorkflowWaitError {
    fn from(value: Error) -> Self {
        Self::Sdk(value)
    }
}

impl fmt::Display for WorkflowWaitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Sdk(value) => value.fmt(formatter),
            Self::Workflow(value) => value.fmt(formatter),
        }
    }
}

impl WorkflowWaitError {
    #[must_use]
    pub fn workflow_failure(&self) -> Option<&WorkflowRunFailure> {
        match self {
            Self::Sdk(_) => None,
            Self::Workflow(failure) => Some(failure),
        }
    }

    #[must_use]
    pub fn sdk_error(&self) -> Option<&Error> {
        match self {
            Self::Sdk(error) => Some(error),
            Self::Workflow(_) => None,
        }
    }
}

impl std::error::Error for WorkflowWaitError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Sdk(error) => Some(error),
            Self::Workflow(error) => Some(error),
        }
    }
}

/// Runtime policy for a resumable workflow watch.
#[derive(Clone, Debug)]
pub struct WorkflowWatchOptions {
    call: CallOptions,
    timeout: Duration,
}

impl WorkflowWatchOptions {
    #[must_use]
    pub fn new() -> Self {
        Self {
            call: CallOptions::default(),
            timeout: DEFAULT_WATCH_TIMEOUT,
        }
    }

    #[must_use]
    pub fn with_call_options(mut self, call: CallOptions) -> Self {
        self.call = call;
        self
    }

    /// Sets the total watch deadline including reconnects.
    ///
    /// # Errors
    ///
    /// Returns an error for zero or more than twenty-four hours.
    pub fn with_timeout(mut self, timeout: Duration) -> Result<Self, Error> {
        if timeout.is_zero() || timeout > Duration::from_hours(24) {
            return Err(Error::invalid_argument(
                "workflow watch timeout must be positive and at most twenty-four hours",
            ));
        }
        self.timeout = timeout;
        Ok(self)
    }
}

impl Default for WorkflowWatchOptions {
    fn default() -> Self {
        Self::new()
    }
}

impl From<WorkflowWatchOptions> for WatchOptions {
    fn from(value: WorkflowWatchOptions) -> Self {
        Self::new()
            .with_call_options(value.call)
            .with_timeout(value.timeout)
            .unwrap_or_else(|_| Self::new())
    }
}

/// Private workflow lifecycle API backed exclusively by generated contracts.
#[derive(Clone)]
pub struct Workflows {
    core: Arc<ClientCore>,
}

impl Workflows {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Creates a generated definition and returns its durable operation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, context, transport, or response.
    pub async fn create_definition(
        &self,
        mut request: CreateWorkflowDefinitionRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        normalize_parent(&self.core, &mut request.parent)?;
        valid_id("workflow definition ID", &request.workflow_definition_id)?;
        let definition = request
            .workflow_definition
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("workflow definition is required"))?;
        normalize_definition(&self.core, definition)?;
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(CREATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.create_workflow_definition(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CreateWorkflowDefinition")
    }

    /// Updates generated definition metadata under a field mask and `ETag`.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/concurrency state or RPC failure.
    pub async fn update_definition(
        &self,
        mut request: UpdateWorkflowDefinitionRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let definition = request
            .workflow_definition
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("workflow definition is required"))?;
        workflow_name(&self.core, &definition.name, "workflowDefinitions")?;
        normalize_definition(&self.core, definition)?;
        if request
            .update_mask
            .as_ref()
            .is_none_or(|mask| mask.paths.is_empty())
            || request.etag.trim().is_empty()
        {
            return Err(Error::invalid_argument(
                "workflow update requires a field mask and ETag",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(UPDATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.update_workflow_definition(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "UpdateWorkflowDefinition")
    }

    /// Reads one generated workflow definition.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, transport, or response.
    pub async fn get_definition(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<WorkflowDefinition, Error> {
        let name = workflow_name(&self.core, &name.into(), "workflowDefinitions")?;
        let prepared = options.prepare(&self.core.config);
        self.core
            .unary(
                GetWorkflowDefinitionRequest {
                    name,
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_policy(GET_DEFINITION),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_workflow_definition(request).await })
                },
            )
            .await?
            .into_inner()
            .workflow_definition
            .ok_or_else(|| Error::protocol("GetWorkflowDefinition response omitted its definition"))
    }

    /// Lists one bounded, opaque-token page of definitions.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/pagination or RPC failure.
    pub fn list_definitions(
        &self,
        mut request: ListWorkflowDefinitionsRequest,
        options: CallOptions,
    ) -> Result<Pages<WorkflowDefinition>, Error> {
        normalize_parent(&self.core, &mut request.parent)?;
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
                            registered_method_policy(LIST_DEFINITIONS),
                            None,
                            |transport, request| {
                                Box::pin(async move {
                                    transport.list_workflow_definitions(request).await
                                })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.workflow_definitions,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Starts a generated durable workflow run.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/context or RPC failure.
    pub async fn start_run(
        &self,
        mut request: StartWorkflowRunRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        normalize_parent(&self.core, &mut request.parent)?;
        valid_id("workflow run ID", &request.workflow_run_id)?;
        let run = request
            .workflow_run
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("workflow run is required"))?;
        normalize_run(&self.core, run)?;
        let definition = run
            .definition
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("workflow run definition is required"))?;
        reference_in_scope(&self.core, definition, "workflow_definition")?;
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(START),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.start_workflow_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "StartWorkflowRun")
    }

    /// Reads one generated workflow run.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, transport, or response.
    pub async fn get_run(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<WorkflowRun, Error> {
        let name = workflow_name(&self.core, &name.into(), "workflowRuns")?;
        let prepared = options.prepare(&self.core.config);
        self.core
            .unary(
                GetWorkflowRunRequest {
                    name,
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_policy(GET_RUN),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_workflow_run(request).await })
                },
            )
            .await?
            .into_inner()
            .workflow_run
            .ok_or_else(|| Error::protocol("GetWorkflowRun response omitted its run"))
    }

    /// Lists one bounded, opaque-token page of workflow runs.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope/pagination or RPC failure.
    pub fn list_runs(
        &self,
        mut request: ListWorkflowRunsRequest,
        options: CallOptions,
    ) -> Result<Pages<WorkflowRun>, Error> {
        normalize_parent(&self.core, &mut request.parent)?;
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
                            registered_method_policy(LIST_RUNS),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_workflow_runs(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    Ok(Page::new(
                        response.workflow_runs,
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
    /// Returns an error for invalid scope/concurrency state or RPC failure.
    pub async fn cancel_run(
        &self,
        mut request: CancelWorkflowRunRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        request.name = workflow_name(&self.core, &request.name, "workflowRuns")?;
        if request.etag.trim().is_empty()
            || request.reason.trim().is_empty()
            || request.reason.len() > 1024
        {
            return Err(Error::invalid_argument(
                "workflow cancellation requires an ETag and bounded reason",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(CANCEL),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.cancel_workflow_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_operation(response.operation, "CancelWorkflowRun")
    }

    /// Commits a generated transition under optimistic concurrency and the
    /// current scheduler fence. Raw lease material is metadata-only.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, `ETag`, fence/token, or RPC response.
    pub async fn commit_transition(
        &self,
        mut request: CommitWorkflowTransitionRequest,
        options: SubmitOptions,
    ) -> Result<WorkflowRun, Error> {
        let run = request
            .workflow_run
            .as_mut()
            .ok_or_else(|| Error::invalid_argument("workflow transition requires a run"))?;
        workflow_name(&self.core, &run.name, "workflowRuns")?;
        normalize_run(&self.core, run)?;
        if request.etag.trim().is_empty() {
            return Err(Error::invalid_argument(
                "workflow transition requires an ETag",
            ));
        }
        normalize_fence(
            &self.core,
            request
                .fence
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("workflow transition requires a fence"))?,
        )?;
        request.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        request.context = Some(command_context(&self.core, &prepared, &options, &request)?);
        let name = request
            .workflow_run
            .as_ref()
            .map(|value| value.name.clone())
            .unwrap_or_default();
        let expected = request.expected_transition_sequence.saturating_add(1);
        let key = options.idempotency_key.clone();
        let run = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_policy(COMMIT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_workflow_transition(request).await })
                },
            )
            .await?
            .into_inner()
            .workflow_run
            .ok_or_else(|| Error::protocol("CommitWorkflowTransition response omitted its run"))?;
        if run.name != name || run.transition_sequence != expected {
            return Err(Error::protocol(
                "CommitWorkflowTransition returned inconsistent durable state",
            ));
        }
        Ok(run)
    }

    /// Opens a cancellation-aware resumable workflow watch.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or watch policy.
    pub fn watch(
        &self,
        name: impl Into<String>,
        after_transition_sequence: u64,
        options: &WorkflowWatchOptions,
        cancellation: CancellationToken,
    ) -> Result<WorkflowWatch, Error> {
        let name = workflow_name(&self.core, &name.into(), "workflowRuns")?;
        let call = options.call.bounded_by(options.timeout);
        Ok(WorkflowWatch {
            inner: Watcher::new(
                Arc::clone(&self.core),
                call.prepare(&self.core.config),
                cancellation,
                WorkflowWatchState {
                    name,
                    last_sequence: after_transition_sequence,
                },
            ),
        })
    }

    /// Resumes a watch from a previously acknowledged transition sequence.
    ///
    /// This is the uniform long-running-operation resume verb: it is exactly
    /// [`Workflows::watch`] with the caller's durable cursor made explicit.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or watch policy.
    pub fn resume_watch(
        &self,
        name: impl Into<String>,
        after_transition_sequence: u64,
        options: &WorkflowWatchOptions,
        cancellation: CancellationToken,
    ) -> Result<WorkflowWatch, Error> {
        self.watch(name, after_transition_sequence, options, cancellation)
    }

    /// Watches until the generated run reaches terminal success or failure.
    ///
    /// # Errors
    ///
    /// Returns a typed generated failure, or a normalized SDK error.
    pub async fn wait(
        &self,
        name: impl Into<String>,
        after_transition_sequence: u64,
        options: WorkflowWatchOptions,
        cancellation: CancellationToken,
    ) -> Result<WorkflowRun, WorkflowWaitError> {
        let mut watch = self.watch(name, after_transition_sequence, &options, cancellation)?;
        while let Some(run) = watch.next().await? {
            if terminal(run.state) {
                return terminal_success(run);
            }
        }
        Err(Error::protocol("workflow watch ended before a terminal revision").into())
    }
}

/// Durable generated workflow watch with strict identity and sequence checks.
pub struct WorkflowWatch {
    inner: Watcher<WorkflowWatchState>,
}

impl WorkflowWatch {
    /// Reads the next strictly contiguous generated revision.
    ///
    /// # Errors
    ///
    /// Returns an error for cancellation, deadline, retry exhaustion, identity
    /// mismatch, missing payload, or non-contiguous sequence.
    pub async fn next(&mut self) -> Result<Option<WorkflowRun>, Error> {
        let Some(response) = self.inner.next().await? else {
            return Ok(None);
        };
        response
            .workflow_run
            .map(Some)
            .ok_or_else(|| Error::protocol("workflow watch response omitted its run"))
    }

    /// The last acknowledged transition sequence. A reconnect resumes here.
    #[must_use]
    pub fn last_sequence(&self) -> u64 {
        self.inner.cursor()
    }

    /// Consumes the watcher and yields its runs as a `Stream`.
    #[must_use]
    pub fn into_stream(self) -> WatchStream<Self> {
        WatchStream::new(self)
    }
}

impl WatchNext for WorkflowWatch {
    type Update = WorkflowRun;

    fn next_update(&mut self) -> NextUpdate<'_, Self::Update> {
        Box::pin(self.next())
    }
}

/// Workflow-specific watch rules: stable run identity and strictly contiguous
/// transition sequences.
struct WorkflowWatchState {
    name: String,
    last_sequence: u64,
}

impl ResumableWatch for WorkflowWatchState {
    type Update = WatchWorkflowRunResponse;
    type Cursor = u64;

    fn route(&self) -> &'static str {
        WATCH
    }

    fn label(&self) -> &'static str {
        "workflow"
    }

    fn stream_ended_message(&self) -> &'static str {
        "workflow watch ended before terminal state"
    }

    fn cursor(&self) -> u64 {
        self.last_sequence
    }

    fn open(
        &self,
        core: &Arc<ClientCore>,
        prepared: &PreparedCall,
        attempt: u8,
    ) -> OpenFuture<Self::Update> {
        let core = Arc::clone(core);
        let prepared = prepared.clone();
        let name = self.name.clone();
        let after_transition_sequence = self.last_sequence;
        Box::pin(async move {
            // `WatchWorkflowRunRequest` deliberately carries no deadline
            // field; the caller's budget is enforced by the SDK alone.
            let request = WatchWorkflowRunRequest {
                name,
                after_transition_sequence,
            };
            let request = core
                .request(request, &prepared, None, attempt, WATCH)
                .await?;
            let remaining = prepared.remaining()?;
            let response =
                tokio::time::timeout(remaining, core.transport.watch_workflow_run(request))
                    .await
                    .map_err(|_| Error::deadline_exceeded())?
                    .map_err(|status| Error::from_status(&status))?;
            Ok(response.into_inner())
        })
    }

    fn accept(
        &mut self,
        response: WatchWorkflowRunResponse,
    ) -> Result<WatchAction<WatchWorkflowRunResponse>, Error> {
        let run = response
            .workflow_run
            .as_ref()
            .ok_or_else(|| Error::protocol("workflow watch response omitted its run"))?;
        if run.name != self.name {
            return Err(Error::protocol("workflow watch returned a different run"));
        }
        if run.transition_sequence <= self.last_sequence {
            return Ok(WatchAction::Skip);
        }
        if run.transition_sequence != self.last_sequence.saturating_add(1) {
            return Err(Error::protocol(
                "workflow watch returned a non-contiguous transition sequence",
            ));
        }
        let terminal = terminal(run.state);
        self.last_sequence = run.transition_sequence;
        if terminal {
            Ok(WatchAction::Terminal(response))
        } else {
            Ok(WatchAction::Emit(response))
        }
    }
}

pub(crate) fn project_name(core: &ClientCore) -> String {
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

pub(crate) fn normalize_parent(core: &ClientCore, parent: &mut String) -> Result<(), Error> {
    let expected = project_name(core);
    if !parent.is_empty() && *parent != expected {
        return Err(Error::invalid_argument(
            "parent does not match configured project",
        ));
    }
    *parent = expected;
    Ok(())
}

pub(crate) fn workflow_name(
    core: &ClientCore,
    name: &str,
    collection: &str,
) -> Result<String, Error> {
    let prefix = format!("{}/{collection}/", project_name(core));
    let suffix = name.strip_prefix(&prefix).ok_or_else(|| {
        Error::invalid_argument("workflow resource is outside configured project")
    })?;
    if suffix.is_empty() || suffix.contains('/') {
        return Err(Error::invalid_argument("workflow resource name is invalid"));
    }
    Ok(name.to_owned())
}

pub(crate) fn validate_page(page: Option<&PageRequest>) -> Result<(), Error> {
    if page.is_some_and(|value| value.page_size > MAX_PAGE_SIZE) {
        return Err(Error::invalid_argument(
            "page size must be between zero and 200",
        ));
    }
    Ok(())
}

pub(crate) fn valid_sha256(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

pub(crate) fn command_context<M: Message>(
    core: &ClientCore,
    prepared: &PreparedCall,
    options: &SubmitOptions,
    request: &M,
) -> Result<mindclade_protocols::common::v1::CommandContext, Error> {
    let mut context = prepared.command_context(&core.config, options)?;
    context.canonical_request_digest =
        format!("sha256:{:x}", Sha256::digest(request.encode_to_vec()));
    Ok(context)
}

fn valid_id(label: &str, value: &str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
    {
        return Err(Error::invalid_argument(format!("{label} is invalid")));
    }
    Ok(())
}

fn normalize_definition(
    core: &ClientCore,
    definition: &mut WorkflowDefinition,
) -> Result<(), Error> {
    if (!definition.tenant_id.is_empty()
        && definition.tenant_id != core.config.identity.tenant_id())
        || (!definition.project_id.is_empty()
            && definition.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "workflow definition scope does not match client",
        ));
    }
    core.config
        .identity
        .tenant_id()
        .clone_into(&mut definition.tenant_id);
    core.config
        .identity
        .project_id()
        .clone_into(&mut definition.project_id);
    for tool in &definition.eligible_tools {
        reference_in_scope(core, tool, "workflow eligible tool")?;
    }
    Ok(())
}

fn normalize_run(core: &ClientCore, run: &mut WorkflowRun) -> Result<(), Error> {
    if (!run.tenant_id.is_empty() && run.tenant_id != core.config.identity.tenant_id())
        || (!run.project_id.is_empty() && run.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "workflow run scope does not match client",
        ));
    }
    core.config
        .identity
        .tenant_id()
        .clone_into(&mut run.tenant_id);
    core.config
        .identity
        .project_id()
        .clone_into(&mut run.project_id);
    Ok(())
}

fn reference_in_scope(
    core: &ClientCore,
    reference: &ResourceRef,
    label: &str,
) -> Result<(), Error> {
    if reference.resource_type.trim().is_empty()
        || reference.resource_id.trim().is_empty()
        || reference.name.trim().is_empty()
        || (!reference.tenant_id.is_empty()
            && reference.tenant_id != core.config.identity.tenant_id())
        || (!reference.project_id.is_empty()
            && reference.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(format!(
            "{label} is outside configured scope"
        )));
    }
    Ok(())
}

fn normalize_fence(core: &ClientCore, fence: &mut LeaseFence) -> Result<(), Error> {
    if fence.job_id.trim().is_empty()
        || fence.run_id.trim().is_empty()
        || fence.attempt_id.trim().is_empty()
        || fence.lease_epoch == 0
        || !valid_sha256(&fence.lease_token_digest)
    {
        return Err(Error::invalid_argument(
            "workflow fence is incomplete or missing its token digest",
        ));
    }
    let deadline = fence
        .deadline
        .as_ref()
        .ok_or_else(|| Error::invalid_argument("workflow fence deadline is required"))?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::invalid_argument("system clock precedes Unix epoch"))?;
    if deadline.seconds < 0
        || u64::try_from(deadline.seconds).ok().is_none_or(|seconds| {
            seconds < now.as_secs()
                || (seconds == now.as_secs()
                    && u32::try_from(deadline.nanos).unwrap_or_default() <= now.subsec_nanos())
        })
    {
        return Err(Error::invalid_argument(
            "workflow fence is expired or invalid",
        ));
    }
    if (!fence.tenant_id.is_empty() && fence.tenant_id != core.config.identity.tenant_id())
        || (!fence.project_id.is_empty() && fence.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "workflow fence scope does not match client",
        ));
    }
    core.config
        .identity
        .tenant_id()
        .clone_into(&mut fence.tenant_id);
    core.config
        .identity
        .project_id()
        .clone_into(&mut fence.project_id);
    Ok(())
}

fn require_operation(operation: Option<Operation>, method: &str) -> Result<Operation, Error> {
    let operation = operation
        .ok_or_else(|| Error::protocol(format!("{method} response omitted its operation")))?;
    if operation.operation_id.trim().is_empty() {
        return Err(Error::protocol(format!(
            "{method} response operation has no identity"
        )));
    }
    Ok(operation)
}

fn terminal(state: i32) -> bool {
    matches!(
        WorkflowRunState::try_from(state).ok(),
        Some(
            WorkflowRunState::Succeeded
                | WorkflowRunState::Failed
                | WorkflowRunState::Cancelled
                | WorkflowRunState::Expired
        )
    )
}

fn terminal_success(run: WorkflowRun) -> Result<WorkflowRun, WorkflowWaitError> {
    if run.state == WorkflowRunState::Succeeded as i32 {
        Ok(run)
    } else {
        Err(WorkflowWaitError::Workflow(Box::new(WorkflowRunFailure {
            run,
        })))
    }
}
