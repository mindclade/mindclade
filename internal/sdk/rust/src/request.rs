use std::{
    fmt,
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use prost_types::Timestamp;

use crate::{Config, Error, config::validate_metadata_value};

static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(1);

/// Per-RPC behavior and correlation metadata. It does not redefine the wire
/// request.
#[derive(Clone, Debug, Default)]
pub struct CallOptions {
    request_id: Option<String>,
    trace_id: Option<String>,
    timeout: Option<Duration>,
    lease_token: Option<SensitiveLeaseToken>,
}

impl CallOptions {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets a caller-provided request identifier.
    ///
    /// # Errors
    ///
    /// Returns an error if the value is unsafe for gRPC metadata.
    pub fn with_request_id(mut self, value: impl Into<String>) -> Result<Self, Error> {
        let value = value.into();
        validate_metadata_value("request ID", &value, true)?;
        self.request_id = Some(value);
        Ok(self)
    }

    /// Sets the distributed trace identifier.
    ///
    /// # Errors
    ///
    /// Returns an error if the value is unsafe for gRPC metadata.
    pub fn with_trace_id(mut self, value: impl Into<String>) -> Result<Self, Error> {
        let value = value.into();
        validate_metadata_value("trace ID", &value, true)?;
        self.trace_id = Some(value);
        Ok(self)
    }

    /// Sets the overall RPC deadline, including retries.
    ///
    /// # Errors
    ///
    /// Returns an error for a zero or unbounded duration.
    pub fn with_timeout(mut self, value: Duration) -> Result<Self, Error> {
        if value.is_zero() || value > Duration::from_hours(24) {
            return Err(Error::invalid_argument(
                "call timeout must be positive and at most twenty-four hours",
            ));
        }
        self.timeout = Some(value);
        Ok(self)
    }

    /// Selects the raw scheduler-issued lease credential for a fenced worker
    /// command. Ordinary RPCs deliberately ignore this field; only a fenced
    /// facade can activate it through `prepare_fenced`.
    ///
    /// # Errors
    ///
    /// Returns an error unless the token is non-empty, bounded visible ASCII
    /// without whitespace or control characters.
    pub fn with_lease_token(mut self, value: impl Into<String>) -> Result<Self, Error> {
        let value = value.into();
        if value.is_empty()
            || value.len() > 4096
            || !value.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
        {
            return Err(Error::invalid_argument(
                "lease token must contain at most 4096 visible non-whitespace ASCII characters",
            ));
        }
        self.lease_token = Some(SensitiveLeaseToken(value));
        Ok(self)
    }

    pub(crate) fn prepare(&self, config: &Config) -> PreparedCall {
        let request_id = self.request_id.clone().unwrap_or_else(generate_request_id);
        let trace_id = self.trace_id.clone().unwrap_or_else(|| request_id.clone());
        let timeout = self.timeout.unwrap_or(config.rpc_timeout);
        PreparedCall {
            request_id,
            trace_id,
            deadline: Instant::now() + timeout,
            wall_deadline: SystemTime::now() + timeout,
            lease_token: None,
        }
    }

    pub(crate) fn prepare_fenced(&self, config: &Config) -> Result<PreparedCall, Error> {
        let mut prepared = self.prepare(config);
        prepared.lease_token = Some(
            self.lease_token
                .clone()
                .ok_or_else(|| Error::invalid_argument("fenced command requires a lease token"))?,
        );
        Ok(prepared)
    }

    pub(crate) fn bounded_by(&self, timeout: Duration) -> Self {
        let mut value = self.clone();
        value.timeout = Some(
            value
                .timeout
                .map_or(timeout, |existing| existing.min(timeout)),
        );
        value
    }
}

/// Behavior required for an idempotent training submission. The scientific
/// payload remains [`mindclade_protocols::training::v1::CreateTrainingRunCommand`].
#[derive(Clone, Debug)]
pub struct SubmitOptions {
    pub(crate) call: CallOptions,
    pub(crate) idempotency_key: String,
    pub(crate) correlation_id: String,
    pub(crate) causation_id: String,
    pub(crate) cancellation_token_id: String,
}

impl SubmitOptions {
    /// Creates validated behavior for an idempotent command.
    ///
    /// # Errors
    ///
    /// Returns an error when the key is empty or unsafe for transport
    /// metadata. The control plane computes the canonical command digest and
    /// materializes it before persistence; callers never reproduce
    /// language-specific protobuf serialization.
    pub fn new(idempotency_key: impl Into<String>) -> Result<Self, Error> {
        let idempotency_key = idempotency_key.into();
        validate_metadata_value("idempotency key", &idempotency_key, true)?;
        Ok(Self {
            call: CallOptions::default(),
            idempotency_key,
            correlation_id: String::new(),
            causation_id: String::new(),
            cancellation_token_id: String::new(),
        })
    }

    #[must_use]
    pub fn with_call_options(mut self, options: CallOptions) -> Self {
        self.call = options;
        self
    }

    /// Adds a correlation identifier.
    ///
    /// # Errors
    ///
    /// Returns an error if the identifier is unsafe for command context.
    pub fn with_correlation_id(mut self, value: impl Into<String>) -> Result<Self, Error> {
        self.correlation_id = checked_optional("correlation ID", value.into())?;
        Ok(self)
    }

    /// Adds a causation identifier.
    ///
    /// # Errors
    ///
    /// Returns an error if the identifier is unsafe for command context.
    pub fn with_causation_id(mut self, value: impl Into<String>) -> Result<Self, Error> {
        self.causation_id = checked_optional("causation ID", value.into())?;
        Ok(self)
    }

    /// Adds the durable cancellation-token identifier.
    ///
    /// # Errors
    ///
    /// Returns an error if the identifier is unsafe for command context.
    pub fn with_cancellation_token_id(mut self, value: impl Into<String>) -> Result<Self, Error> {
        self.cancellation_token_id = checked_optional("cancellation token ID", value.into())?;
        Ok(self)
    }
}

fn checked_optional(name: &str, value: String) -> Result<String, Error> {
    if !value.is_empty() {
        validate_metadata_value(name, &value, true)?;
    }
    Ok(value)
}

#[derive(Clone, Debug)]
pub(crate) struct PreparedCall {
    pub(crate) request_id: String,
    pub(crate) trace_id: String,
    pub(crate) deadline: Instant,
    pub(crate) wall_deadline: SystemTime,
    pub(crate) lease_token: Option<SensitiveLeaseToken>,
}

#[derive(Clone)]
pub(crate) struct SensitiveLeaseToken(String);

impl SensitiveLeaseToken {
    pub(crate) fn expose(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for SensitiveLeaseToken {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("[REDACTED]")
    }
}

impl PreparedCall {
    pub(crate) fn deadline_timestamp(&self) -> Result<Timestamp, Error> {
        let value = self
            .wall_deadline
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::invalid_argument("call deadline precedes the Unix epoch"))?;
        let seconds = i64::try_from(value.as_secs())
            .map_err(|_| Error::invalid_argument("call deadline exceeds protobuf range"))?;
        let nanos = i32::try_from(value.subsec_nanos())
            .map_err(|_| Error::invalid_argument("call deadline nanos exceed protobuf range"))?;
        Ok(Timestamp { seconds, nanos })
    }

    pub(crate) fn command_context(
        &self,
        config: &Config,
        options: &SubmitOptions,
    ) -> Result<mindclade_protocols::common::v1::CommandContext, Error> {
        Ok(mindclade_protocols::common::v1::CommandContext {
            request_id: self.request_id.clone(),
            idempotency_key: options.idempotency_key.clone(),
            principal_id: config.identity.principal_id().to_owned(),
            trace_id: self.trace_id.clone(),
            deadline: Some(self.deadline_timestamp()?),
            // The server computes this over its received generated message,
            // then persists and emits the authoritative value.
            canonical_request_digest: String::new(),
            tenant_id: config.identity.tenant_id().to_owned(),
            project_id: config.identity.project_id().to_owned(),
            correlation_id: options.correlation_id.clone(),
            causation_id: options.causation_id.clone(),
            cancellation_token_id: options.cancellation_token_id.clone(),
        })
    }
}

pub(crate) fn validate_resource_value(name: &str, value: &str) -> Result<(), Error> {
    validate_metadata_value(name, value, true)
}

pub(crate) fn generate_request_id() -> String {
    let sequence = REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |value| value.as_nanos());
    format!("{:x}-{nanos:x}-{sequence:x}", std::process::id())
}
