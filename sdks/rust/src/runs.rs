use std::{
    fmt,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::{
    internal::job::v1::{
        AcquireAttemptLeaseRequest, CancelAttemptRequest, CancelAttemptResponse,
        CommitAttemptRequest, CommitAttemptResponse, GetAttemptRequest, GetRunRequest,
        HeartbeatAttemptRequest, HeartbeatAttemptResponse, ListAttemptsRequest,
        ListAttemptsResponse, ListRunsRequest, ListRunsResponse, RenewAttemptLeaseRequest,
    },
    job::v1::{Attempt, LeaseFence, Run},
};
use sha2::{Digest, Sha256};

use crate::{
    CallOptions, ClientCore, Error, SubmitOptions,
    jobs::{canonical_resource, protobuf_digest, valid_compact_resource, valid_leaf},
    request::{PreparedCall, SensitiveLeaseToken},
    retry::registered_method_safety,
};

const GET_RUN: &str = "/mindclade.internal.job.v1.RunService/GetRun";
const LIST_RUNS: &str = "/mindclade.internal.job.v1.RunService/ListRuns";
const GET_ATTEMPT: &str = "/mindclade.internal.job.v1.RunService/GetAttempt";
const LIST_ATTEMPTS: &str = "/mindclade.internal.job.v1.RunService/ListAttempts";
const ACQUIRE: &str = "/mindclade.internal.job.v1.RunService/AcquireAttemptLease";
const RENEW: &str = "/mindclade.internal.job.v1.RunService/RenewAttemptLease";
const HEARTBEAT: &str = "/mindclade.internal.job.v1.RunService/HeartbeatAttempt";
const CANCEL: &str = "/mindclade.internal.job.v1.RunService/CancelAttempt";
const COMMIT: &str = "/mindclade.internal.job.v1.RunService/CommitAttempt";
const LEASE_HEADER: &str = "x-mindclade-lease-token";

/// Opaque scheduler-issued capability. Its raw value is never readable,
/// serializable, or representable in a protobuf message.
#[derive(Clone)]
pub struct LeaseCredential {
    token: SensitiveLeaseToken,
}

impl fmt::Debug for LeaseCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LeaseCredential([REDACTED])")
    }
}

impl fmt::Display for LeaseCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LeaseCredential([REDACTED])")
    }
}

/// Clone-safe durable lease snapshot plus its opaque transport capability.
#[derive(Clone)]
pub struct AttemptLease {
    attempt: Attempt,
    fence: LeaseFence,
    credential: LeaseCredential,
}

impl AttemptLease {
    #[must_use]
    pub fn attempt(&self) -> Attempt {
        self.attempt.clone()
    }

    #[must_use]
    pub fn fence(&self) -> LeaseFence {
        self.fence.clone()
    }

    #[must_use]
    pub fn credential(&self) -> LeaseCredential {
        self.credential.clone()
    }
}

impl fmt::Debug for AttemptLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AttemptLease")
            .field("attempt", &self.attempt)
            .field("fence", &self.fence)
            .field("credential", &self.credential)
            .finish()
    }
}

/// Logical-run, attempt, and fenced worker helpers over generated `RunService` types.
#[derive(Clone)]
pub struct Runs {
    core: Arc<ClientCore>,
}

impl Runs {
    pub(crate) fn new(core: Arc<ClientCore>) -> Self {
        Self { core }
    }

    /// Reads one frozen logical execution.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, credentials, transport failure, or
    /// a malformed response.
    pub async fn get_run(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<Run, Error> {
        let name = canonical_resource(&self.core, &name.into(), "runs")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetRunRequest { name: name.clone() },
                &prepared,
                registered_method_safety(GET_RUN),
                None,
                |transport, request| Box::pin(async move { transport.get_run(request).await }),
            )
            .await?
            .into_inner();
        let run = response
            .run
            .ok_or_else(|| Error::protocol("GetRun response omitted its run"))?;
        if run.run_id != name || !valid_run(&self.core, &run) {
            return Err(Error::protocol("GetRun response changed durable identity"));
        }
        Ok(run)
    }

