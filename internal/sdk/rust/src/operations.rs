use std::{
    fmt,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

use mindclade_protocols::{
    internal::job::v1::{
        CancelOperationRequest, CancelOperationResponse, GetOperationRequest, GetOperationResponse,
        ListOperationsRequest, WatchOperationRequest, WatchOperationResponse,
    },
    job::v1::{Operation, OperationState},
};
use tokio::sync::Notify;
use tonic::codegen::tokio_stream::StreamExt;

use crate::{
    CallOptions, ClientCore, Error, OperationStream, Page, Pages, SubmitOptions,
    request::{PreparedCall, initial_page_token, page_request, validate_resource_value},
    retry::registered_method_policy,
};

const DEFAULT_WAIT_TIMEOUT: Duration = Duration::from_mins(30);
const GET_OPERATION: &str = "/mindclade.internal.job.v1.OperationService/GetOperation";
const CANCEL_OPERATION: &str = "/mindclade.internal.job.v1.OperationService/CancelOperation";
const WATCH_OPERATION: &str = "/mindclade.internal.job.v1.OperationService/WatchOperation";
const LIST_OPERATIONS: &str = "/mindclade.internal.job.v1.OperationService/ListOperations";
const MAX_OPERATION_PAGE_SIZE: u32 = 200;

/// A remote terminal operation that did not succeed. The generated operation
/// remains available for programmatic inspection; display/debug output does
/// not render its server-provided error payload.
pub struct OperationFailure {
    operation: Operation,
}

impl OperationFailure {
    #[must_use]
    pub fn operation(&self) -> &Operation {
        &self.operation
    }

    #[must_use]
    pub fn into_operation(self) -> Operation {
        self.operation
    }

    /// Projects this durable failure onto the sanitized SDK error hierarchy.
    ///
    /// The generated operation stays authoritative; only bounded, non-secret
    /// fields of its structured detail are copied out, and the server's own
    /// message text is never used.
    #[must_use]
    pub fn as_error(&self) -> Error {
        Error::operation_failed(&self.operation.operation_id, self.operation.error.as_ref())
    }
}

impl fmt::Debug for OperationFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OperationFailure")
            .field("operation_id", &self.operation.operation_id)
            .field("state", &self.operation.state)
            .field(
                "error",
                &self.operation.error.as_ref().map(|_| "<redacted>"),
            )
            .finish()
    }
}

impl fmt::Display for OperationFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "mindclade operation {} terminated unsuccessfully (state={})",
            self.operation.operation_id, self.operation.state
        )
    }
}

impl std::error::Error for OperationFailure {}

/// Failure returned by terminal operation helpers.
#[derive(Debug)]
pub enum OperationWaitError {
    Sdk(Error),
    Operation(Box<OperationFailure>),
}

impl OperationWaitError {
    #[must_use]
    pub fn operation_failure(&self) -> Option<&OperationFailure> {
        match self {
            Self::Sdk(_) => None,
            Self::Operation(failure) => Some(failure),
        }
    }

    #[must_use]
    pub fn sdk_error(&self) -> Option<&Error> {
        match self {
            Self::Sdk(error) => Some(error),
            Self::Operation(_) => None,
        }
    }
}

impl From<Error> for OperationWaitError {
    fn from(error: Error) -> Self {
        Self::Sdk(error)
    }
}

impl fmt::Display for OperationWaitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Sdk(error) => error.fmt(formatter),
            Self::Operation(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for OperationWaitError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Sdk(error) => Some(error),
            Self::Operation(error) => Some(error),
        }
    }
}

/// Cooperative local cancellation for polling and streaming helpers.
#[derive(Clone, Default)]
pub struct CancellationToken {
    inner: Arc<CancellationState>,
}

#[derive(Default)]
struct CancellationState {
    cancelled: AtomicBool,
    notify: Notify,
}

