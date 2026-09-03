use std::{sync::Arc, time::Duration};

use mindclade_protocols::{
    inference::v1::{
        InferenceRequest, InferenceResult, InferenceStreamCursor, InferenceStreamMessage,
        inference_stream_message::Update,
    },
    internal::inference::v1::{
        CommitInferenceResultRequest, GetInferenceRequestRequest, GetInferenceResultRequest,
        SubmitInferenceRequest, WatchInferenceRequest, WatchInferenceResponse,
    },
    operation::v1::Operation,
};
use prost::Message;
use sha2::{Digest, Sha256};

use crate::{
    CallOptions, CancellationToken, ClientCore, Error, SubmitOptions, WatchNext, WatchOptions,
    WatchStream,
    operations::{NextUpdate, OpenFuture, ResumableWatch, WatchAction, Watcher},
    request::{PreparedCall, validate_resource_value},
    retry::registered_method_policy,
};

const DEFAULT_WAIT_TIMEOUT: Duration = Duration::from_mins(30);
const SUBMIT: &str = "/mindclade.internal.inference.v1.InferenceService/SubmitInference";
const GET_REQUEST: &str = "/mindclade.internal.inference.v1.InferenceService/GetInferenceRequest";
const GET_RESULT: &str = "/mindclade.internal.inference.v1.InferenceService/GetInferenceResult";
const COMMIT_RESULT: &str =
    "/mindclade.internal.inference.v1.InferenceService/CommitInferenceResult";
const WATCH: &str = "/mindclade.internal.inference.v1.InferenceService/WatchInference";

/// Runtime policy for a resumable inference watch or terminal wait.
#[derive(Clone, Debug)]
pub struct InferenceWaitOptions {
    call: CallOptions,
    timeout: Duration,
}

impl InferenceWaitOptions {
    #[must_use]
    pub fn new() -> Self {
        Self {
            call: CallOptions::default(),
            timeout: DEFAULT_WAIT_TIMEOUT,
        }
    }

    #[must_use]
    pub fn with_call_options(mut self, call: CallOptions) -> Self {
        self.call = call;
        self
    }

    /// Sets the total watch deadline, including reconnects and the terminal
    /// result read.
    ///
    /// # Errors
    ///
    /// Returns an error for zero or more than twenty-four hours.
    pub fn with_timeout(mut self, timeout: Duration) -> Result<Self, Error> {
        if timeout.is_zero() || timeout > Duration::from_hours(24) {
            return Err(Error::invalid_argument(
                "inference wait timeout must be positive and at most twenty-four hours",
            ));
        }
        self.timeout = timeout;
        Ok(self)
    }
}

impl Default for InferenceWaitOptions {
    fn default() -> Self {
        Self::new()
    }
}

impl From<InferenceWaitOptions> for WatchOptions {
    fn from(value: InferenceWaitOptions) -> Self {
        Self::new()
            .with_call_options(value.call)
            .with_timeout(value.timeout)
            .unwrap_or_else(|_| Self::new())
    }
}

/// Generated-type-only inference façade.
#[derive(Clone)]
pub struct Inference {
    core: Arc<ClientCore>,
}

