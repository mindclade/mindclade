use std::{fmt, net::IpAddr, sync::Arc, time::Duration};

use tonic::codegen::http::Uri;

use crate::{Error, TokenProvider};

const DEFAULT_RPC_TIMEOUT: Duration = Duration::from_secs(20);
const DEFAULT_POLL_INTERVAL: Duration = Duration::from_millis(500);
const DEFAULT_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);

/// A governed Mindclade runtime environment.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Environment {
    Local,
    Development,
    Staging,
    Production,
}

impl Environment {
    fn endpoint(self) -> &'static str {
        match self {
            Self::Local => "https://127.0.0.1:9443",
            Self::Development => "https://control-plane.development.mindclade.internal:443",
            Self::Staging => "https://control-plane.staging.mindclade.internal:443",
            Self::Production => "https://control-plane.production.mindclade.internal:443",
        }
    }
}

/// Authenticated identity scope expected by the internal control plane.
///
/// The server remains authoritative and verifies these expectations against
/// the workload identity credential; they are not authorization claims.
#[derive(Clone, Debug, Eq, PartialEq)]
#[allow(clippy::struct_field_names)] // Names intentionally match contract identity fields.
pub struct Identity {
    tenant_id: String,
    project_id: String,
    principal_id: String,
}

impl Identity {
    /// Creates a validated identity expectation.
    ///
    /// # Errors
    ///
    /// Returns an error if any identifier is empty or unsafe for gRPC
    /// metadata.
    pub fn new(
        tenant_id: impl Into<String>,
        project_id: impl Into<String>,
        principal_id: impl Into<String>,
    ) -> Result<Self, Error> {
        let value = Self {
            tenant_id: tenant_id.into(),
            project_id: project_id.into(),
            principal_id: principal_id.into(),
        };
        validate_metadata_value("tenant ID", &value.tenant_id, true)?;
        validate_metadata_value("project ID", &value.project_id, true)?;
        validate_metadata_value("principal ID", &value.principal_id, true)?;
        Ok(value)
    }

    #[must_use]
    pub fn tenant_id(&self) -> &str {
        &self.tenant_id
    }

    #[must_use]
    pub fn project_id(&self) -> &str {
        &self.project_id
    }

    #[must_use]
    pub fn principal_id(&self) -> &str {
        &self.principal_id
    }
}

/// Bounded retry policy for safe reads and idempotent commands.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RetryPolicy {
    pub(crate) max_attempts: u8,
    pub(crate) initial_backoff: Duration,
    pub(crate) max_backoff: Duration,
}

impl RetryPolicy {
    /// Creates a retry policy. At most eight attempts are permitted.
    ///
    /// # Errors
    ///
    /// Returns an error for an unbounded attempt count or invalid backoff
    /// interval.
    pub fn new(
        max_attempts: u8,
        initial_backoff: Duration,
        max_backoff: Duration,
    ) -> Result<Self, Error> {
        if !(1..=8).contains(&max_attempts) {
            return Err(Error::configuration(
                "retry attempts must be between one and eight",
            ));
        }
        if initial_backoff.is_zero() || max_backoff < initial_backoff {
            return Err(Error::configuration(
                "retry backoff must be positive and monotonically bounded",
            ));
        }
        if max_backoff > Duration::from_secs(30) {
            return Err(Error::configuration(
                "maximum retry backoff cannot exceed thirty seconds",
            ));
        }
        Ok(Self {
            max_attempts,
            initial_backoff,
            max_backoff,
        })
    }

    #[must_use]
    pub fn max_attempts(self) -> u8 {
        self.max_attempts
    }
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 4,
            initial_backoff: Duration::from_millis(100),
            max_backoff: Duration::from_secs(2),
        }
    }
}

#[derive(Clone)]
pub(crate) enum TrustRoots {
    WebPki,
    CustomCa(Arc<[u8]>),
}

