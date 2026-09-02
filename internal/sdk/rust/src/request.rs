use std::{
    collections::{BTreeMap, HashSet, VecDeque},
    fmt,
    future::Future,
    pin::Pin,
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use mindclade_protocols::common::v1::{PageRequest, PageResponse};
use prost_types::Timestamp;
use tonic::{Code, metadata::MetadataMap};

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

/// Allowlisted response metadata keys exposed through [`SafeMetadata`].
///
/// Membership is a cross-language invariant: the Go, Python, Rust, and
/// TypeScript internal SDKs expose exactly this set. Nothing credential
/// bearing may ever be added, and [`is_credential_bearing`] is asserted over
/// the list by a unit test so the two can never drift apart.
pub const SAFE_RESPONSE_METADATA: [&str; 8] = [
    "content-type",
    "date",
    "grpc-status",
    "retry-after-ms",
    "x-mindclade-sdk",
    "x-mindclade-should-retry",
    "x-request-id",
    "x-trace-id",
];

/// Metadata keys the SDK refuses to expose, accept, or forward.
///
/// The same predicate gates the response projection in [`SafeMetadata`] and
/// caller-supplied request metadata, so a credential can neither leak out of a
/// response nor be smuggled into a request.
const CREDENTIAL_METADATA_KEYS: [&str; 7] = [
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-goog-api-key",
    "x-mindclade-lease-token",
];

const CREDENTIAL_METADATA_PATTERNS: [&str; 6] = [
    "auth",
    "credential",
    "key",
    "password",
    "secret",
    "token",
];

/// Reports whether a metadata key may carry a credential.
///
/// Exact matches cover the keys this SDK and its gateways actually use;
/// the substring patterns fail closed for anything a caller invents.
#[must_use]
pub fn is_credential_bearing(key: &str) -> bool {
    let key = key.trim().to_ascii_lowercase();
    CREDENTIAL_METADATA_KEYS.contains(&key.as_str())
        || CREDENTIAL_METADATA_PATTERNS
            .iter()
            .any(|pattern| key.contains(pattern))
}

/// Credential-free projection of response metadata.
///
/// Only [`SAFE_RESPONSE_METADATA`] keys are retained, and only when the value
/// is bounded visible ASCII. Header values are never copied wholesale.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct SafeMetadata {
    entries: BTreeMap<String, String>,
}

impl SafeMetadata {
    /// Returns the allowlisted value recorded under `key`, if any.
    #[must_use]
    pub fn get(&self, key: &str) -> Option<&str> {
        self.entries.get(key).map(String::as_str)
    }

    /// Iterates the retained key names in stable order.
    pub fn keys(&self) -> impl Iterator<Item = &str> {
        self.entries.keys().map(String::as_str)
    }

    /// Iterates the retained pairs in stable order.
    pub fn iter(&self) -> impl Iterator<Item = (&str, &str)> {
        self.entries
            .iter()
            .map(|(key, value)| (key.as_str(), value.as_str()))
    }

    /// Reports whether the server sent no allowlisted metadata at all.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Number of retained entries.
    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    fn project(metadata: &MetadataMap) -> Self {
        let mut entries = BTreeMap::new();
        for key in SAFE_RESPONSE_METADATA {
            if is_credential_bearing(key) {
                continue;
            }
            if let Some(value) = bounded_ascii(metadata, key) {
                entries.insert(key.to_owned(), value);
            }
        }
        Self { entries }
    }
}

fn bounded_ascii(metadata: &MetadataMap, key: &str) -> Option<String> {
    let value = metadata.get(key)?.to_str().ok()?;
    if value.is_empty()
        || value.len() > 512
        || !value.bytes().all(|byte| (0x20..=0x7e).contains(&byte))
    {
        None
    } else {
        Some(value.to_owned())
    }
}

/// A successful RPC together with its correlation identity and an
/// allowlisted, credential-free metadata projection.
///
/// This is the SDK's raw-response wrapper: it is what
/// [`crate::Client::send_with_metadata`] returns and what every ergonomic
/// facade unwraps internally.
pub struct Response<T> {
    inner: T,
    status: Code,
    request_id: Option<String>,
    trace_id: Option<String>,
    safe: SafeMetadata,
    raw: MetadataMap,
}

impl<T> Response<T> {
    /// Consumes the wrapper and returns the generated response message.
    #[must_use]
    pub fn into_inner(self) -> T {
        self.inner
    }