    /// Lists one bounded page of runs beneath a durable job.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination, credentials,
    /// transport failure, or an inconsistent response.
    pub async fn list_runs(
        &self,
        mut request: ListRunsRequest,
        options: CallOptions,
    ) -> Result<ListRunsResponse, Error> {
        request.parent = canonical_resource(&self.core, &request.parent, "jobs")?;
        if request
            .page
            .as_ref()
            .is_some_and(|page| page.page_size > 200)
            || !request.filter.trim().is_empty()
        {
            return Err(Error::invalid_argument(
                "run list page size or filter is invalid",
            ));
        }
        let parent = request.parent.clone();
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(LIST_RUNS),
                None,
                |transport, request| Box::pin(async move { transport.list_runs(request).await }),
            )
            .await?
            .into_inner();
        if response
            .runs
            .iter()
            .any(|run| !valid_run(&self.core, run) || run.job_id != parent)
        {
            return Err(Error::protocol(
                "ListRuns response changed durable identity",
            ));
        }
        Ok(response)
    }

    /// Reads one fenced execution attempt.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, credentials, transport failure, or
    /// an inconsistent response.
    pub async fn get_attempt(
        &self,
        name: impl Into<String>,
        options: CallOptions,
    ) -> Result<Attempt, Error> {
        let name = canonical_resource(&self.core, &name.into(), "attempts")?;
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                GetAttemptRequest { name: name.clone() },
                &prepared,
                registered_method_safety(GET_ATTEMPT),
                None,
                |transport, request| Box::pin(async move { transport.get_attempt(request).await }),
            )
            .await?
            .into_inner();
        let attempt = response
            .attempt
            .ok_or_else(|| Error::protocol("GetAttempt response omitted its attempt"))?;
        if attempt.attempt_id != name || !valid_attempt(&self.core, &attempt) {
            return Err(Error::protocol(
                "GetAttempt response changed durable identity",
            ));
        }
        Ok(attempt)
    }

    /// Lists one bounded page of attempts beneath a run.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope or pagination, credentials,
    /// transport failure, or an inconsistent response.
    pub async fn list_attempts(
        &self,
        mut request: ListAttemptsRequest,
        options: CallOptions,
    ) -> Result<ListAttemptsResponse, Error> {
        request.parent = canonical_resource(&self.core, &request.parent, "runs")?;
        if request
            .page
            .as_ref()
            .is_some_and(|page| page.page_size > 200)
        {
            return Err(Error::invalid_argument("attempt page size exceeds 200"));
        }
        let parent = request.parent.clone();
        let prepared = options.prepare(&self.core.config);
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(LIST_ATTEMPTS),
                None,
                |transport, request| {
                    Box::pin(async move { transport.list_attempts(request).await })
                },
            )
            .await?
            .into_inner();
        if response
            .attempts
            .iter()
            .any(|attempt| !valid_attempt(&self.core, attempt) || attempt.run_id != parent)
        {
            return Err(Error::protocol(
                "ListAttempts response changed durable identity",
            ));
        }
        Ok(response)
    }

    /// Atomically acquires a scheduler lease and captures its secret response
    /// metadata as an opaque capability handle.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid intent, credentials, transport failure,
    /// missing capability metadata, or an inconsistent fence response.
    pub async fn acquire(
        &self,
        mut request: AcquireAttemptLeaseRequest,
        options: SubmitOptions,
    ) -> Result<AttemptLease, Error> {
        request.run_name = canonical_resource(&self.core, &request.run_name, "runs")?;
        if !valid_leaf(&request.attempt_id) || !valid_duration(request.lease_duration.as_ref()) {
            return Err(Error::invalid_argument(
                "lease acquisition requires a valid attempt ID and duration from five seconds through fifteen minutes",
            ));
        }
        request.context = None;
        let prepared = options.call.prepare(&self.core.config);
        let digest = protobuf_digest(&request);
        let mut context = prepared.command_context(&self.core.config, &options)?;
        context.canonical_request_digest = digest;
        request.context = Some(context);
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(ACQUIRE),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.acquire_attempt_lease(request).await })
                },
            )
            .await?;
        let token = response_lease_token(response.metadata())?;
        let credential = LeaseCredential {
            token: SensitiveLeaseToken::new(token)?,
        };
        let response = response.into_inner();
        let attempt = response
            .attempt
            .ok_or_else(|| Error::protocol("AcquireAttemptLease omitted its attempt"))?;
        let fence = response
            .fence
            .ok_or_else(|| Error::protocol("AcquireAttemptLease omitted its fence"))?;
        validate_lease(&self.core, &attempt, &fence, &credential)?;
        Ok(AttemptLease {
            attempt,
            fence,
            credential,
        })
    }

    /// Renews the current attempt lease under token, epoch, and revision fencing.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid fencing, credentials, transport failure,
    /// or an inconsistent lease response.
    pub async fn renew(
        &self,
        mut request: RenewAttemptLeaseRequest,
        credential: &LeaseCredential,
        options: SubmitOptions,
    ) -> Result<AttemptLease, Error> {
        if request.expected_resource_version < 1 || !valid_duration(request.lease_duration.as_ref())
        {
            return Err(Error::invalid_argument(
                "lease renewal requires a positive revision and bounded duration",
            ));
        }
        normalize_fence(
            &self.core,
            request
                .fence
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("lease renewal requires a fence"))?,
        )?;
        let prepared = prepare_fenced(&self.core, credential, &options)?;
        attach_context(&self.core, &prepared, &options, &mut request)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(RENEW),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.renew_attempt_lease(request).await })
                },
            )
            .await?
            .into_inner();
        let attempt = response
            .attempt
            .ok_or_else(|| Error::protocol("RenewAttemptLease omitted its attempt"))?;
        let fence = response
            .fence
            .ok_or_else(|| Error::protocol("RenewAttemptLease omitted its fence"))?;
        validate_lease(&self.core, &attempt, &fence, credential)?;
        Ok(AttemptLease {
            attempt,
            fence,
            credential: credential.clone(),
        })
    }

    /// Proves liveness and renews the authenticated lease.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid fencing, credentials, transport failure,
    /// or an inconsistent server-clock response.
    pub async fn heartbeat(
        &self,
        mut request: HeartbeatAttemptRequest,
        credential: &LeaseCredential,
        options: SubmitOptions,
    ) -> Result<HeartbeatAttemptResponse, Error> {
        if request.expected_resource_version < 1 || !valid_duration(request.lease_duration.as_ref())
        {
            return Err(Error::invalid_argument(
                "heartbeat requires a positive revision and bounded duration",
            ));
        }
        normalize_fence(
            &self.core,
            request
                .fence
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("heartbeat requires a fence"))?,
        )?;
        let prepared = prepare_fenced(&self.core, credential, &options)?;
        attach_context(&self.core, &prepared, &options, &mut request)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(HEARTBEAT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.heartbeat_attempt(request).await })
                },
            )
            .await?
            .into_inner();
        let attempt = response
            .attempt
            .as_ref()
            .ok_or_else(|| Error::protocol("HeartbeatAttempt omitted its attempt"))?;
        let fence = response
            .fence
            .as_ref()
            .ok_or_else(|| Error::protocol("HeartbeatAttempt omitted its fence"))?;
        if response.observed_at.is_none() {
            return Err(Error::protocol(
                "HeartbeatAttempt omitted server observation time",
            ));
        }
        validate_lease(&self.core, attempt, fence, credential)?;
        Ok(response)
    }

    /// Cancels the current attempt through its opaque lease capability.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid fencing or intent, credentials, transport
    /// failure, or an inconsistent response.
    pub async fn cancel_attempt(
        &self,
        mut request: CancelAttemptRequest,
        credential: &LeaseCredential,
        options: SubmitOptions,
    ) -> Result<CancelAttemptResponse, Error> {
        if request.expected_resource_version < 1
            || request.reason.len() > 1024
            || request.reason.contains('\0')
        {
            return Err(Error::invalid_argument(
                "attempt cancellation requires a positive revision and bounded reason",
            ));
        }
        normalize_fence(
            &self.core,
            request
                .fence
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("attempt cancellation requires a fence"))?,
        )?;
        let prepared = prepare_fenced(&self.core, credential, &options)?;
        attach_context(&self.core, &prepared, &options, &mut request)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(CANCEL),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.cancel_attempt(request).await })
                },
            )
            .await?
            .into_inner();
        validate_attempt_run_response(
            &self.core,
            response.attempt.as_ref(),
            response.run.as_ref(),
            "CancelAttempt",
        )?;
        Ok(response)
    }

    /// Commits a bounded terminal attempt update under lease and revision fencing.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid fencing, update mask, or state, credentials,
    /// transport failure, or an inconsistent response.
    pub async fn commit_attempt(
        &self,
        mut request: CommitAttemptRequest,
        credential: &LeaseCredential,
        options: SubmitOptions,
    ) -> Result<CommitAttemptResponse, Error> {
        if request.expected_resource_version < 1 {
            return Err(Error::invalid_argument(
                "attempt commit requires a positive resource revision",
            ));
        }
        normalize_fence(
            &self.core,
            request
                .fence
                .as_mut()
                .ok_or_else(|| Error::invalid_argument("attempt commit requires a fence"))?,
        )?;
        let fence = request
            .fence
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("attempt commit requires a fence"))?;
        let attempt = request
            .attempt
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("attempt commit requires an attempt"))?;
        let mask = request
            .update_mask
            .as_ref()
            .ok_or_else(|| Error::invalid_argument("attempt commit requires an update mask"))?;
        if !valid_attempt(&self.core, attempt)
            || !valid_mask(&mask.paths)
            || attempt.attempt_id != fence.attempt_id
            || attempt.run_id != fence.run_id
            || attempt.job_id != fence.job_id
            || attempt.lease_epoch != fence.lease_epoch
        {
            return Err(Error::invalid_argument(
                "attempt commit does not match its current fence or update mask",
            ));
        }
        let prepared = prepare_fenced(&self.core, credential, &options)?;
        attach_context(&self.core, &prepared, &options, &mut request)?;
        let key = options.idempotency_key.clone();
        let response = self
            .core
            .unary(
                request,
                &prepared,
                registered_method_safety(COMMIT),
                Some(&key),
                |transport, request| {
                    Box::pin(async move { transport.commit_attempt(request).await })
                },
            )
            .await?
            .into_inner();
        validate_attempt_run_response(
            &self.core,
            response.attempt.as_ref(),
            response.run.as_ref(),
            "CommitAttempt",
        )?;
        Ok(response)
    }
}