impl Inference {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Submits immutable inference intent after replacing untrusted identity
    /// and command context with authenticated SDK values.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid generated intent, credentials, transport
    /// failure, or a response without its durable operation.
    pub async fn submit(
        &self,
        mut inference_request: InferenceRequest,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        validate_required("inference request name", &inference_request.name)?;
        let prepared = options.call.prepare(&self.core.config);
        inference_request.context = None;
        inference_request.tenant_id = self.core.config.identity.tenant_id().to_owned();
        inference_request.project_id = self.core.config.identity.project_id().to_owned();
        let digest = protobuf_digest(&inference_request);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        inference_request.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                SubmitInferenceRequest {
                    inference_request: Some(inference_request),
                },
                &prepared,
                registered_method_policy(SUBMIT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.submit_inference(request).await })
                },
            )
            .await?
            .into_inner();
        let operation = response.operation.ok_or_else(|| {
            Error::protocol("SubmitInference response omitted its durable operation")
        })?;
        validate_required("inference operation", &operation.operation_id)?;
        Ok(operation)
    }

    /// Reads frozen admitted inference intent.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid identity, credentials, transport failure,
    /// or a response without its generated request.
    pub async fn get_request(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<InferenceRequest, Error> {
        let name = name.into();
        validate_required("inference request name", &name)?;
        let prepared = options.prepare(&self.core.config);
        self.core
            .unary(
                GetInferenceRequestRequest { name },
                &prepared,
                registered_method_policy(GET_REQUEST),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_inference_request(request).await })
                },
            )
            .await?
            .into_inner()
            .inference_request
            .ok_or_else(|| Error::protocol("GetInferenceRequest response omitted its request"))
    }

    /// Reads immutable terminal truth and the operation authorizing it.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid identity, credentials, transport failure,
    /// or a response without both generated values.
    pub async fn get_result(
        &self,
        operation_name: impl Into<String>,
        options: CallOptions,
    ) -> Result<(InferenceResult, Operation), Error> {
        let operation_name = operation_name.into();
        validate_required("inference operation name", &operation_name)?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetInferenceResultRequest { operation_name },
                &prepared,
                registered_method_policy(GET_RESULT),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_inference_result(request).await })
                },
            )
            .await?
            .into_inner();
        let result = response
            .result
            .ok_or_else(|| Error::protocol("GetInferenceResult response omitted its result"))?;
        let operation = response
            .operation
            .ok_or_else(|| Error::protocol("GetInferenceResult response omitted its operation"))?;
        Ok((result, operation))
    }

    /// Commits generated terminal truth under the current worker lease fence.
    /// The SDK replaces caller context and computes the canonical command
    /// digest before transport.
    ///
    /// # Errors
    ///
    /// Returns an error for an incomplete command, credentials, a stale fence,
    /// transport failure, or a malformed response.
    pub async fn commit_result(
        &self,
        mut command: CommitInferenceResultRequest,
        options: SubmitOptions,
    ) -> Result<(InferenceResult, Operation), Error> {
        if command.inference_request.is_none()
            || command.fence.is_none()
            || command.result.is_none()
            || command.request_digest.trim().is_empty()
        {
            return Err(Error::invalid_argument(
                "inference request, lease fence, result, and request digest are required",
            ));
        }
        let prepared = options.call.prepare(&self.core.config);
        command.context = None;
        let digest = protobuf_digest(&command);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        command.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                command,
                &prepared,
                registered_method_policy(COMMIT_RESULT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_inference_result(request).await })
                },
            )
            .await?
            .into_inner();
        let result = response
            .result
            .ok_or_else(|| Error::protocol("CommitInferenceResult response omitted its result"))?;
        let operation = response.operation.ok_or_else(|| {
            Error::protocol("CommitInferenceResult response omitted its operation")
        })?;
        Ok((result, operation))
    }

    /// Opens a resumable generated inference stream. Only server-issued
    /// durable cursors are accepted for reconnects.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid operation name, cursor, or wait policy.
    pub fn watch(
        &self,
        operation_name: impl Into<String>,
        cursor: Option<InferenceStreamCursor>,
        options: &InferenceWaitOptions,
        cancellation: CancellationToken,
    ) -> Result<InferenceWatch, Error> {
        let operation_name = operation_name.into();
        validate_required("inference operation name", &operation_name)?;
        if let Some(value) = cursor.as_ref() {
            if value.after_sequence == 0
                || value.request_name.trim().is_empty()
                || value.resume_token.trim().is_empty()
            {
                return Err(Error::invalid_argument(
                    "inference cursor must be a complete server-issued durable cursor",
                ));
            }
            validate_resource_value("inference cursor request name", &value.request_name)?;
            validate_resource_value("inference cursor token", &value.resume_token)?;
        }
        let call = options.call.bounded_by(options.timeout);
        Ok(InferenceWatch {
            inner: Watcher::new(
                Arc::clone(&self.core),
                call.prepare(&self.core.config),
                cancellation,
                InferenceWatchState {
                    operation_name,
                    cursor,
                },
            ),
        })
    }

    /// Resumes a watch from a previously issued durable cursor.
    ///
    /// This is the uniform long-running-operation resume verb: it is exactly
    /// [`Inference::watch`] with the caller's durable cursor made explicit,
    /// and only a complete server-issued cursor is accepted.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid operation name, cursor, or wait policy.
    pub fn resume_watch(
        &self,
        operation_name: impl Into<String>,
        cursor: InferenceStreamCursor,
        options: &InferenceWaitOptions,
        cancellation: CancellationToken,
    ) -> Result<InferenceWatch, Error> {
        self.watch(operation_name, Some(cursor), options, cancellation)
    }

    /// Waits for terminal stream truth and then reads the immutable result.
    ///
    /// # Errors
    ///
    /// Returns an error for cancellation, deadline exhaustion, invalid stream
    /// sequencing, durable failure, transport failure, or malformed terminal
    /// truth.
    pub async fn wait(
        &self,
        operation_name: impl Into<String>,
        cursor: Option<InferenceStreamCursor>,
        options: InferenceWaitOptions,
        cancellation: CancellationToken,
    ) -> Result<(InferenceResult, Operation), Error> {
        let operation_name = operation_name.into();
        let call = options.call.clone().bounded_by(options.timeout);
        let mut watch = self.watch(operation_name.clone(), cursor, &options, cancellation)?;
        while let Some(message) = watch.next().await? {
            match message.update {
                Some(Update::Failure(_)) => {
                    return Err(Error::protocol("inference watch reported durable failure"));
                }
                Some(Update::FinalResult(_)) => {
                    let remaining = watch.remaining()?;
                    return self
                        .get_result(operation_name, call.bounded_by(remaining))
                        .await;
                }
                _ => {}
            }
        }
        Err(Error::protocol(
            "inference watch ended before durable terminal truth",
        ))
    }
}