impl CancellationToken {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn cancel(&self) {
        if !self.inner.cancelled.swap(true, Ordering::AcqRel) {
            self.inner.notify.notify_waiters();
        }
    }

    #[must_use]
    pub fn is_cancelled(&self) -> bool {
        self.inner.cancelled.load(Ordering::Acquire)
    }

    pub(crate) async fn cancelled(&self) {
        if self.is_cancelled() {
            return;
        }
        let notified = self.inner.notify.notified();
        if self.is_cancelled() {
            return;
        }
        notified.await;
    }
}

/// Runtime policy for operation polling.
#[derive(Clone, Debug)]
pub struct WaitOptions {
    call: CallOptions,
    timeout: Duration,
    poll_interval: Option<Duration>,
}

impl WaitOptions {
    #[must_use]
    pub fn new() -> Self {
        Self {
            call: CallOptions::default(),
            timeout: DEFAULT_WAIT_TIMEOUT,
            poll_interval: None,
        }
    }

    #[must_use]
    pub fn with_call_options(mut self, options: CallOptions) -> Self {
        self.call = options;
        self
    }

    /// Sets the overall polling deadline.
    ///
    /// # Errors
    ///
    /// Returns an error for a zero or unbounded duration.
    pub fn with_timeout(mut self, timeout: Duration) -> Result<Self, Error> {
        validate_wait_duration("operation wait timeout", timeout)?;
        self.timeout = timeout;
        Ok(self)
    }

    /// Overrides the configured polling interval.
    ///
    /// # Errors
    ///
    /// Returns an error for a zero or unbounded duration.
    pub fn with_poll_interval(mut self, interval: Duration) -> Result<Self, Error> {
        validate_wait_duration("operation poll interval", interval)?;
        self.poll_interval = Some(interval);
        Ok(self)
    }
}

impl Default for WaitOptions {
    fn default() -> Self {
        Self::new()
    }
}

/// Durable operation helpers over the generated operation client.
#[derive(Clone)]
pub struct Operations {
    core: Arc<ClientCore>,
}

