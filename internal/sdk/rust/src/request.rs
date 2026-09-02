use std::{
    collections::{HashSet, VecDeque},
    fmt,
    future::Future,
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use prost_types::Timestamp;

use crate::{Config, Error, config::validate_metadata_value};

static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(1);

const DEFAULT_PAGINATION_MAX_PAGES: usize = 100;
const DEFAULT_PAGINATION_MAX_ITEMS: usize = 10_000;
const HARD_PAGINATION_MAX_PAGES: usize = 1_000;
const HARD_PAGINATION_MAX_ITEMS: usize = 1_000_000;

/// Hard limits for lazy traversal of opaque-token list pages.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PaginationLimits {
    max_pages: usize,
    max_items: usize,
}

impl PaginationLimits {
    /// Builds validated pagination limits.
    ///
    /// # Errors
    ///
    /// Returns an error for zero or unreasonably large limits.
    pub fn new(max_pages: usize, max_items: usize) -> Result<Self, Error> {
        if !(1..=HARD_PAGINATION_MAX_PAGES).contains(&max_pages) {
            return Err(Error::invalid_argument(
                "pagination max pages must be in [1, 1000]",
            ));
        }
        if !(1..=HARD_PAGINATION_MAX_ITEMS).contains(&max_items) {
            return Err(Error::invalid_argument(
                "pagination max items must be in [1, 1000000]",
            ));
        }
        Ok(Self {
            max_pages,
            max_items,
        })
    }
}

impl Default for PaginationLimits {
    fn default() -> Self {
        Self {
            max_pages: DEFAULT_PAGINATION_MAX_PAGES,
            max_items: DEFAULT_PAGINATION_MAX_ITEMS,
        }
    }
}

/// One generated-facade page adapted for [`Paginator`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PaginationPage<T> {
    pub items: Vec<T>,
    pub next_page_token: String,
}

impl<T> PaginationPage<T> {
    #[must_use]
    pub fn new(items: Vec<T>, next_page_token: impl Into<String>) -> Self {
        Self {
            items,
            next_page_token: next_page_token.into(),
        }
    }
}

/// Lazy, bounded automatic pagination over an ergonomic facade list method.
///
/// The fetch closure receives each opaque token without normalization. Use
/// [`Paginator::try_next`] in a loop; it rejects repeated cursors and reports
/// budget exhaustion rather than presenting a partial traversal as complete.
pub struct Paginator<T, Fetch> {
    fetch_page: Fetch,
    token: String,
    seen: HashSet<String>,
    pending: VecDeque<T>,
    limits: PaginationLimits,
    pages: usize,
    items: usize,
    finished: bool,
    failed: bool,
}

/// Creates a lazy paginator. `fetch_page` should call an ergonomic SDK list
/// method so identity, deadlines, retries, and response validation stay active.
pub fn paginate<T, Fetch>(
    fetch_page: Fetch,
    initial_page_token: impl Into<String>,
    limits: PaginationLimits,
) -> Paginator<T, Fetch> {
    let token = initial_page_token.into();
    let seen = if token.is_empty() {
        HashSet::new()
    } else {
        HashSet::from([token.clone()])
    };
    Paginator {
        fetch_page,
        token,
        seen,
        pending: VecDeque::new(),
        limits,
        pages: 0,
        items: 0,
        finished: false,
        failed: false,
    }
}

impl<T, Fetch> Paginator<T, Fetch> {
    /// Returns the next item, fetching pages only as needed.
    ///
    /// # Errors
    ///
    /// Returns the facade fetch error, a protocol error for a repeated token,
    /// or a non-retryable resource-exhausted error when a limit is reached.
    pub async fn try_next<FetchFuture>(&mut self) -> Result<Option<T>, Error>
    where
        Fetch: FnMut(String) -> FetchFuture,
        FetchFuture: Future<Output = Result<PaginationPage<T>, Error>>,
    {
        loop {
            if self.failed {
                return Ok(None);
            }
            if let Some(item) = self.pending.pop_front() {
                if self.items >= self.limits.max_items {
                    self.failed = true;
                    return Err(Error::pagination_limit(
                        "automatic pagination exceeded its item budget",
                    ));
                }
                self.items += 1;
                return Ok(Some(item));
            }
            if self.finished {
                return Ok(None);
            }
            if self.items >= self.limits.max_items {
                self.failed = true;
                return Err(Error::pagination_limit(
                    "automatic pagination exceeded its item budget",
                ));
            }
            if self.pages >= self.limits.max_pages {
                self.failed = true;
                return Err(Error::pagination_limit(
                    "automatic pagination exceeded its page budget",
                ));
            }
            let page = match (self.fetch_page)(self.token.clone()).await {
                Ok(page) => page,
                Err(error) => {
                    self.failed = true;
                    return Err(error);
                }
            };
            self.pages += 1;
            if !page.next_page_token.is_empty() && !self.seen.insert(page.next_page_token.clone()) {
                self.failed = true;
                return Err(Error::protocol(
                    "list response repeated an opaque page token",
                ));
            }
            self.finished = page.next_page_token.is_empty();
            self.token = page.next_page_token;
            self.pending = page.items.into();
        }
    }
}

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

    pub(crate) fn with_sensitive_lease_token(mut self, value: SensitiveLeaseToken) -> Self {
        self.lease_token = Some(value);
        self
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
    pub(crate) fn new(value: String) -> Result<Self, Error> {
        if value.len() < 32
            || value.len() > 4096
            || !value.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
        {
            return Err(Error::protocol(
                "lease credential metadata must contain 32 through 4096 visible ASCII characters",
            ));
        }
        Ok(Self(value))
    }

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
