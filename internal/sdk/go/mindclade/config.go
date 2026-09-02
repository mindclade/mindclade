package mindclade

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	defaultRPCTimeout       = 20 * time.Second
	defaultOperationTimeout = 30 * time.Minute
	defaultPollInterval     = 500 * time.Millisecond
	defaultRetryBaseDelay   = 100 * time.Millisecond
	defaultRetryMaxDelay    = 2 * time.Second
	defaultMaxAttempts      = 4
)

// Environment selects a governed control-plane endpoint. An explicit endpoint
// supplied with WithEndpoint always takes precedence.
type Environment string

const (
	Local       Environment = "local"
	Development Environment = "development"
	Staging     Environment = "staging"
	Production  Environment = "production"
)

var environmentEndpoints = map[Environment]string{
	Local:       "127.0.0.1:9443",
	Development: "control-plane.development.mindclade.internal:443",
	Staging:     "control-plane.staging.mindclade.internal:443",
	Production:  "control-plane.production.mindclade.internal:443",
}

// TokenProvider supplies short-lived bearer credentials. Implementations must
// be concurrency-safe and must never return a long-lived static secret unless
// explicitly configured for a local test.
type TokenProvider interface {
	Token(ctx context.Context) (Token, error)
}

// Token is one short-lived authorization token.
type Token struct {
	AccessToken string
	Expiry      time.Time
}

// Observer receives bounded transport metadata and never request or response
// payloads. Implementations may bridge this to OpenTelemetry or metrics.
type Observer interface {
	RPCStarted(method string, attempt int)
	RPCFinished(method string, attempt int, elapsed time.Duration, code Code)
}

type nopObserver struct{}

func (nopObserver) RPCStarted(string, int)                       {}
func (nopObserver) RPCFinished(string, int, time.Duration, Code) {}

// Config is the validated SDK runtime policy. Construct it through New and
// Option values so insecure combinations cannot be represented accidentally.
type Config struct {
	Environment             Environment
	Endpoint                string
	Audience                string
	TenantID                string
	ProjectID               string
	PrincipalID             string
	DefaultRPCTimeout       time.Duration
	DefaultOperationTimeout time.Duration
	PollInterval            time.Duration
	RetryBaseDelay          time.Duration
	RetryMaxDelay           time.Duration
	MaxAttempts             int
	ServerName              string
	TLSConfig               *tls.Config
	TokenProvider           TokenProvider
	Observer                Observer
	UserAgent               string
	// jitter supplies the uniform random component of the retry backoff. It is
	// unexported so the transport policy cannot be widened from outside the
	// SDK, and injectable so tests can script backoff deterministically. A nil
	// value selects the cryptographically seeded default.
	jitter             jitterSource
	insecureForTesting bool
	workloadIdentity   bool
	ownedTokenProvider bool
}

type Option func(*Config) error

func defaultConfig() Config {
	return Config{
		Environment:             Development,
		DefaultRPCTimeout:       defaultRPCTimeout,
		DefaultOperationTimeout: defaultOperationTimeout,
		PollInterval:            defaultPollInterval,
		RetryBaseDelay:          defaultRetryBaseDelay,
		RetryMaxDelay:           defaultRetryMaxDelay,
		MaxAttempts:             defaultMaxAttempts,
		Observer:                nopObserver{},
		UserAgent:               "mindclade-internal-go-sdk/0.1",
	}
}

func WithEnvironment(environment Environment) Option {
	return func(config *Config) error {
		if _, ok := environmentEndpoints[environment]; !ok {
			return fmt.Errorf("mindclade: unknown environment %q", environment)
		}
		config.Environment = environment
		return nil
	}
}

func WithEndpoint(endpoint string) Option {
	return func(config *Config) error {
		config.Endpoint = strings.TrimSpace(endpoint)
		return nil
	}
}

// WithAudience selects the expected OIDC audience for workload-identity ID
// tokens. It must match the control-plane verifier exactly.
func WithAudience(audience string) Option {
	return func(config *Config) error {
		config.Audience = strings.TrimSpace(audience)
		return nil
	}
}

func WithTenantProject(tenantID, projectID string) Option {
	return func(config *Config) error {
		config.TenantID = strings.TrimSpace(tenantID)
		config.ProjectID = strings.TrimSpace(projectID)
		return nil
	}
}

func WithPrincipal(principalID string) Option {
	return func(config *Config) error {
		config.PrincipalID = strings.TrimSpace(principalID)
		return nil
	}
}