impl Operations {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Returns a lazy, bounded cursor over project-scoped operations.
    ///
    /// The cursor iterates items transparently across pages and keeps
    /// page-level access. Every page is validated, not only the first.
    ///
    /// # Errors
    ///
    /// Returns an error for a cross-project parent or an oversized page. RPC
    /// failures and invalid returned operation state surface while advancing
    /// the cursor.
    pub fn list(
        &self,
        mut request: ListOperationsRequest,
        options: CallOptions,
    ) -> Result<Pages<Operation>, Error> {
        let parent = project_parent(&self.core.config);
        if !request.parent.is_empty() && request.parent != parent {
            return Err(Error::invalid_argument(
                "operation list parent must match the configured project",
            ));
        }
        if request
            .page
            .as_ref()
            .is_some_and(|page| page.page_size > MAX_OPERATION_PAGE_SIZE)
        {
            return Err(Error::invalid_argument(
                "operation page size cannot exceed 200",
            ));
        }
        request.parent = parent;
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
                            registered_method_policy(LIST_OPERATIONS),
                            None,
                            |transport, request| {
                                Box::pin(async move { transport.list_operations(request).await })
                            },
                        )
                        .await?;
                    let request_id = response.request_id().map(str::to_owned);
                    let response = response.into_inner();
                    for operation in &response.operations {
                        validate_listed_operation(&core, operation)?;
                    }
                    Ok(Page::new(
                        response.operations,
                        response.page,
                        response.read_time,
                        request_id,
                    ))
                }
            },
            token,
        ))
    }

    /// Reads the latest durable operation revision with bounded safe retries.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid name, credentials, transport status, or
    /// malformed response.
    pub async fn get(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<Operation, Error> {
        let name = name.into();
        validate_resource_value("operation name", &name)?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetOperationRequest {
                    name,
                    if_none_match: String::new(),
                },
                &prepared,
                registered_method_policy(GET_OPERATION),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_operation(request).await })
                },
            )
            .await?;
        extract_get_operation(response.into_inner())
    }

    /// Polls until the operation is terminal, the overall deadline expires, or
    /// local cancellation is requested.
    ///
    /// # Errors
    ///
    /// Returns an error when cancelled, timed out, or when an underlying read
    /// fails.
    pub async fn wait(
        &self,
        name: impl Into<String>,
        options: WaitOptions,
        cancellation: CancellationToken,
    ) -> Result<Operation, OperationWaitError> {
        let name = name.into();
        validate_resource_value("operation name", &name)?;
        let deadline = Instant::now() + options.timeout;
        let poll_interval = options
            .poll_interval
            .unwrap_or(self.core.config.poll_interval);

        loop {
            if cancellation.is_cancelled() {
                return Err(Error::cancelled().into());
            }
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .ok_or_else(Error::deadline_exceeded)?;
            let call = options.call.bounded_by(remaining);
            let operation = tokio::select! {
                biased;
                () = cancellation.cancelled() => return Err(Error::cancelled().into()),
                result = self.get(name.clone(), call) => result?,
            };
            if operation.done || is_terminal_failure(&operation) {
                return require_successful_terminal(operation);
            }

            let remaining = deadline
                .checked_duration_since(Instant::now())
                .ok_or_else(Error::deadline_exceeded)?;
            let delay = poll_interval.min(remaining);
            tokio::select! {
                biased;
                () = cancellation.cancelled() => return Err(Error::cancelled().into()),
                () = self.core.sleeper.sleep(delay) => {}
            }
        }
    }

    /// Records durable remote cancellation using an idempotency key and `ETag`.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid command metadata, credentials, an RPC
    /// failure, or a malformed response.
    pub async fn cancel(
        &self,
        name: impl Into<String>,
        etag: impl Into<String>,
        reason: impl Into<String>,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        let name = name.into();
        let etag = etag.into();
        let reason = reason.into().trim().to_owned();
        validate_resource_value("operation name", &name)?;
        validate_resource_value("operation ETag", &etag)?;
        if reason.is_empty()
            || reason.len() > 1_024
            || reason
                .bytes()
                .any(|byte| matches!(byte, b'\0' | b'\r' | b'\n'))
        {
            return Err(Error::invalid_argument(
                "cancellation reason must be non-empty bounded text without control delimiters",
            ));
        }
        let prepared = options.call.prepare(&self.core.config);
        let context = prepared.command_context(&self.core.config, &options)?;
        let idempotency_key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CancelOperationRequest {
                    context: Some(context),
                    name,
                    etag,
                    reason,
                },
                &prepared,
                registered_method_policy(CANCEL_OPERATION),
                Some(&idempotency_key),
                |transport, request| {
                    Box::pin(async move { transport.cancel_operation(request).await })
                },
            )
            .await?;
        extract_cancel_operation(response.into_inner())
    }

    /// Opens the generated resumable watch stream. Local cancellation is
    /// checked while opening and while reading updates.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid input, cancellation, credentials, or a
    /// failure to establish the stream.
    pub fn watch(
        &self,
        name: impl Into<String>,
        after_sequence: u64,
        options: &CallOptions,
        cancellation: CancellationToken,
    ) -> Result<OperationWatch, Error> {
        let name = name.into();
        validate_resource_value("operation name", &name)?;
        let prepared = options.prepare(&self.core.config);
        Ok(OperationWatch {
            core: Arc::clone(&self.core),
            name,
            prepared,
            stream: None,
            cancellation,
            last_sequence: after_sequence,
            consecutive_failures: 0,
            terminal: false,
        })
    }

    /// Watches until the service emits a terminal operation.
    ///
    /// # Errors
    ///
    /// Returns an error when the watch is cancelled, fails remotely, violates
    /// sequence invariants, or ends before a terminal revision.
    pub async fn watch_until_done(
        &self,
        name: impl Into<String>,
        after_sequence: u64,
        options: CallOptions,
        cancellation: CancellationToken,
    ) -> Result<Operation, OperationWaitError> {
        let mut watch = self
            .watch(name, after_sequence, &options, cancellation)
            .map_err(OperationWaitError::from)?;
        while let Some(update) = watch.next().await.map_err(OperationWaitError::from)? {
            let operation = update
                .operation
                .ok_or_else(|| Error::protocol("operation watch update omitted its operation"))?;
            if operation.done || is_terminal_failure(&operation) {
                return require_successful_terminal(operation);
            }
        }
        Err(Error::protocol("operation watch ended before a terminal revision").into())
    }
}

