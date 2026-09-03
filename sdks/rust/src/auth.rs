use std::{
    collections::HashMap,
    fmt,
    net::Ipv4Addr,
    sync::Arc,
    time::{Duration, SystemTime},
};

use serde_json::Value;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
    sync::{Mutex, Notify},
};
use tonic::codegen::async_trait;

use crate::Error;

const TOKEN_REFRESH_SKEW: Duration = Duration::from_secs(30);
const MAX_TOKEN_LIFETIME: Duration = Duration::from_mins(65);
const DEFAULT_EXCHANGE_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_EXCHANGE_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_AUDIENCE_BYTES: usize = 2_048;
const MAX_METADATA_RESPONSE_BYTES: usize = 32 * 1_024;

/// A short-lived bearer credential. Its secret is deliberately private and
/// redacted from `Debug` output.
#[derive(Clone)]
pub struct AccessToken {
    secret: String,
    expires_at: SystemTime,
}

impl AccessToken {
    /// Creates a token returned by a workload-identity provider.
    ///
    /// # Errors
    ///
    /// Returns an error when the token is empty, oversized, or cannot be
    /// represented safely as bearer metadata.
    pub fn new(secret: impl Into<String>, expires_at: SystemTime) -> Result<Self, Error> {
        let secret = secret.into();
        if secret.is_empty()
            || secret.len() > 16 * 1024
            || !secret.bytes().all(|byte| byte.is_ascii_graphic())
        {
            return Err(Error::authentication(
                "credential provider returned an invalid access token",
            ));
        }
        Ok(Self { secret, expires_at })
    }

    pub(crate) fn authorization_value(&self, now: SystemTime) -> Result<String, Error> {
        let remaining = self
            .expires_at
            .duration_since(now)
            .map_err(|_| Error::authentication("credential provider returned an expired token"))?;
        if remaining <= TOKEN_REFRESH_SKEW {
            return Err(Error::authentication(
                "credential provider returned a token too close to expiry",
            ));
        }
        if remaining > MAX_TOKEN_LIFETIME {
            return Err(Error::authentication(
                "credential provider must return a short-lived token",
            ));
        }
        Ok(format!("Bearer {}", self.secret))
    }

    pub(crate) fn expires_at(&self) -> SystemTime {
        self.expires_at
    }
}

impl fmt::Debug for AccessToken {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AccessToken")
            .field("secret", &"<redacted>")
            .field("expires_at", &self.expires_at)
            .finish()
    }
}

/// Injectable short-lived token source. A production implementation normally
/// exchanges workload identity for an audience-bound access token and caches
/// it only until the refresh window.
#[async_trait]
pub trait TokenProvider: Send + Sync {
    async fn token(&self, audience: &str) -> Result<AccessToken, Error>;
}

/// GCP workload-identity token source backed by the GCE/GKE metadata identity
/// endpoint. Tokens are audience-bound, cached only outside the refresh skew,
/// and singleflighted per audience.
#[derive(Clone)]
pub struct GcpWorkloadIdentityProvider {
    inner: Arc<GcpProviderInner>,
}

struct GcpProviderInner {
    exchange: Arc<dyn GcpIdentityTokenExchange>,
    exchange_timeout: Duration,
    state: Mutex<GcpProviderState>,
}

#[derive(Default)]
struct GcpProviderState {
    cached: HashMap<String, AccessToken>,
    in_flight: HashMap<String, Arc<TokenFlight>>,
}

struct TokenFlight {
    result: Mutex<Option<Result<AccessToken, ()>>>,
    ready: Notify,
}

impl TokenFlight {
    fn new() -> Self {
        Self {
            result: Mutex::new(None),
            ready: Notify::new(),
        }
    }

    async fn wait(&self) -> Result<AccessToken, Error> {
        loop {
            let notified = self.ready.notified();
            if let Some(result) = self.result.lock().await.clone() {
                return result
                    .map_err(|()| Error::authentication("GCP workload identity exchange failed"));
            }
            notified.await;
        }
    }
}

impl GcpWorkloadIdentityProvider {
    /// Creates the production GCP workload-identity provider.
    ///
    /// # Errors
    ///
    /// Returns an error when the exchange timeout is zero or exceeds the
    /// SDK's bounded credential-exchange limit.
    pub fn new(exchange_timeout: Duration) -> Result<Self, Error> {
        Self::with_exchange(exchange_timeout, Arc::new(GcpMetadataIdentityExchange))
    }