/// Immutable, validated SDK runtime policy.
#[derive(Clone)]
pub struct Config {
    pub(crate) environment: Environment,
    pub(crate) endpoint: String,
    pub(crate) identity: Identity,
    pub(crate) token_provider: Option<Arc<dyn TokenProvider>>,
    pub(crate) audience: String,
    pub(crate) rpc_timeout: Duration,
    pub(crate) poll_interval: Duration,
    pub(crate) connect_timeout: Duration,
    pub(crate) retry: RetryPolicy,
    pub(crate) server_name: Option<String>,
    pub(crate) trust_roots: TrustRoots,
    pub(crate) insecure_loopback: bool,
}

impl Config {
    /// Starts a validated configuration builder. The token provider is an
    /// injected workload-identity abstraction and must issue short-lived
    /// credentials.
    pub fn builder(
        environment: Environment,
        identity: Identity,
        token_provider: Arc<dyn TokenProvider>,
    ) -> ConfigBuilder {
        ConfigBuilder {
            environment,
            endpoint: None,
            identity,
            token_provider: Some(token_provider),
            audience: None,
            rpc_timeout: DEFAULT_RPC_TIMEOUT,
            poll_interval: DEFAULT_POLL_INTERVAL,
            connect_timeout: DEFAULT_CONNECT_TIMEOUT,
            retry: RetryPolicy::default(),
            server_name: None,
            custom_ca: None,
            insecure_loopback: false,
        }
    }

    /// Starts an explicitly unauthenticated plaintext builder for hermetic
    /// Local loopback tests. This mode cannot carry a credential provider.
    #[must_use]
    pub fn local_insecure_builder(identity: Identity) -> ConfigBuilder {
        ConfigBuilder {
            environment: Environment::Local,
            endpoint: Some("http://127.0.0.1:9443".to_owned()),
            identity,
            token_provider: None,
            audience: None,
            rpc_timeout: DEFAULT_RPC_TIMEOUT,
            poll_interval: DEFAULT_POLL_INTERVAL,
            connect_timeout: DEFAULT_CONNECT_TIMEOUT,
            retry: RetryPolicy::default(),
            server_name: None,
            custom_ca: None,
            insecure_loopback: true,
        }
    }

    #[must_use]
    pub fn environment(&self) -> Environment {
        self.environment
    }

    #[must_use]
    pub fn endpoint(&self) -> &str {
        &self.endpoint
    }

    /// Returns the exact OIDC audience used for workload-identity credentials.
    #[must_use]
    pub fn audience(&self) -> &str {
        &self.audience
    }

    #[must_use]
    pub fn identity(&self) -> &Identity {
        &self.identity
    }

    #[must_use]
    pub fn default_rpc_timeout(&self) -> Duration {
        self.rpc_timeout
    }

    #[must_use]
    pub fn retry_policy(&self) -> RetryPolicy {
        self.retry
    }
}

impl fmt::Debug for Config {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Config")
            .field("environment", &self.environment)
            .field("endpoint", &self.endpoint)
            .field("identity", &self.identity)
            .field("token_provider", &"<redacted>")
            .field("audience", &self.audience)
            .field("rpc_timeout", &self.rpc_timeout)
            .field("poll_interval", &self.poll_interval)
            .field("connect_timeout", &self.connect_timeout)
            .field("retry", &self.retry)
            .field("server_name", &self.server_name)
            .field("insecure_loopback", &self.insecure_loopback)
            .finish_non_exhaustive()
    }
}

/// Builder for [`Config`].
pub struct ConfigBuilder {
    environment: Environment,
    endpoint: Option<String>,
    identity: Identity,
    token_provider: Option<Arc<dyn TokenProvider>>,
    audience: Option<String>,
    rpc_timeout: Duration,
    poll_interval: Duration,
    connect_timeout: Duration,
    retry: RetryPolicy,
    server_name: Option<String>,
    custom_ca: Option<Vec<u8>>,
    insecure_loopback: bool,
}

