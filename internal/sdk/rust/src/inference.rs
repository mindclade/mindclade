use std::{
    sync::Arc,
    time::{Duration, Instant},
};

use mindclade_protocols::{
    inference::v1::{
        InferenceRequest, InferenceResult, InferenceStreamCursor, InferenceStreamMessage,
        inference_stream_message::Update,
    },
    internal::inference::v1::{
        CommitInferenceResultRequest, GetInferenceRequestRequest, GetInferenceResultRequest,
        SubmitInferenceRequest, WatchInferenceRequest,
    },
    job::v1::Operation,
};
use prost::Message;
use sha2::{Digest, Sha256};
use tonic::codegen::tokio_stream::StreamExt;

use crate::{
    CallOptions, CancellationToken, ClientCore, Error, InferenceStream, SubmitOptions,
    request::{PreparedCall, validate_resource_value},
    retry::registered_method_safety,
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
                registered_method_safety(SUBMIT),
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
                registered_method_safety(GET_REQUEST),
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
                registered_method_safety(GET_RESULT),
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
                registered_method_safety(COMMIT_RESULT),
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
            core: Arc::clone(&self.core),
            operation_name,
            prepared: call.prepare(&self.core.config),
            cursor,
            stream: None,
            cancellation,
            consecutive_failures: 0,
            terminal: false,
        })
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
                    let remaining = watch
                        .prepared
                        .deadline
                        .checked_duration_since(Instant::now())
                        .ok_or_else(Error::deadline_exceeded)?;
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
    core: Arc<ClientCore>,
    operation_name: String,
    prepared: PreparedCall,
    cursor: Option<InferenceStreamCursor>,
    stream: Option<InferenceStream>,
    cancellation: CancellationToken,
    consecutive_failures: u8,
    terminal: bool,
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
            let next = {
                let stream = self
                    .stream
                    .as_mut()
                    .ok_or_else(|| Error::protocol("inference watch stream was not established"))?;
                tokio::select! {
                    biased;
                    () = self.cancellation.cancelled() => return Err(Error::cancelled()),
                    update = stream.next() => update,
                }
            };
            match next {
                None => {
                    self.stream = None;
                    self.retry_or_fail(Error::from_status(&tonic::Status::unavailable(
                        "inference watch ended before terminal truth",
                    )))
                    .await?;
                }
                Some(Err(status)) => {
                    self.stream = None;
                    self.retry_or_fail(Error::from_status(&status)).await?;
                }
                Some(Ok(response)) => {
                    let message = response.message.ok_or_else(|| {
                        Error::protocol("inference watch response omitted its message")
                    })?;
                    self.accept(message.clone())?;
                    self.consecutive_failures = 0;
                    return Ok(Some(message));
                }
            }
        }
    }

    #[must_use]
    pub fn cursor(&self) -> Option<InferenceStreamCursor> {
        self.cursor.clone()
    }

    fn accept(&mut self, message: InferenceStreamMessage) -> Result<(), Error> {
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
            return Ok(());
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
        self.cursor = Some(InferenceStreamCursor {
            request_name: message.request_name,
            after_sequence: message.sequence,
            resume_token: message.resume_token,
        });
        self.terminal = matches!(
            message.update,
            Some(Update::FinalResult(_) | Update::Failure(_))
        );
        Ok(())
    }

    async fn connect(&self) -> Result<InferenceStream, Error> {
        if !matches!(
            registered_method_safety(WATCH),
            crate::retry::CallSafety::Safe
        ) {
            return Err(Error::protocol("inference watch safety policy is missing"));
        }
        let request = WatchInferenceRequest {
            operation_name: self.operation_name.clone(),
            cursor: self.cursor.clone(),
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
            result = tokio::time::timeout(remaining, self.core.transport.watch_inference(request)) => {
                result
                    .map_err(|_| Error::deadline_exceeded())?
                    .map_err(|status| Error::from_status(&status))?
            },
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