trait ContextualRequest: prost::Message {
    fn context_mut(&mut self) -> &mut Option<mindclade_protocols::common::v1::CommandContext>;
}

macro_rules! contextual_request {
    ($($request:ty),+ $(,)?) => {
        $(impl ContextualRequest for $request {
            fn context_mut(&mut self) -> &mut Option<mindclade_protocols::common::v1::CommandContext> {
                &mut self.context
            }
        })+
    };
}

contextual_request!(
    RenewAttemptLeaseRequest,
    HeartbeatAttemptRequest,
    CancelAttemptRequest,
    CommitAttemptRequest,
);

fn attach_context<T: ContextualRequest>(
    core: &ClientCore,
    prepared: &PreparedCall,
    options: &SubmitOptions,
    request: &mut T,
) -> Result<(), Error> {
    *request.context_mut() = None;
    let digest = protobuf_digest(request);
    let mut context = prepared.command_context(&core.config, options)?;
    context.canonical_request_digest = digest;
    *request.context_mut() = Some(context);
    Ok(())
}

fn prepare_fenced(
    core: &ClientCore,
    credential: &LeaseCredential,
    options: &SubmitOptions,
) -> Result<PreparedCall, Error> {
    options
        .call
        .clone()
        .with_sensitive_lease_token(credential.token.clone())
        .prepare_fenced(&core.config)
}