    /// Borrows the generated response message.
    #[must_use]
    pub fn get_ref(&self) -> &T {
        &self.inner
    }

    /// The gRPC status of a successful call, always [`Code::Ok`].
    #[must_use]
    pub fn status(&self) -> Code {
        self.status
    }

    /// The server-echoed `x-request-id`, when it was well formed.
    #[must_use]
    pub fn request_id(&self) -> Option<&str> {
        self.request_id.as_deref()
    }

    /// The server-echoed `x-trace-id`, when it was well formed.
    #[must_use]
    pub fn trace_id(&self) -> Option<&str> {
        self.trace_id.as_deref()
    }

    /// The allowlisted, credential-free response metadata.
    #[must_use]
    pub fn safe_metadata(&self) -> &SafeMetadata {
        &self.safe
    }

    /// Applies `transform` to the message, preserving response identity.
    #[must_use]
    pub fn map<U>(self, transform: impl FnOnce(T) -> U) -> Response<U> {
        Response {
            inner: transform(self.inner),
            status: self.status,
            request_id: self.request_id,
            trace_id: self.trace_id,
            safe: self.safe,
            raw: self.raw,
        }
    }

    /// Crate-private access to unfiltered response metadata.
    ///
    /// Exactly one caller needs this: fenced lease acquisition, which reads
    /// the deliberately denylisted `x-mindclade-lease-token` capability and
    /// immediately wraps it in a redacting handle.
    pub(crate) fn raw_metadata(&self) -> &MetadataMap {
        &self.raw
    }

    pub(crate) fn from_tonic(response: tonic::Response<T>) -> Self {
        let safe = SafeMetadata::project(response.metadata());
        let request_id = bounded_ascii(response.metadata(), crate::error::REQUEST_ID_METADATA);
        let trace_id = bounded_ascii(response.metadata(), crate::error::TRACE_ID_METADATA);
        let (metadata, inner, _extensions) = response.into_parts();
        Self {
            inner,
            status: Code::Ok,
            request_id,
            trace_id,
            safe,
            raw: metadata,
        }
    }
}

impl<T: fmt::Debug> fmt::Debug for Response<T> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Response")
            .field("status", &self.status)
            .field("request_id", &self.request_id)
            .field("trace_id", &self.trace_id)
            .field("safe_metadata", &self.safe)
            .field("inner", &self.inner)
            .finish_non_exhaustive()
    }
}

/// Default page size the SDK requests when a caller leaves it unset.
pub const DEFAULT_PAGE_SIZE: u32 = 100;
/// Absolute page-size ceiling. Each facade may impose a stricter cap.
pub const HARD_PAGE_SIZE_CEILING: u32 = 1_000;

/// Builds the outbound page request for one hop of an automatic traversal.
///
/// The caller's opaque cursor is carried verbatim; the page size is filled
/// with the SDK default when unset and clamped to the SDK-wide ceiling. Each
/// facade's own, stricter cap has already rejected an oversized request before
/// this runs.
pub(crate) fn page_request(page: Option<&PageRequest>, page_token: String) -> PageRequest {
    let requested = page.map_or(0, |value| value.page_size);
    let page_size = if requested == 0 {
        DEFAULT_PAGE_SIZE
    } else {
        requested.min(HARD_PAGE_SIZE_CEILING)
    };
    PageRequest {
        page_token,
        page_size,
    }
}

/// Reads the caller's initial opaque cursor without normalizing it.
pub(crate) fn initial_page_token(page: Option<&PageRequest>) -> String {
    page.map_or_else(String::new, |value| value.page_token.clone())
}

/// One list page together with its page-level metadata.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Page<T> {
    items: Vec<T>,
    next_page_token: String,
    request_id: Option<String>,
    read_time: Option<Timestamp>,
}

impl<T> Page<T> {
    pub(crate) fn new(
        items: Vec<T>,
        page: Option<PageResponse>,
        read_time: Option<Timestamp>,
        request_id: Option<String>,
    ) -> Self {
        Self {
            items,
            next_page_token: page.map_or_else(String::new, |value| value.next_page_token),
            request_id,
            read_time,
        }
    }

    /// Borrows this page's items.
    #[must_use]
    pub fn items(&self) -> &[T] {
        &self.items
    }

    /// Consumes the page and returns its items.
    #[must_use]
    pub fn into_items(self) -> Vec<T> {
        self.items
    }

    /// The opaque cursor for the following page, empty when this is the last.
    #[must_use]
    pub fn next_page_token(&self) -> &str {
        &self.next_page_token
    }