    #[cfg(test)]
    pub(crate) fn with_test_exchange(
        exchange_timeout: Duration,
        exchange: Arc<dyn GcpIdentityTokenExchange>,
    ) -> Result<Self, Error> {
        Self::with_exchange(exchange_timeout, exchange)
    }

    fn with_exchange(
        exchange_timeout: Duration,
        exchange: Arc<dyn GcpIdentityTokenExchange>,
    ) -> Result<Self, Error> {
        if exchange_timeout.is_zero() || exchange_timeout > MAX_EXCHANGE_TIMEOUT {
            return Err(Error::configuration(
                "GCP credential exchange timeout must be positive and at most thirty seconds",
            ));
        }
        Ok(Self {
            inner: Arc::new(GcpProviderInner {
                exchange,
                exchange_timeout,
                state: Mutex::new(GcpProviderState::default()),
            }),
        })
    }
}

impl Default for GcpWorkloadIdentityProvider {
    fn default() -> Self {
        // The default is a compile-time valid duration.
        Self::new(DEFAULT_EXCHANGE_TIMEOUT).expect("default exchange timeout is valid")
    }
}

#[async_trait]
impl TokenProvider for GcpWorkloadIdentityProvider {
    async fn token(&self, audience: &str) -> Result<AccessToken, Error> {
        validate_audience(audience)?;

        let (flight, leader) = {
            let mut state = self.inner.state.lock().await;
            if let Some(token) = state.cached.get(audience)
                && token.authorization_value(SystemTime::now()).is_ok()
            {
                return Ok(token.clone());
            }
            state.cached.remove(audience);
            if let Some(flight) = state.in_flight.get(audience) {
                (Arc::clone(flight), false)
            } else {
                let flight = Arc::new(TokenFlight::new());
                state
                    .in_flight
                    .insert(audience.to_owned(), Arc::clone(&flight));
                (flight, true)
            }
        };

        if leader {
            let inner = Arc::clone(&self.inner);
            let audience = audience.to_owned();
            let flight_for_task = Arc::clone(&flight);
            tokio::spawn(async move {
                let result = tokio::time::timeout(
                    inner.exchange_timeout,
                    inner.exchange.exchange(&audience),
                )
                .await
                .ok()
                .and_then(Result::ok)
                .and_then(|jwt| access_token_from_jwt(jwt, &audience).ok())
                .ok_or(());

                {
                    let mut state = inner.state.lock().await;
                    state.in_flight.remove(&audience);
                    if let Ok(token) = &result {
                        state.cached.insert(audience, token.clone());
                    }
                }
                *flight_for_task.result.lock().await = Some(result);
                flight_for_task.ready.notify_waiters();
            });
        }

        flight.wait().await
    }
}

#[async_trait]
pub(crate) trait GcpIdentityTokenExchange: Send + Sync {
    async fn exchange(&self, audience: &str) -> Result<String, Error>;
}

struct GcpMetadataIdentityExchange;

#[async_trait]
impl GcpIdentityTokenExchange for GcpMetadataIdentityExchange {
    async fn exchange(&self, audience: &str) -> Result<String, Error> {
        let encoded_audience = percent_encode_query_value(audience);
        let request = format!(
            "GET /computeMetadata/v1/instance/service-accounts/default/identity?audience={encoded_audience}&format=full HTTP/1.1\r\nHost: metadata.google.internal\r\nMetadata-Flavor: Google\r\nConnection: close\r\n\r\n"
        );
        let mut stream = TcpStream::connect((Ipv4Addr::new(169, 254, 169, 254), 80))
            .await
            .map_err(|_| Error::authentication("GCP workload identity exchange failed"))?;
        stream
            .write_all(request.as_bytes())
            .await
            .map_err(|_| Error::authentication("GCP workload identity exchange failed"))?;

        let mut response = Vec::new();
        loop {
            let mut chunk = [0_u8; 4_096];
            let read = stream
                .read(&mut chunk)
                .await
                .map_err(|_| Error::authentication("GCP workload identity exchange failed"))?;
            if read == 0 {
                break;
            }
            if response.len().saturating_add(read) > MAX_METADATA_RESPONSE_BYTES {
                return Err(Error::authentication(
                    "GCP workload identity exchange failed",
                ));
            }
            response.extend_from_slice(&chunk[..read]);
        }
        parse_metadata_response(&response)
    }
}

fn validate_audience(audience: &str) -> Result<(), Error> {
    if audience.is_empty()
        || audience.len() > MAX_AUDIENCE_BYTES
        || !audience.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
    {
        return Err(Error::authentication(
            "GCP workload identity audience is invalid",
        ));
    }
    Ok(())
}

