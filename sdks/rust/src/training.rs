use std::{
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    common::v1::ResourceRef,
    internal::training::v1::{
        CancelTrainingRunRequest, CommitCheckpointRequest, CommitTrainingProgressRequest,
        CompleteTrainingRunRequest, CreateTrainingRunRequest, CreateTrainingRunResponse,
        GetCheckpointRequest, GetTrainingRunRequest, ListCheckpointsRequest,
        ListCheckpointsResponse, ListTrainingRunsRequest, ListTrainingRunsResponse,
        PrepareCheckpointRequest, ResumeTrainingAttemptRequest, StartTrainingAttemptRequest,
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
use tonic::codegen::tokio_stream::StreamExt;

use crate::{
    CallOptions, CancellationToken, ClientCore, Error, SubmitOptions, TrainingStream,
    request::PreparedCall,
    retry::{CallSafety, registered_method_safety},
    workflows::{command_context, normalize_parent, project_name, valid_sha256, validate_page},
};

const CREATE: &str = "/mindclade.internal.training.v1.TrainingService/CreateTrainingRun";
const GET: &str = "/mindclade.internal.training.v1.TrainingService/GetTrainingRun";
const LIST: &str = "/mindclade.internal.training.v1.TrainingService/ListTrainingRuns";
const START: &str = "/mindclade.internal.training.v1.TrainingService/StartTrainingAttempt";
const RESUME: &str = "/mindclade.internal.training.v1.TrainingService/ResumeTrainingAttempt";
const COMMIT_PROGRESS: &str =
    "/mindclade.internal.training.v1.TrainingService/CommitTrainingProgress";
const PREPARE_CHECKPOINT: &str =
    "/mindclade.internal.training.v1.TrainingService/PrepareCheckpoint";
const COMMIT_CHECKPOINT: &str = "/mindclade.internal.training.v1.TrainingService/CommitCheckpoint";
const COMPLETE: &str = "/mindclade.internal.training.v1.TrainingService/CompleteTrainingRun";
const CANCEL: &str = "/mindclade.internal.training.v1.TrainingService/CancelTrainingRun";
const GET_CHECKPOINT: &str = "/mindclade.internal.training.v1.TrainingService/GetCheckpoint";
const LIST_CHECKPOINTS: &str = "/mindclade.internal.training.v1.TrainingService/ListCheckpoints";
const WATCH: &str = "/mindclade.internal.training.v1.TrainingService/WatchTrainingRun";
const DEFAULT_WATCH_TIMEOUT: Duration = Duration::from_mins(30);

/// Runtime policy for a resumable generated training stream.
#[derive(Clone, Debug)]
pub struct TrainingWatchOptions {
    call: CallOptions,
    timeout: Duration,
}

impl TrainingWatchOptions {
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

    /// Sets the deadline shared by every reconnect.
    ///
    /// # Errors
    ///
    /// Returns an error for zero or more than twenty-four hours.
    pub fn with_timeout(mut self, timeout: Duration) -> Result<Self, Error> {
        if timeout.is_zero() || timeout > Duration::from_hours(24) {
            return Err(Error::invalid_argument(
                "training watch timeout must be positive and at most twenty-four hours",
            ));
        }
        self.timeout = timeout;
        Ok(self)
    }
}

impl Default for TrainingWatchOptions {
    fn default() -> Self {
        Self::new()
    }
}

/// Ergonomic private training lifecycle over authoritative generated clients.
#[derive(Clone)]
pub struct Training {
    core: Arc<ClientCore>,
}

impl Training {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Submits immutable generated scientific intent and returns its operation.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid context, transport failure, or malformed response.
    pub async fn submit(
        &self,
        mut command: CreateTrainingRunCommand,
        options: SubmitOptions,
    ) -> Result<Operation, Error> {
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CreateTrainingRunRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(CREATE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.create_training_run(request).await })
                },
            )
            .await?;
        extract_operation(response.into_inner())
    }

    /// Reads one project-scoped generated training run.
    ///
    /// # Errors
    ///
    /// Returns an error for an out-of-scope name, transport failure, or malformed response.
    pub async fn get(
        &self,
        name: impl Into<String>,
        if_none_match: impl Into<String>,
        options: CallOptions,
    ) -> Result<TrainingRun, Error> {
        let name = training_run_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetTrainingRunRequest {
                    name: name.clone(),
                    if_none_match: if_none_match.into(),
                },
                &prepared,
                registered_method_safety(GET),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_training_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_run(response.training_run, "GetTrainingRun", Some(&name))
    }

    /// Lists one bounded page of generated training runs.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid pagination, transport failure, or an invalid project scope.
    pub async fn list_runs(
        &self,
        mut request: ListTrainingRunsRequest,
        options: CallOptions,
    ) -> Result<ListTrainingRunsResponse, Error> {
        normalize_parent(&self.core, &mut request.parent)?;
        validate_page(request.page.as_ref())?;
        let prepared = options.prepare(&self.core.config);
        Ok(self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(LIST),
                None,
                |transport, request| {
                    Box::pin(async move { transport.list_training_runs(request).await })
                },
            )
            .await?
            .into_inner())
    }

    /// Starts a fresh worker attempt under the current scheduler fence.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid fence, missing lease credential, or transport failure.
    pub async fn start_attempt(
        &self,
        mut command: StartTrainingAttemptCommand,
        options: SubmitOptions,
    ) -> Result<TrainingRun, Error> {
        let name = normalize_run_reference(&self.core, command.training_run.as_mut())?;
        normalize_fence(&self.core, command.fence.as_mut())?;
        future_timestamp(command.deadline.as_ref(), "training attempt deadline")?;
        command.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                StartTrainingAttemptRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(START),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.start_training_attempt(request).await })
                },
            )
            .await?
            .into_inner();
        require_run(response.training_run, "StartTrainingAttempt", Some(&name))
    }

    /// Resumes a worker attempt from a committed generated checkpoint.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid checkpoint or fence, missing credential, or RPC failure.
    pub async fn resume_attempt(
        &self,
        mut command: ResumeTrainingAttemptCommand,
        options: SubmitOptions,
    ) -> Result<TrainingRun, Error> {
        let name = normalize_run_reference(&self.core, command.training_run.as_mut())?;
        normalize_checkpoint_reference(&self.core, command.checkpoint.as_mut())?;
        normalize_fence(&self.core, command.fence.as_mut())?;
        future_timestamp(command.deadline.as_ref(), "training resume deadline")?;
        command.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                ResumeTrainingAttemptRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(RESUME),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.resume_training_attempt(request).await })
                },
            )
            .await?
            .into_inner();
        require_run(response.training_run, "ResumeTrainingAttempt", Some(&name))
    }

    /// Commits one monotonic generated progress snapshot.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid progress, a stale fence, transport failure, or bad response.
    pub async fn commit_progress(
        &self,
        mut command: CommitTrainingProgressCommand,
        options: SubmitOptions,
    ) -> Result<(TrainingProgress, TrainingRun), Error> {
        let name = training_run_name(&self.core, &command.training_run_name)?;
        let progress = command
            .progress
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("training progress is required"))?;
        if progress.training_run_name != name || progress.progress_revision == 0 {
            return Err(Error::invalid_argument(
                "training progress must be monotonic and belong to the target run",
            ));
        }
        normalize_fence(&self.core, command.fence.as_mut())?;
        command.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CommitTrainingProgressRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(COMMIT_PROGRESS),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_training_progress(request).await })
                },
            )
            .await?
            .into_inner();
        let progress = response
            .progress
            .ok_or_else(|| Error::protocol("CommitTrainingProgress omitted progress"))?;
        if progress.training_run_name != name {
            return Err(Error::protocol(
                "CommitTrainingProgress changed progress identity",
            ));
        }
        Ok((
            progress,
            require_run(response.training_run, "CommitTrainingProgress", Some(&name))?,
        ))
    }

    /// Creates an atomic generated checkpoint preparation boundary.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid checkpoint intent, a stale fence, or transport failure.
    pub async fn prepare_checkpoint(
        &self,
        mut command: PrepareCheckpointCommand,
        options: SubmitOptions,
    ) -> Result<Checkpoint, Error> {
        let name = training_run_name(&self.core, &command.training_run_name)?;
        if command.snapshot_epoch == 0
            || command.logical_state_descriptor.is_none()
            || command.committed_progress.is_none()
        {
            return Err(Error::invalid_argument(
                "checkpoint preparation requires epoch, state descriptor, and progress",
            ));
        }
        normalize_fence(&self.core, command.fence.as_mut())?;
        command.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let epoch = command.snapshot_epoch;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                PrepareCheckpointRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(PREPARE_CHECKPOINT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.prepare_checkpoint(request).await })
                },
            )
            .await?
            .into_inner();
        require_checkpoint(response.checkpoint, "PrepareCheckpoint", &name, epoch)
    }

    /// Publishes an immutable verified generated checkpoint.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid checkpoint evidence, a stale fence, or transport failure.
    pub async fn commit_checkpoint(
        &self,
        mut command: CommitCheckpointCommand,
        options: SubmitOptions,
    ) -> Result<(Checkpoint, TrainingRun), Error> {
        let name = training_run_name(&self.core, &command.training_run_name)?;
        if command.snapshot_epoch == 0
            || command.checkpoint_manifest.is_none()
            || command.logical_state_descriptor.is_none()
            || command.committed_progress.is_none()
            || command.verification_evidence.is_none()
            || command.committed_at.is_none()
        {
            return Err(Error::invalid_argument(
                "checkpoint commit requires manifests, evidence, progress, epoch, and time",
            ));
        }
        normalize_fence(&self.core, command.fence.as_mut())?;
        command.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let epoch = command.snapshot_epoch;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CommitCheckpointRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(COMMIT_CHECKPOINT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_checkpoint(request).await })
                },
            )
            .await?
            .into_inner();
        Ok((
            require_checkpoint(response.checkpoint, "CommitCheckpoint", &name, epoch)?,
            require_run(response.training_run, "CommitCheckpoint", Some(&name))?,
        ))
    }

    /// Commits one fenced terminal generated result.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid terminal state, a stale fence, or transport failure.
    pub async fn complete(
        &self,
        mut command: CompleteTrainingRunCommand,
        options: SubmitOptions,
    ) -> Result<TrainingRun, Error> {
        let name = training_run_name(&self.core, &command.training_run_name)?;
        if TrainingTerminalClassification::try_from(command.classification)
            .ok()
            .is_none_or(|value| value == TrainingTerminalClassification::Unspecified)
            || command.completed_at.is_none()
        {
            return Err(Error::invalid_argument(
                "training completion requires terminal classification and completion time",
            ));
        }
        normalize_fence(&self.core, command.fence.as_mut())?;
        command.context = None;
        let prepared = options.call.prepare_fenced(&self.core.config)?;
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CompleteTrainingRunRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(COMPLETE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.complete_training_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_run(response.training_run, "CompleteTrainingRun", Some(&name))
    }

    /// Records generated cancellation intent under optimistic concurrency.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid cancellation intent, transport failure, or bad response.
    pub async fn cancel(
        &self,
        mut command: CancelTrainingRunCommand,
        options: SubmitOptions,
    ) -> Result<TrainingRun, Error> {
        let name = training_run_name(&self.core, &command.training_run_name)?;
        if command.etag.trim().is_empty()
            || command.reason.trim().is_empty()
            || command.reason.len() > 1024
        {
            return Err(Error::invalid_argument(
                "training cancellation requires an ETag and bounded reason",
            ));
        }
        command.context = None;
        let prepared = options.call.prepare(&self.core.config);
        command.context = Some(command_context(&self.core, &prepared, &options, &command)?);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                CancelTrainingRunRequest {
                    command: Some(command),
                },
                &prepared,
                registered_method_safety(CANCEL),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.cancel_training_run(request).await })
                },
            )
            .await?
            .into_inner();
        require_run(response.training_run, "CancelTrainingRun", Some(&name))
    }

    /// Reads one immutable generated checkpoint.
    ///
    /// # Errors
    ///
    /// Returns an error for an out-of-scope name, transport failure, or malformed response.
    pub async fn get_checkpoint(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<Checkpoint, Error> {
        let name = checkpoint_name(&self.core, &name.into())?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetCheckpointRequest { name },
                &prepared,
                registered_method_safety(GET_CHECKPOINT),
                None,
                |transport, request| {
                    Box::pin(async move { transport.get_checkpoint(request).await })
                },
            )
            .await?
            .into_inner();
        response
            .checkpoint
            .ok_or_else(|| Error::protocol("GetCheckpoint response omitted its checkpoint"))
    }

    /// Lists one bounded page of checkpoints beneath a generated training run.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid pagination or parent scope, or for transport failure.
    pub async fn list_checkpoints(
        &self,
        mut request: ListCheckpointsRequest,
        options: CallOptions,
    ) -> Result<ListCheckpointsResponse, Error> {
        request.parent = training_run_name(&self.core, &request.parent)?;
        validate_page(request.page.as_ref())?;
        let prepared = options.prepare(&self.core.config);
        Ok(self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(LIST_CHECKPOINTS),
                None,
                |transport, request| {
                    Box::pin(async move { transport.list_checkpoints(request).await })
                },
            )
            .await?
            .into_inner())
    }

    /// Opens a cancellation-aware, reconnecting generated update stream.
    ///
    /// # Errors
    ///
    /// Returns an error when the run name is outside the configured project.
    pub fn watch(
        &self,
        name: impl Into<String>,
        after_sequence: u64,
        options: &TrainingWatchOptions,
        cancellation: CancellationToken,
    ) -> Result<TrainingWatch, Error> {
        let name = training_run_name(&self.core, &name.into())?;
        let call = options.call.bounded_by(options.timeout);
        Ok(TrainingWatch {
            core: Arc::clone(&self.core),
            name,
            prepared: call.prepare(&self.core.config),
            stream: None,
            cancellation,
            last_sequence: after_sequence,
            consecutive_failures: 0,
            terminal: false,
        })
    }
}