impl ConfigBuilder {
    #[must_use]
    pub fn endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.endpoint = Some(endpoint.into());
        self
    }

    #[must_use]
    pub fn audience(mut self, audience: impl Into<String>) -> Self {
        self.audience = Some(audience.into());
        self
    }

    #[must_use]
    pub fn default_rpc_timeout(mut self, timeout: Duration) -> Self {
        self.rpc_timeout = timeout;
        self
    }

    #[must_use]
    pub fn poll_interval(mut self, interval: Duration) -> Self {
        self.poll_interval = interval;
        self
    }

    #[must_use]
    pub fn connect_timeout(mut self, timeout: Duration) -> Self {
        self.connect_timeout = timeout;
        self
    }

    #[must_use]
    pub fn retry_policy(mut self, policy: RetryPolicy) -> Self {
        self.retry = policy;
        self
    }

    #[must_use]
    pub fn server_name(mut self, server_name: impl Into<String>) -> Self {
        self.server_name = Some(server_name.into());
        self
    }

    /// Adds a private trust anchor without disabling certificate or hostname
    /// verification.
    #[must_use]
    pub fn custom_ca_pem(mut self, pem: impl Into<Vec<u8>>) -> Self {
        self.custom_ca = Some(pem.into());
        self
    }

    /// Allows plaintext only for the Local environment and a loopback host.
    /// It cannot weaken development, staging, or production endpoints.
    #[must_use]
    pub fn insecure_loopback_for_testing(mut self) -> Self {
        self.insecure_loopback = true;
        self
    }

    /// Validates all configuration and produces immutable runtime policy.
    ///
    /// # Errors
    ///
    /// Returns an error if endpoint, TLS, duration, audience, or trust-root
    /// policy is invalid.
    pub fn build(self) -> Result<Config, Error> {
        validate_duration("default RPC timeout", self.rpc_timeout)?;
        validate_duration("poll interval", self.poll_interval)?;
        validate_duration("connect timeout", self.connect_timeout)?;

        let endpoint = self
            .endpoint
            .unwrap_or_else(|| self.environment.endpoint().to_owned());
        let uri = validate_endpoint(&endpoint, self.environment, self.insecure_loopback)?;

        if self.insecure_loopback && self.token_provider.is_some() {
            return Err(Error::configuration(
                "credentials cannot be sent over plaintext transport",
            ));
        }
        if !self.insecure_loopback && self.token_provider.is_none() {
            return Err(Error::configuration(
                "secure clients require a workload-identity token provider",
            ));
        }

        let audience = self
            .audience
            .unwrap_or_else(|| canonical_https_origin(&uri));
        validate_metadata_value("credential audience", &audience, true)?;

        let server_name = self.server_name.map(|value| value.trim().to_owned());
        if let Some(value) = &server_name {
            validate_server_name(value)?;
        }
        if uri.scheme_str() == Some("http") && server_name.is_some() {
            return Err(Error::configuration(
                "a TLS server name cannot be configured for plaintext transport",
            ));
        }

        let trust_roots = match self.custom_ca {
            Some(ca) => {
                if ca.is_empty() || ca.len() > 1_048_576 {
                    return Err(Error::configuration(
                        "custom CA PEM must contain at most one mebibyte",
                    ));
                }
                TrustRoots::CustomCa(Arc::from(ca))
            }
            None => TrustRoots::WebPki,
        };

        Ok(Config {
            environment: self.environment,
            endpoint,
            identity: self.identity,
            token_provider: self.token_provider,
            audience,
            rpc_timeout: self.rpc_timeout,
            poll_interval: self.poll_interval,
            connect_timeout: self.connect_timeout,
            retry: self.retry,
            server_name,
            trust_roots,
            insecure_loopback: self.insecure_loopback,
        })
    }
}

fn validate_duration(name: &str, value: Duration) -> Result<(), Error> {
    if value.is_zero() || value > Duration::from_hours(24) {
        return Err(Error::configuration(format!(
            "{name} must be positive and at most twenty-four hours"
        )));
    }
    Ok(())
}