    /// Reports whether the server offered another page.
    #[must_use]
    pub fn has_next_page(&self) -> bool {
        !self.next_page_token.is_empty()
    }

    /// The request identifier of the RPC that produced this page.
    #[must_use]
    pub fn request_id(&self) -> Option<&str> {
        self.request_id.as_deref()
    }

    /// The revision-consistent read time the server reported for this page.
    #[must_use]
    pub fn read_time(&self) -> Option<&Timestamp> {
        self.read_time.as_ref()
    }

    /// Number of items on this page.
    #[must_use]
    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Reports whether the server returned an empty page.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
}

type PageFuture<T> = Pin<Box<dyn Future<Output = Result<Page<T>, Error>> + Send + 'static>>;
type PageFetch<T> = Box<dyn FnMut(String) -> PageFuture<T> + Send>;

/// A lazy, bounded cursor over an ergonomic list method.
///
/// It iterates items transparently across pages through
/// [`Pages::try_next`] while keeping page-level access through
/// [`Pages::next_page`]. Opaque cursors are never normalized, a repeated
/// cursor is a protocol failure rather than an infinite loop, and both the
/// page and item budgets fail closed instead of presenting a truncated
/// traversal as complete.
#[must_use = "a page cursor performs no work until it is advanced"]
pub struct Pages<T> {
    fetch: PageFetch<T>,
    token: String,
    seen: HashSet<String>,
    pending: VecDeque<T>,
    pending_next_token: String,
    pending_request_id: Option<String>,
    pending_read_time: Option<Timestamp>,
    limits: PaginationLimits,
    page_hops: usize,
    items: usize,
    finished: bool,
    failed: bool,
}

impl<T> Pages<T> {
    /// Builds a cursor over `fetch`, starting at the caller's opaque token.
    pub(crate) fn new<Fetch, Fut>(fetch: Fetch, initial_page_token: String) -> Self
    where
        Fetch: FnMut(String) -> Fut + Send + 'static,
        Fut: Future<Output = Result<Page<T>, Error>> + Send + 'static,
    {
        let mut fetch = fetch;
        let seen = if initial_page_token.is_empty() {
            HashSet::new()
        } else {
            HashSet::from([initial_page_token.clone()])
        };
        Self {
            fetch: Box::new(move |token| Box::pin(fetch(token))),
            token: initial_page_token,
            seen,
            pending: VecDeque::new(),
            pending_next_token: String::new(),
            pending_request_id: None,
            pending_read_time: None,
            limits: PaginationLimits::default(),
            page_hops: 0,
            items: 0,
            finished: false,
            failed: false,
        }
    }

    /// Replaces the traversal budgets for this cursor.
    pub fn with_limits(mut self, limits: PaginationLimits) -> Self {
        self.limits = limits;
        self
    }

    /// Reports whether another page may still be fetched.
    #[must_use]
    pub fn has_next_page(&self) -> bool {
        !self.finished && !self.failed
    }

    /// Pages fetched so far.
    #[must_use]
    pub fn page_count(&self) -> usize {
        self.page_hops
    }

    /// Items yielded so far.
    #[must_use]
    pub fn item_count(&self) -> usize {
        self.items
    }

    /// Returns the next item, fetching pages only as needed.
    ///
    /// # Errors
    ///
    /// Returns the underlying list failure, a protocol error when the server
    /// repeats an opaque cursor, or a non-retryable resource-exhausted error
    /// when a budget is reached.
    pub async fn try_next(&mut self) -> Result<Option<T>, Error> {
        loop {
            if self.failed {
                return Ok(None);
            }
            if let Some(item) = self.pending.pop_front() {
                if self.items >= self.limits.max_items {
                    return Err(self.exhausted("item"));
                }
                self.items += 1;
                return Ok(Some(item));
            }
            if self.finished {
                return Ok(None);
            }
            if self.items >= self.limits.max_items {
                return Err(self.exhausted("item"));
            }
            let page = self.fetch_page().await?;
            self.pending = page.items.into();
            self.pending_next_token = page.next_page_token;
            self.pending_request_id = page.request_id;
            self.pending_read_time = page.read_time;
        }
    }