/// Cancellation-aware wrapper around the generated operation update stream.
pub struct OperationWatch {
    core: Arc<ClientCore>,
    name: String,
    prepared: PreparedCall,
    stream: Option<OperationStream>,
    cancellation: CancellationToken,
    last_sequence: u64,
    consecutive_failures: u8,
    terminal: bool,
}

impl OperationWatch {
    /// Reads the next strictly monotonic generated watch response.
    ///
    /// # Errors
    ///
    /// Returns an error for cancellation, a remote stream status, or an
    /// invalid sequence.
    pub async fn next(&mut self) -> Result<Option<WatchOperationResponse>, Error> {
        loop {
            if self.terminal {
                return Ok(None);
            }
            if self.cancellation.is_cancelled() {
                return Err(Error::cancelled());
            }
            if self.stream.is_none() {
                match self.connect().await {
                    Ok(stream) => self.stream = Some(stream),
                    Err(error) => {
                        self.retry_or_fail(error).await?;
                        continue;
                    }
                }
            }
            let stream = self
                .stream
                .as_mut()
                .ok_or_else(|| Error::protocol("operation watch stream was not established"))?;
            let update = tokio::select! {
                biased;
                () = self.cancellation.cancelled() => return Err(Error::cancelled()),
                update = stream.next() => update,
            };
            match update {
                None => {
                    self.stream = None;
                    self.retry_or_fail(Error::from_status(&tonic::Status::unavailable(
                        "operation watch ended before a terminal revision",
                    )))
                    .await?;
                }
                Some(Err(status)) => {
                    self.stream = None;
                    self.retry_or_fail(Error::from_status(&status)).await?;
                }
                Some(Ok(response)) => {
                    if response.sequence == 0 {
                        return Err(Error::protocol(
                            "operation watch returned an invalid zero sequence",
                        ));
                    }
                    if response.sequence <= self.last_sequence {
                        continue;
                    }
                    let operation = response.operation.as_ref().ok_or_else(|| {
                        Error::protocol("operation watch update omitted its operation")
                    })?;
                    if operation.operation_id != self.name {
                        return Err(Error::protocol(
                            "operation watch returned a different operation",
                        ));
                    }
                    self.consecutive_failures = 0;
                    self.last_sequence = response.sequence;
                    self.terminal = operation.done || is_terminal_failure(operation);
                    return Ok(Some(response));
                }
            }
        }
    }

    async fn connect(&self) -> Result<OperationStream, Error> {
        if !matches!(
            registered_method_policy(WATCH_OPERATION),
            crate::retry::CallSafety::Safe
        ) {
            return Err(Error::protocol("operation watch safety policy is missing"));
        }
        let request = WatchOperationRequest {
            name: self.name.clone(),
            after_sequence: self.last_sequence,
            deadline: Some(self.prepared.deadline_timestamp()?),
        };
        let request = tokio::select! {
            biased;
            () = self.cancellation.cancelled() => return Err(Error::cancelled()),
            result = self.core.request(request, &self.prepared, None, self.consecutive_failures) => result?,
        };
        let remaining = self
            .prepared
            .deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(Error::deadline_exceeded)?;
        let response = tokio::select! {
            biased;
            () = self.cancellation.cancelled() => return Err(Error::cancelled()),
            result = tokio::time::timeout(
                remaining,
                self.core.transport.watch_operation(request),
            ) => result
                .map_err(|_| Error::deadline_exceeded())?
                .map_err(|status| Error::from_status(&status))?,
        };
        Ok(response.into_inner())
    }