fn response_lease_token(metadata: &tonic::metadata::MetadataMap) -> Result<String, Error> {
    let mut values = metadata.get_all(LEASE_HEADER).iter();
    let value = values
        .next()
        .ok_or_else(|| Error::protocol("lease response omitted its credential metadata"))?;
    if values.next().is_some() {
        return Err(Error::protocol(
            "lease response supplied ambiguous credential metadata",
        ));
    }
    value
        .to_str()
        .map(str::to_owned)
        .map_err(|_| Error::protocol("lease response credential metadata was invalid"))
}

fn valid_duration(value: Option<&prost_types::Duration>) -> bool {
    value.is_some_and(|value| {
        (0..1_000_000_000).contains(&value.nanos)
            && (5_000_000_000_i128..=900_000_000_000_i128)
                .contains(&(i128::from(value.seconds) * 1_000_000_000 + i128::from(value.nanos)))
    })
}

fn normalize_fence(core: &ClientCore, fence: &mut LeaseFence) -> Result<(), Error> {
    if !valid_compact_resource(&fence.job_id, "jobs")
        || !valid_compact_resource(&fence.run_id, "runs")
        || !valid_compact_resource(&fence.attempt_id, "attempts")
        || fence.lease_epoch == 0
        || !valid_digest(&fence.lease_token_digest)
        || !timestamp_is_future(fence.deadline.as_ref())
        || (!fence.tenant_id.is_empty() && fence.tenant_id != core.config.identity.tenant_id())
        || (!fence.project_id.is_empty() && fence.project_id != core.config.identity.project_id())
    {
        return Err(Error::invalid_argument(
            "current scoped lease fence is required",
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

fn validate_lease(
    core: &ClientCore,
    attempt: &Attempt,
    fence: &LeaseFence,
    credential: &LeaseCredential,
) -> Result<(), Error> {
    if !valid_attempt(core, attempt)
        || fence.tenant_id != core.config.identity.tenant_id()
        || fence.project_id != core.config.identity.project_id()
        || attempt.job_id != fence.job_id
        || attempt.run_id != fence.run_id
        || attempt.attempt_id != fence.attempt_id
        || attempt.lease_epoch != fence.lease_epoch
        || !timestamp_is_future(fence.deadline.as_ref())
        || !token_matches(credential.token.expose(), &fence.lease_token_digest)
    {
        return Err(Error::protocol(
            "lease response violated durable fence authority",
        ));
    }
    Ok(())
}

fn validate_attempt_run_response(
    core: &ClientCore,
    attempt: Option<&Attempt>,
    run: Option<&Run>,
    method: &str,
) -> Result<(), Error> {
    let attempt =
        attempt.ok_or_else(|| Error::protocol(format!("{method} omitted its attempt")))?;
    let run = run.ok_or_else(|| Error::protocol(format!("{method} omitted its run")))?;
    if !valid_attempt(core, attempt)
        || !valid_run(core, run)
        || attempt.run_id != run.run_id
        || attempt.job_id != run.job_id
    {
        return Err(Error::protocol(format!(
            "{method} response changed durable identity"
        )));
    }
    Ok(())
}

fn valid_run(core: &ClientCore, value: &Run) -> bool {
    value.tenant_id == core.config.identity.tenant_id()
        && value.project_id == core.config.identity.project_id()
        && valid_compact_resource(&value.run_id, "runs")
        && valid_compact_resource(&value.job_id, "jobs")
        && value.resource_version > 0
        && value.state != 0
}

fn valid_attempt(core: &ClientCore, value: &Attempt) -> bool {
    value.tenant_id == core.config.identity.tenant_id()
        && value.project_id == core.config.identity.project_id()
        && valid_compact_resource(&value.attempt_id, "attempts")
        && valid_compact_resource(&value.run_id, "runs")
        && valid_compact_resource(&value.job_id, "jobs")
        && value.lease_epoch > 0
        && value.resource_version > 0
        && value.state != 0
}

fn valid_mask(paths: &[String]) -> bool {
    !paths.is_empty()
        && paths.len() <= 3
        && paths.iter().any(|path| path == "state")
        && paths.iter().enumerate().all(|(index, path)| {
            matches!(path.as_str(), "state" | "outputs" | "error") && !paths[..index].contains(path)
        })
}

fn valid_digest(value: &str) -> bool {
    value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn token_matches(token: &str, expected: &str) -> bool {
    let actual = format!("sha256:{:x}", Sha256::digest(token.as_bytes()));
    constant_time_equal(actual.as_bytes(), expected.as_bytes())
}

fn constant_time_equal(left: &[u8], right: &[u8]) -> bool {
    let mut difference = left.len() ^ right.len();
    let maximum = left.len().max(right.len());
    for index in 0..maximum {
        difference |= usize::from(
            left.get(index).copied().unwrap_or_default()
                ^ right.get(index).copied().unwrap_or_default(),
        );
    }
    difference == 0
}

fn timestamp_is_future(value: Option<&prost_types::Timestamp>) -> bool {
    let Some(value) = value else {
        return false;
    };
    let Ok(seconds) = u64::try_from(value.seconds) else {
        return false;
    };
    let Ok(nanos) = u32::try_from(value.nanos) else {
        return false;
    };
    if nanos >= 1_000_000_000 {
        return false;
    }
    UNIX_EPOCH
        .checked_add(Duration::new(seconds, nanos))
        .is_some_and(|deadline| deadline > SystemTime::now())
}