    /// Returns the next whole page together with its page-level metadata.
    ///
    /// Items already buffered by [`Pages::try_next`] are returned first, so
    /// the two accessors can be mixed without losing or repeating an item.
    ///
    /// # Errors
    ///
    /// Returns the underlying list failure, a protocol error when the server
    /// repeats an opaque cursor, or a non-retryable resource-exhausted error
    /// when a budget is reached.
    pub async fn next_page(&mut self) -> Result<Option<Page<T>>, Error> {
        if self.failed {
            return Ok(None);
        }
        if !self.pending.is_empty() {
            let items: Vec<T> = std::mem::take(&mut self.pending).into();
            self.charge_items(items.len())?;
            return Ok(Some(Page {
                items,
                next_page_token: std::mem::take(&mut self.pending_next_token),
                request_id: self.pending_request_id.take(),
                read_time: self.pending_read_time.take(),
            }));
        }
        if self.finished {
            return Ok(None);
        }
        let page = self.fetch_page().await?;
        self.charge_items(page.items.len())?;
        Ok(Some(page))
    }

    /// Collects every remaining item under the configured budgets.
    ///
    /// # Errors
    ///
    /// Returns the same failures as [`Pages::try_next`].
    pub async fn try_collect(&mut self) -> Result<Vec<T>, Error> {
        let mut collected = Vec::new();
        while let Some(item) = self.try_next().await? {
            collected.push(item);
        }
        Ok(collected)
    }

    async fn fetch_page(&mut self) -> Result<Page<T>, Error> {
        if self.page_hops >= self.limits.max_pages {
            return Err(self.exhausted("page"));
        }
        let page = match (self.fetch)(self.token.clone()).await {
            Ok(page) => page,
            Err(error) => {
                self.failed = true;
                return Err(error);
            }
        };
        self.page_hops += 1;
        if !page.next_page_token.is_empty() && !self.seen.insert(page.next_page_token.clone()) {
            self.failed = true;
            return Err(Error::protocol(
                "list response repeated an opaque page token",
            ));
        }
        self.finished = page.next_page_token.is_empty();
        self.token.clone_from(&page.next_page_token);
        Ok(page)
    }

    fn charge_items(&mut self, count: usize) -> Result<(), Error> {
        if self.items.saturating_add(count) > self.limits.max_items {
            return Err(self.exhausted("item"));
        }
        self.items += count;
        Ok(())
    }

    fn exhausted(&mut self, budget: &str) -> Error {
        self.failed = true;
        Error::pagination_limit(format!(
            "automatic pagination exceeded its {budget} budget"
        ))
    }
}

impl<T> fmt::Debug for Pages<T> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Pages")
            .field("page_hops", &self.page_hops)
            .field("items", &self.items)
            .field("has_next_page", &self.has_next_page())
            .finish_non_exhaustive()
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
    max_attempts: Option<u8>,
    unsafe_retry_acknowledged: bool,
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

    /// Overrides the configured attempt budget for this call only.
    ///
    /// The timeout remains a total budget across every attempt, so a larger
    /// attempt count never extends the caller's deadline.
    ///
    /// # Errors
    ///
    /// Returns an error unless the count is between one and eight, matching
    /// the bound [`crate::RetryPolicy`] enforces.
    pub fn with_max_attempts(mut self, attempts: u8) -> Result<Self, Error> {
        if !(1..=8).contains(&attempts) {
            return Err(Error::invalid_argument(
                "per-request retry attempts must be between one and eight",
            ));
        }
        self.max_attempts = Some(attempts);
        Ok(self)
    }

    /// Retries an RPC this SDK classifies as non-idempotent.
    ///
    /// The name is deliberate and there is no bare boolean equivalent: the
    /// caller asserts that the RPC is externally deduplicated, and accepts
    /// that a retry may produce a second durable effect. It cannot be applied
    /// to an RPC that is already retryable, and it can never make a raw-only
    /// never-retry RPC retryable.
    ///
    /// # Errors
    ///
    /// Returns an error unless the count is between one and eight.
    pub fn with_unsafe_retry_of_non_idempotent_rpc(mut self, attempts: u8) -> Result<Self, Error> {
        self = self.with_max_attempts(attempts)?;
        self.unsafe_retry_acknowledged = true;
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
            max_attempts: self.max_attempts,
            unsafe_retry_acknowledged: self.unsafe_retry_acknowledged,
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
    pub(crate) max_attempts: Option<u8>,
    pub(crate) unsafe_retry_acknowledged: bool,
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
    /// Returns the budget still available to this call.
    ///
    /// The deadline is a total budget spanning credential acquisition and
    /// every retry, so each consumer reads it through this one accessor.
    pub(crate) fn remaining(&self) -> Result<Duration, Error> {
        self.deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(Error::deadline_exceeded)
    }

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