func WithDefaultTimeout(timeout time.Duration) Option {
	return func(config *Config) error {
		config.DefaultRPCTimeout = timeout
		return nil
	}
}

// WithOperationTimeout sets the total default budget for long-running wait
// and watch helpers when the caller did not already provide a deadline. It is
// deliberately separate from the per-RPC budget.
func WithOperationTimeout(timeout time.Duration) Option {
	return func(config *Config) error {
		config.DefaultOperationTimeout = timeout
		return nil
	}
}

func WithPollInterval(interval time.Duration) Option {
	return func(config *Config) error {
		config.PollInterval = interval
		return nil
	}
}

// WithRetryPolicy narrows or widens the fixed default transport retry policy:
// four attempts, 100ms growing to a 2s cap, with full jitter — every wait is
// drawn uniformly from [0, min(cap, base*2^n)]. The policy governs only RPCs
// the method policy already classifies as safe or idempotent; it can never
// make an ineligible RPC retryable.
func WithRetryPolicy(maxAttempts int, baseDelay, maxDelay time.Duration) Option {
	return func(config *Config) error {
		config.MaxAttempts = maxAttempts
		config.RetryBaseDelay = baseDelay
		config.RetryMaxDelay = maxDelay
		return nil
	}
}

func WithTLSConfig(tlsConfig *tls.Config) Option {
	return func(config *Config) error {
		if tlsConfig == nil {
			return errors.New("mindclade: TLS config cannot be nil")
		}
		config.TLSConfig = tlsConfig.Clone()
		return nil
	}
}

func WithServerName(serverName string) Option {
	return func(config *Config) error {
		config.ServerName = strings.TrimSpace(serverName)
		return nil
	}
}

func WithTokenProvider(provider TokenProvider) Option {
	return func(config *Config) error {
		if provider == nil {
			return errors.New("mindclade: token provider cannot be nil")
		}
		config.TokenProvider = provider
		config.workloadIdentity = false
		config.ownedTokenProvider = false
		return nil
	}
}

// WithWorkloadIdentity discovers Application Default Credentials and obtains
// short-lived audience-bound Google ID tokens. No token is persisted by the
// SDK, and the refresh context lives exactly as long as the client.
func WithWorkloadIdentity() Option {
	return func(config *Config) error {
		config.workloadIdentity = true
		config.ownedTokenProvider = false
		config.TokenProvider = nil
		return nil
	}
}

func WithObserver(observer Observer) Option {
	return func(config *Config) error {
		if observer == nil {
			return errors.New("mindclade: observer cannot be nil")
		}
		config.Observer = observer
		return nil
	}
}

func WithUserAgent(userAgent string) Option {
	return func(config *Config) error {
		config.UserAgent = strings.TrimSpace(userAgent)
		return nil
	}
}

// WithInsecureTransportForTesting is accepted only for loopback endpoints and
// Local. It exists for hermetic bufconn/local tests, never production setup.
func WithInsecureTransportForTesting() Option {
	return func(config *Config) error {
		config.insecureForTesting = true
		return nil
	}
}