fn validate_endpoint(
    endpoint: &str,
    environment: Environment,
    insecure_loopback: bool,
) -> Result<Uri, Error> {
    if endpoint.trim() != endpoint || endpoint.contains(['\r', '\n']) {
        return Err(Error::configuration("endpoint is not canonical"));
    }
    let uri: Uri = endpoint
        .parse()
        .map_err(|_| Error::configuration("endpoint is not a valid absolute URI"))?;
    if uri.authority().is_none() || uri.host().is_none() {
        return Err(Error::configuration("endpoint must include a host"));
    }
    if uri
        .authority()
        .is_some_and(|value| value.as_str().contains('@'))
    {
        return Err(Error::configuration(
            "endpoint cannot contain user information",
        ));
    }
    if uri.path() != "/" || uri.query().is_some() {
        return Err(Error::configuration(
            "endpoint cannot contain a path, query, or fragment",
        ));
    }
    match uri.scheme_str() {
        Some("https") => {
            if insecure_loopback {
                return Err(Error::configuration(
                    "plaintext test mode requires an http loopback endpoint",
                ));
            }
        }
        Some("http") => {
            if environment != Environment::Local
                || !insecure_loopback
                || !uri.host().is_some_and(is_loopback_host)
            {
                return Err(Error::configuration(
                    "plaintext transport is restricted to explicit Local loopback tests",
                ));
            }
        }
        _ => return Err(Error::configuration("endpoint scheme must be https")),
    }
    Ok(uri)
}

fn is_loopback_host(host: &str) -> bool {
    matches!(host, "localhost" | "127.0.0.1" | "::1" | "[::1]")
}

fn canonical_https_origin(uri: &Uri) -> String {
    let host = uri
        .host()
        .expect("validated endpoints always have a host")
        .trim_start_matches('[')
        .trim_end_matches(']');
    let canonical_host = host
        .parse::<IpAddr>()
        .map_or_else(|_| host.to_ascii_lowercase(), |value| value.to_string());
    let origin_host = if canonical_host.contains(':') {
        format!("[{canonical_host}]")
    } else {
        canonical_host
    };
    match uri.port_u16() {
        Some(port) if port != 443 => format!("https://{origin_host}:{port}"),
        _ => format!("https://{origin_host}"),
    }
}

fn validate_server_name(value: &str) -> Result<(), Error> {
    validate_metadata_value("TLS server name", value, true)?;
    if value.contains(['/', ':', '@']) {
        return Err(Error::configuration("TLS server name must be a DNS name"));
    }
    Ok(())
}

pub(crate) fn validate_metadata_value(
    name: &str,
    value: &str,
    required: bool,
) -> Result<(), Error> {
    if required && value.is_empty() {
        return Err(Error::invalid_argument(format!("{name} cannot be empty")));
    }
    if value.len() > 512 || !value.bytes().all(|byte| (0x21..=0x7e).contains(&byte)) {
        return Err(Error::invalid_argument(format!(
            "{name} must contain at most 512 visible ASCII characters"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod audience_tests {
    use std::sync::Arc;

    use tonic::codegen::async_trait;

    use super::{Config, Environment, Identity};
    use crate::{AccessToken, Error, TokenProvider};

    struct NeverTokenProvider;

    #[async_trait]
    impl TokenProvider for NeverTokenProvider {
        async fn token(&self, _audience: &str) -> Result<AccessToken, Error> {
            Err(Error::authentication("test provider is never invoked"))
        }
    }

    fn config(endpoint: &str, audience: Option<&str>) -> Config {
        let identity = Identity::new("tenant-01", "project-01", "principal-01").unwrap();
        let mut builder = Config::builder(
            Environment::Development,
            identity,
            Arc::new(NeverTokenProvider),
        )
        .endpoint(endpoint);
        if let Some(value) = audience {
            builder = builder.audience(value);
        }
        builder.build().unwrap()
    }

    #[test]
    fn workload_identity_audience_uses_canonical_https_origin() {
        for (endpoint, expected) in [
            (
                "https://CONTROL-PLANE.EXAMPLE:443",
                "https://control-plane.example",
            ),
            (
                "https://control-plane.example:8443",
                "https://control-plane.example:8443",
            ),
            ("https://[2001:db8::1]:443", "https://[2001:db8::1]"),
        ] {
            assert_eq!(config(endpoint, None).audience(), expected);
        }
        assert_eq!(
            config(
                "https://control-plane.example:443",
                Some("https://verifier.example/custom-audience"),
            )
            .audience(),
            "https://verifier.example/custom-audience"
        );
    }
}