/// Strictly ordered generated training updates with transparent reconnect.
pub struct TrainingWatch {
    core: Arc<ClientCore>,
    name: String,
    prepared: PreparedCall,
    stream: Option<TrainingStream>,
    cancellation: CancellationToken,
    last_sequence: u64,
    consecutive_failures: u8,
    terminal: bool,
}

impl TrainingWatch {
    /// Returns the next contiguous generated update, or `None` after terminal state.
    ///
    /// # Errors
    ///
    /// Returns an error for cancellation, timeout, non-contiguous updates, or transport failure.
    pub async fn next(&mut self) -> Result<Option<WatchTrainingRunResponse>, Error> {
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
                .ok_or_else(|| Error::protocol("training watch stream was not established"))?;
            let update = tokio::select! {
                biased;
                () = self.cancellation.cancelled() => return Err(Error::cancelled()),
                update = stream.next() => update,
            };
            match update {
                None => {
                    self.stream = None;
                    self.retry_or_fail(Error::from_status(&tonic::Status::unavailable(
                        "training watch ended before terminal state",
                    )))
                    .await?;
                }
                Some(Err(status)) => {
                    self.stream = None;
                    self.retry_or_fail(Error::from_status(&status)).await?;
                }
                Some(Ok(response)) => {
                    let run = response.training_run.as_ref().ok_or_else(|| {
                        Error::protocol("training watch response omitted its run")
                    })?;
                    if run.name != self.name {
                        return Err(Error::protocol("training watch returned a different run"));
                    }
                    if response.sequence <= self.last_sequence {
                        continue;
                    }
                    if response.sequence != self.last_sequence.saturating_add(1) {
                        return Err(Error::protocol(
                            "training watch returned a non-contiguous sequence",
                        ));
                    }
                    self.last_sequence = response.sequence;
                    self.consecutive_failures = 0;
                    self.terminal = terminal(run.state);
                    return Ok(Some(response));
                }
            }
        }
    }

    #[must_use]
    pub fn last_sequence(&self) -> u64 {
        self.last_sequence
    }

    async fn connect(&self) -> Result<TrainingStream, Error> {
        if !matches!(registered_method_safety(WATCH), CallSafety::Safe) {
            return Err(Error::protocol("training watch safety policy is missing"));
        }
        let request = WatchTrainingRunRequest {
            name: self.name.clone(),
            after_sequence: self.last_sequence,
            deadline: Some(self.prepared.deadline_timestamp()?),
        };
        let request = tokio::select! {
            biased;
            () = self.cancellation.cancelled() => return Err(Error::cancelled()),
            result = self.core.request(request, &self.prepared, None) => result?,
        };
        let remaining = self
            .prepared
            .deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(Error::deadline_exceeded)?;
        let response = tokio::select! {
            biased;
            () = self.cancellation.cancelled() => return Err(Error::cancelled()),
            result = tokio::time::timeout(remaining, self.core.transport.watch_training_run(request)) =>
                result.map_err(|_| Error::deadline_exceeded())?.map_err(|status| Error::from_status(&status))?,
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
        let delay = error
            .retry_after()
            .unwrap_or_else(|| self.core.backoff(self.consecutive_failures));
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

fn extract_operation(response: CreateTrainingRunResponse) -> Result<Operation, Error> {
    let operation = response
        .operation
        .ok_or_else(|| Error::protocol("CreateTrainingRun response omitted its operation"))?;
    if operation.operation_id.trim().is_empty() {
        return Err(Error::protocol(
            "CreateTrainingRun response operation has no identity",
        ));
    }
    Ok(operation)
}

fn training_run_name(core: &ClientCore, name: &str) -> Result<String, Error> {
    scoped_name(core, name, "trainingRuns")
}

fn checkpoint_name(core: &ClientCore, name: &str) -> Result<String, Error> {
    let prefix = format!("{}/trainingRuns/", project_name(core));
    let suffix = name
        .strip_prefix(&prefix)
        .ok_or_else(|| Error::invalid_argument("checkpoint is outside configured project"))?;
    let components = suffix.split('/').collect::<Vec<_>>();
    if components.len() != 3
        || !valid_id(components[0])
        || components[1] != "checkpoints"
        || !valid_id(components[2])
    {
        return Err(Error::invalid_argument(
            "checkpoint resource name is invalid",
        ));
    }
    Ok(name.to_owned())
}

fn scoped_name(core: &ClientCore, name: &str, collection: &str) -> Result<String, Error> {
    let prefix = format!("{}/{collection}/", project_name(core));
    let id = name.strip_prefix(&prefix).ok_or_else(|| {
        Error::invalid_argument("training resource is outside configured project")
    })?;
    if !valid_id(id) {
        return Err(Error::invalid_argument("training resource name is invalid"));
    }
    Ok(name.to_owned())
}

fn valid_id(value: &str) -> bool {
    let mut bytes = value.bytes();
    bytes
        .next()
        .is_some_and(|byte| byte.is_ascii_alphanumeric())
        && value.len() <= 128
        && bytes
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~'))
}

fn normalize_run_reference(
    core: &ClientCore,
    value: Option<&mut ResourceRef>,
) -> Result<String, Error> {
    let value =
        value.ok_or_else(|| Error::invalid_argument("training run reference is required"))?;
    normalize_reference(core, value, "training_run", false)
}

fn normalize_checkpoint_reference(
    core: &ClientCore,
    value: Option<&mut ResourceRef>,
) -> Result<String, Error> {
    let value = value.ok_or_else(|| Error::invalid_argument("checkpoint reference is required"))?;
    normalize_reference(core, value, "checkpoint", true)
}

fn normalize_reference(
    core: &ClientCore,
    value: &mut ResourceRef,
    expected_type: &str,
    checkpoint: bool,
) -> Result<String, Error> {
    let name = if checkpoint {
        checkpoint_name(core, &value.name)?
    } else {
        training_run_name(core, &value.name)?
    };
    let id = name.rsplit('/').next().unwrap_or_default();
    if (!value.resource_id.is_empty() && value.resource_id != id)
        || (!value.resource_type.is_empty() && value.resource_type != expected_type)
        || !scope_matches(
            core.config.identity.tenant_id(),
            &value.tenant_id,
            "tenants",
        )
        || !scope_matches(
            core.config.identity.project_id(),
            &value.project_id,
            "projects",
        )
    {
        return Err(Error::invalid_argument(
            "training resource reference conflicts with client identity",
        ));
    }
    id.clone_into(&mut value.resource_id);
    expected_type.clone_into(&mut value.resource_type);
    core.config
        .identity
        .tenant_id()
        .clone_into(&mut value.tenant_id);
    core.config
        .identity
        .project_id()
        .clone_into(&mut value.project_id);
    Ok(name)
}

fn normalize_fence(core: &ClientCore, value: Option<&mut LeaseFence>) -> Result<(), Error> {
    let fence = value.ok_or_else(|| Error::invalid_argument("training fence is required"))?;
    if fence.job_id.trim().is_empty()
        || fence.run_id.trim().is_empty()
        || fence.attempt_id.trim().is_empty()
        || fence.lease_epoch == 0
        || !valid_sha256(&fence.lease_token_digest)
        || !scope_matches(
            core.config.identity.tenant_id(),
            &fence.tenant_id,
            "tenants",
        )
        || !scope_matches(
            core.config.identity.project_id(),
            &fence.project_id,
            "projects",
        )
    {
        return Err(Error::invalid_argument(
            "training fence is incomplete or outside configured scope",
        ));
    }
    future_timestamp(fence.deadline.as_ref(), "training fence deadline")?;
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

fn scope_matches(configured: &str, value: &str, collection: &str) -> bool {
    if value.is_empty() || value == configured {
        return true;
    }
    let prefix = format!("{collection}/");
    let configured = configured.strip_prefix(&prefix).unwrap_or(configured);
    let value = value.strip_prefix(&prefix).unwrap_or(value);
    value == configured
}

fn future_timestamp(value: Option<&prost_types::Timestamp>, label: &str) -> Result<(), Error> {
    let value = value.ok_or_else(|| Error::invalid_argument(format!("{label} is required")))?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::invalid_argument("system clock precedes Unix epoch"))?;
    let seconds = u64::try_from(value.seconds)
        .map_err(|_| Error::invalid_argument(format!("{label} is invalid")))?;
    let nanos = u32::try_from(value.nanos)
        .map_err(|_| Error::invalid_argument(format!("{label} is invalid")))?;
    if nanos >= 1_000_000_000
        || seconds < now.as_secs()
        || (seconds == now.as_secs() && nanos <= now.subsec_nanos())
    {
        return Err(Error::invalid_argument(format!(
            "{label} must be in the future"
        )));
    }
    Ok(())
}

fn require_run(
    value: Option<TrainingRun>,
    method: &str,
    expected_name: Option<&str>,
) -> Result<TrainingRun, Error> {
    let value = value
        .ok_or_else(|| Error::protocol(format!("{method} response omitted its training run")))?;
    if value.name.trim().is_empty() || expected_name.is_some_and(|name| name != value.name) {
        return Err(Error::protocol(format!(
            "{method} response changed training run identity"
        )));
    }
    Ok(value)
}

fn require_checkpoint(
    value: Option<Checkpoint>,
    method: &str,
    run_name: &str,
    epoch: u64,
) -> Result<Checkpoint, Error> {
    let value = value
        .ok_or_else(|| Error::protocol(format!("{method} response omitted its checkpoint")))?;
    if value.name.trim().is_empty()
        || value.training_run_name != run_name
        || value.snapshot_epoch != epoch
    {
        return Err(Error::protocol(format!(
            "{method} response changed checkpoint identity"
        )));
    }
    Ok(value)
}

fn terminal(state: i32) -> bool {
    matches!(
        TrainingRunState::try_from(state).ok(),
        Some(TrainingRunState::Completed | TrainingRunState::Failed | TrainingRunState::Cancelled)
    )
}