func (config *Config) finalize() error {
	if config.Endpoint == "" {
		if fromEnvironment := strings.TrimSpace(os.Getenv("MINDCLADE_ENDPOINT")); fromEnvironment != "" {
			config.Endpoint = fromEnvironment
		} else {
			config.Endpoint = environmentEndpoints[config.Environment]
		}
	}
	if config.TenantID == "" {
		config.TenantID = strings.TrimSpace(os.Getenv("MINDCLADE_TENANT_ID"))
	}
	if config.ProjectID == "" {
		config.ProjectID = strings.TrimSpace(os.Getenv("MINDCLADE_PROJECT_ID"))
	}
	if config.PrincipalID == "" {
		config.PrincipalID = strings.TrimSpace(os.Getenv("MINDCLADE_PRINCIPAL_ID"))
	}
	if config.Audience == "" {
		config.Audience = strings.TrimSpace(os.Getenv("MINDCLADE_AUDIENCE"))
	}
	if strings.ContainsAny(config.Endpoint, "\r\n") {
		return errors.New("mindclade: endpoint contains control characters")
	}
	if err := validateEndpoint(config.Endpoint); err != nil {
		return err
	}
	if config.workloadIdentity {
		if config.Audience == "" {
			config.Audience = defaultAudience(config.Endpoint)
		}
		if len(config.Audience) > 1024 || strings.ContainsAny(config.Audience, " \t\r\n") {
			return errors.New("mindclade: workload identity audience is invalid")
		}
	}
	for label, value := range map[string]string{
		"tenant ID": config.TenantID, "project ID": config.ProjectID, "principal ID": config.PrincipalID,
	} {
		if err := validateMetadataIdentifier(label, value); err != nil {
			return err
		}
	}
	if config.DefaultRPCTimeout <= 0 || config.DefaultRPCTimeout > 5*time.Minute {
		return errors.New("mindclade: default RPC timeout must be positive and at most five minutes")
	}
	if config.DefaultOperationTimeout <= 0 || config.DefaultOperationTimeout > 24*time.Hour {
		return errors.New("mindclade: operation timeout must be positive and at most twenty-four hours")
	}
	if config.PollInterval <= 0 || config.PollInterval > time.Minute {
		return errors.New("mindclade: poll interval must be positive and at most one minute")
	}
	if config.MaxAttempts < 1 || config.MaxAttempts > 8 {
		return errors.New("mindclade: max retry attempts must be between 1 and 8")
	}
	if config.RetryBaseDelay <= 0 || config.RetryMaxDelay < config.RetryBaseDelay {
		return errors.New("mindclade: retry delays are invalid")
	}
	if config.Observer == nil {
		config.Observer = nopObserver{}
	}
	if config.UserAgent == "" {
		return errors.New("mindclade: user agent cannot be empty")
	}
	if err := validateMetadataIdentifier("user agent", config.UserAgent); err != nil {
		return err
	}
	if config.ServerName != "" {
		if err := validateServerName(config.ServerName); err != nil {
			return err
		}
	}
	if config.TLSConfig != nil && config.TLSConfig.InsecureSkipVerify {
		return errors.New("mindclade: TLS certificate verification cannot be disabled")
	}
	if config.insecureForTesting {
		if config.Environment != Local || !isLoopbackEndpoint(config.Endpoint) {
			return errors.New("mindclade: insecure transport is restricted to Local loopback")
		}
		if config.workloadIdentity || config.TokenProvider != nil {
			return errors.New("mindclade: credentials cannot be sent over insecure transport")
		}
	} else if !config.workloadIdentity && config.TokenProvider == nil {
		return errors.New("mindclade: workload identity or a token provider is required")
	}
	return nil
}

func validateEndpoint(endpoint string) error {
	if endpoint == "" || len(endpoint) > 1024 || strings.ContainsAny(endpoint, " \t\r\n/?#@") {
		return errors.New("mindclade: endpoint must be a bounded host:port authority")
	}
	host, port, err := net.SplitHostPort(endpoint)
	if err != nil || host == "" || port == "" {
		return errors.New("mindclade: endpoint must include a host and numeric port")
	}
	portNumber, err := strconv.ParseUint(port, 10, 16)
	if err != nil || portNumber == 0 {
		return errors.New("mindclade: endpoint port is invalid")
	}
	return nil
}

func validateMetadataIdentifier(label, value string) error {
	if value == "" || len(value) > 256 {
		return fmt.Errorf("mindclade: %s must be non-empty and at most 256 bytes", label)
	}
	for _, character := range value {
		if character < 0x21 || character > 0x7e {
			return fmt.Errorf("mindclade: %s contains unsafe metadata characters", label)
		}
	}
	return nil
}

func validateServerName(value string) error {
	if len(value) > 253 || strings.ContainsAny(value, " \t\r\n/:@?#") {
		return errors.New("mindclade: TLS server name is invalid")
	}
	return nil
}

func isLoopbackEndpoint(endpoint string) bool {
	host, _, _ := net.SplitHostPort(endpoint)
	host = strings.Trim(host, "[]")
	if host == "localhost" || host == "bufnet" {
		return true
	}
	parsed := net.ParseIP(host)
	return parsed != nil && parsed.IsLoopback()
}

func defaultAudience(endpoint string) string {
	host, port, err := net.SplitHostPort(endpoint)
	if err != nil {
		return ""
	}
	host = strings.ToLower(strings.Trim(host, "[]"))
	if parsed := net.ParseIP(host); parsed != nil {
		host = parsed.String()
	}
	portNumber, err := strconv.ParseUint(port, 10, 16)
	if err != nil || portNumber == 0 {
		return ""
	}
	originHost := host
	if strings.Contains(host, ":") {
		originHost = "[" + host + "]"
	}
	if portNumber == 443 {
		return "https://" + originHost
	}
	return "https://" + net.JoinHostPort(host, strconv.FormatUint(portNumber, 10))
}