/// Cancellation-aware resumable wrapper around the generated inference
/// response stream.
pub struct InferenceWatch {
    inner: Watcher<InferenceWatchState>,
}

impl InferenceWatch {
    /// Reads one validated generated stream message, reconnecting only after
    /// the last durable server-issued cursor.
    ///
    /// # Errors
    ///
    /// Returns an error for cancellation, deadline exhaustion, a non-retryable
    /// transport failure, or any cursor/message invariant violation.
    pub async fn next(&mut self) -> Result<Option<InferenceStreamMessage>, Error> {
        let Some(response) = self.inner.next().await? else {
            return Ok(None);
        };
        response
            .message
            .map(Some)
            .ok_or_else(|| Error::protocol("inference watch response omitted its message"))
    }

    /// The last durable server-issued cursor. A reconnect resumes here.
    #[must_use]
    pub fn cursor(&self) -> Option<InferenceStreamCursor> {
        self.inner.cursor()
    }

    /// Consumes the watcher and yields its messages as a `Stream`.
    #[must_use]
    pub fn into_stream(self) -> WatchStream<Self> {
        WatchStream::new(self)
    }

    pub(crate) fn remaining(&self) -> Result<Duration, Error> {
        self.inner.remaining()
    }
}

impl WatchNext for InferenceWatch {
    type Update = InferenceStreamMessage;

    fn next_update(&mut self) -> NextUpdate<'_, Self::Update> {
        Box::pin(self.next())
    }
}