fn percent_encode_query_value(value: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            encoded.push(char::from(byte));
        } else {
            encoded.push('%');
            encoded.push(char::from(HEX[usize::from(byte >> 4)]));
            encoded.push(char::from(HEX[usize::from(byte & 0x0f)]));
        }
    }
    encoded
}

fn parse_metadata_response(response: &[u8]) -> Result<String, Error> {
    let separator = response
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| Error::authentication("GCP workload identity exchange failed"))?;
    let headers = std::str::from_utf8(&response[..separator])
        .map_err(|_| Error::authentication("GCP workload identity exchange failed"))?;
    let mut lines = headers.split("\r\n");
    if !lines
        .next()
        .is_some_and(|status| status.starts_with("HTTP/1.1 200 "))
    {
        return Err(Error::authentication(
            "GCP workload identity exchange failed",
        ));
    }
    let metadata_flavor = lines.any(|line| {
        line.split_once(':').is_some_and(|(name, value)| {
            name.eq_ignore_ascii_case("metadata-flavor") && value.trim() == "Google"
        })
    });
    if !metadata_flavor {
        return Err(Error::authentication(
            "GCP workload identity exchange failed",
        ));
    }
    let body = std::str::from_utf8(&response[separator + 4..])
        .map_err(|_| Error::authentication("GCP workload identity exchange failed"))?
        .trim();
    if body.is_empty()
        || body.len() > 16 * 1024
        || !body.bytes().all(|byte| byte.is_ascii_graphic())
    {
        return Err(Error::authentication(
            "GCP workload identity exchange failed",
        ));
    }
    Ok(body.to_owned())
}

fn access_token_from_jwt(jwt: String, audience: &str) -> Result<AccessToken, Error> {
    let mut parts = jwt.split('.');
    let _header = parts.next();
    let payload = parts
        .next()
        .ok_or_else(|| Error::authentication("GCP workload identity exchange failed"))?;
    if parts.next().is_none() || parts.next().is_some() {
        return Err(Error::authentication(
            "GCP workload identity exchange failed",
        ));
    }
    let decoded = decode_base64url(payload)?;
    let claims: Value = serde_json::from_slice(&decoded)
        .map_err(|_| Error::authentication("GCP workload identity exchange failed"))?;
    let audience_matches = match claims.get("aud") {
        Some(Value::String(value)) => value == audience,
        Some(Value::Array(values)) => {
            !values.is_empty()
                && values.iter().all(Value::is_string)
                && values.iter().any(|value| value.as_str() == Some(audience))
        }
        _ => false,
    };
    if !audience_matches {
        return Err(Error::authentication(
            "GCP workload identity exchange failed",
        ));
    }
    let expires_at_seconds = claims
        .get("exp")
        .and_then(Value::as_u64)
        .ok_or_else(|| Error::authentication("GCP workload identity exchange failed"))?;
    let expires_at = SystemTime::UNIX_EPOCH
        .checked_add(Duration::from_secs(expires_at_seconds))
        .ok_or_else(|| Error::authentication("GCP workload identity exchange failed"))?;
    let token = AccessToken::new(jwt, expires_at)?;
    token.authorization_value(SystemTime::now())?;
    Ok(token)
}

fn decode_base64url(value: &str) -> Result<Vec<u8>, Error> {
    if value.is_empty() || value.len() > MAX_METADATA_RESPONSE_BYTES || value.contains('=') {
        return Err(Error::authentication(
            "GCP workload identity exchange failed",
        ));
    }
    let mut output = Vec::with_capacity(value.len().saturating_mul(3) / 4);
    let mut accumulator = 0_u32;
    let mut bits = 0_u8;
    for byte in value.bytes() {
        let sextet = match byte {
            b'A'..=b'Z' => byte - b'A',
            b'a'..=b'z' => byte - b'a' + 26,
            b'0'..=b'9' => byte - b'0' + 52,
            b'-' => 62,
            b'_' => 63,
            _ => {
                return Err(Error::authentication(
                    "GCP workload identity exchange failed",
                ));
            }
        };
        accumulator = (accumulator << 6) | u32::from(sextet);
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            output.push(((accumulator >> bits) & 0xff) as u8);
        }
    }
    if bits != 0 && (accumulator & ((1_u32 << bits) - 1)) != 0 {
        return Err(Error::authentication(
            "GCP workload identity exchange failed",
        ));
    }
    Ok(output)
}