    async fn retry_or_fail(&mut self, error: Error) -> Result<(), Error> {
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
        if !error.is_retryable() || self.consecutive_failures >= self.core.config.retry.max_attempts
        {
            return Err(error);
        }
        let remaining = self
            .prepared
            .deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(Error::deadline_exceeded)?;
        // A server-pinned `retry-after-ms` is clamped to the configured maximum
        // backoff, exactly as the unary retry loop clamps it.
        let delay = error.retry_after().map_or_else(
            || self.core.backoff(self.consecutive_failures),
            |hint| hint.min(self.core.config.retry.max_backoff),
        );
        if delay >= remaining {
            return Err(Error::deadline_exceeded());
        }
        tokio::select! {
            biased;
            () = self.cancellation.cancelled() => Err(Error::cancelled()),
            () = self.core.sleeper.sleep(delay) => Ok(()),
        }
    }

    #[must_use]
    pub fn last_sequence(&self) -> u64 {
        self.last_sequence
    }
}

fn is_terminal_failure(operation: &Operation) -> bool {
    operation.error.is_some()
        || operation.state == OperationState::Failed as i32
        || operation.state == OperationState::Cancelled as i32
}

fn require_successful_terminal(operation: Operation) -> Result<Operation, OperationWaitError> {
    if is_terminal_failure(&operation) {
        return Err(OperationWaitError::Operation(Box::new(OperationFailure {
            operation,
        })));
    }
    if !operation.done || operation.state != OperationState::Succeeded as i32 {
        return Err(Error::protocol("done operation has a non-terminal-success state").into());
    }
    Ok(operation)
}

fn extract_get_operation(response: GetOperationResponse) -> Result<Operation, Error> {
    response
        .operation
        .ok_or_else(|| Error::protocol("GetOperation response omitted its operation"))
}

fn extract_cancel_operation(response: CancelOperationResponse) -> Result<Operation, Error> {
    response
        .operation
        .ok_or_else(|| Error::protocol("CancelOperation response omitted its operation"))
}

fn validate_wait_duration(name: &str, value: Duration) -> Result<(), Error> {
    if value.is_zero() || value > Duration::from_hours(24) {
        return Err(Error::invalid_argument(format!(
            "{name} must be positive and at most twenty-four hours"
        )));
    }
    Ok(())
}

fn project_parent(config: &crate::Config) -> String {
    let tenant = if config.identity.tenant_id().starts_with("tenants/") {
        config.identity.tenant_id().to_owned()
    } else {
        format!("tenants/{}", config.identity.tenant_id())
    };
    let project = config.identity.project_id();
    if project.starts_with("tenants/") {
        project.to_owned()
    } else if project.starts_with("projects/") {
        format!("{tenant}/{project}")
    } else {
        format!("{tenant}/projects/{project}")
    }
}

fn validate_listed_operation(core: &ClientCore, operation: &Operation) -> Result<(), Error> {
    let terminal = operation.state == OperationState::Succeeded as i32
        || operation.state == OperationState::Failed as i32
        || operation.state == OperationState::Cancelled as i32;
    if operation.operation_id.is_empty()
        || operation.tenant_id != core.config.identity.tenant_id()
        || operation.project_id != core.config.identity.project_id()
        || operation.state == OperationState::Unspecified as i32
        || operation.done != terminal
    {
        return Err(Error::protocol(
            "ListOperations returned invalid or cross-project durable state",
        ));
    }
    Ok(())
}