/// Inference-specific watch rules: server-issued durable cursors only,
/// heartbeats pinned to the last cursor, and contiguous data sequences.
struct InferenceWatchState {
    operation_name: String,
    cursor: Option<InferenceStreamCursor>,
}

impl ResumableWatch for InferenceWatchState {
    type Update = WatchInferenceResponse;
    type Cursor = Option<InferenceStreamCursor>;

    fn route(&self) -> &'static str {
        WATCH
    }

    fn label(&self) -> &'static str {
        "inference"
    }

    fn stream_ended_message(&self) -> &'static str {
        "inference watch ended before terminal truth"
    }

    fn cursor(&self) -> Option<InferenceStreamCursor> {
        self.cursor.clone()
    }

    fn open(
        &self,
        core: &Arc<ClientCore>,
        prepared: &PreparedCall,
        attempt: u8,
    ) -> OpenFuture<Self::Update> {
        let core = Arc::clone(core);
        let prepared = prepared.clone();
        let operation_name = self.operation_name.clone();
        let cursor = self.cursor.clone();
        Box::pin(async move {
            let request = WatchInferenceRequest {
                operation_name,
                cursor,
                deadline: Some(prepared.deadline_timestamp()?),
            };
            let request = core
                .request(request, &prepared, None, attempt, WATCH)
                .await?;
            let remaining = prepared.remaining()?;
            let response = tokio::time::timeout(remaining, core.transport.watch_inference(request))
                .await
                .map_err(|_| Error::deadline_exceeded())?
                .map_err(|status| Error::from_status(&status))?;
            Ok(response.into_inner())
        })
    }

    fn accept(
        &mut self,
        response: WatchInferenceResponse,
    ) -> Result<WatchAction<WatchInferenceResponse>, Error> {
        let message = response
            .message
            .as_ref()
            .ok_or_else(|| Error::protocol("inference watch response omitted its message"))?;
        validate_required("inference stream request name", &message.request_name)?;
        validate_required("inference stream resume token", &message.resume_token)?;
        if message.sequence == 0 || message.update.is_none() {
            return Err(Error::protocol(
                "inference watch returned an incomplete message",
            ));
        }
        if matches!(message.update, Some(Update::Heartbeat(_))) {
            let cursor = self.cursor.as_ref().ok_or_else(|| {
                Error::protocol("inference heartbeat preceded durable cursor truth")
            })?;
            if message.request_name != cursor.request_name
                || message.sequence != cursor.after_sequence
                || message.resume_token != cursor.resume_token
            {
                return Err(Error::protocol(
                    "inference heartbeat is not bound to the last durable cursor",
                ));
            }
            // A heartbeat is surfaced to the caller but never advances the
            // durable cursor.
            return Ok(WatchAction::Emit(response));
        }
        let expected = self
            .cursor
            .as_ref()
            .map_or(1, |value| value.after_sequence.saturating_add(1));
        if let Some(cursor) = self.cursor.as_ref()
            && message.request_name != cursor.request_name
        {
            return Err(Error::protocol("inference watch changed request identity"));
        }
        if message.sequence != expected {
            return Err(Error::protocol(
                "inference watch sequence is not contiguous",
            ));
        }
        let terminal = matches!(
            message.update,
            Some(Update::FinalResult(_) | Update::Failure(_))
        );
        self.cursor = Some(InferenceStreamCursor {
            request_name: message.request_name.clone(),
            after_sequence: message.sequence,
            resume_token: message.resume_token.clone(),
        });
        if terminal {
            Ok(WatchAction::Terminal(response))
        } else {
            Ok(WatchAction::Emit(response))
        }
    }
}

fn validate_required(name: &str, value: &str) -> Result<(), Error> {
    if value.trim().is_empty() {
        return Err(Error::invalid_argument(format!("{name} is required")));
    }
    validate_resource_value(name, value)
}

fn protobuf_digest(message: &impl Message) -> String {
    format!("sha256:{:x}", Sha256::digest(message.encode_to_vec()))
}
