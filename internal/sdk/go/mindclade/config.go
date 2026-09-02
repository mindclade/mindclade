package mindclade

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"runtime"
	"strconv"
	"strings"
	"time"

	"google.golang.org/grpc"
)

// Version is the single source of truth for this SDK's revision. It is stamped
// into the gRPC user agent and into the structured x-mindclade-sdk metadata;
// nothing else in the SDK declares a version.
const Version = "0.2.0"

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

// RPCEvent is the bounded telemetry one transport attempt produces. It carries
// metadata KEY NAMES only: never a request or response payload, never a bearer
// token, never a lease token, and never a metadata value of any kind.
type RPCEvent struct {
	Method       string
	Attempt      int
	Elapsed      time.Duration
	Status       Code
	RequestID    string
	TraceID      string
	MetadataKeys []string
	RetryAfter   time.Duration
}

// RequestObserver receives the complete bounded event for every attempt. An
// Observer that does not implement it keeps receiving the two-argument
// callbacks, so the richer seam is additive rather than a breaking change.
type RequestObserver interface {
	Observer
	RPCAttempt(event RPCEvent)
}

// slogObserver bridges the observer seam to log/slog. It builds every attribute
// from RPCEvent fields, so the no-payload and no-token contract is enforced by
// construction rather than by the discipline of whoever edits it next.
type slogObserver struct {
	logger *slog.Logger
	level  slog.Level
}

func (observer slogObserver) RPCStarted(method string, attempt int) {
	observer.logger.LogAttrs(context.Background(), observer.level, "mindclade rpc started",
		slog.String("method", method), slog.Int("attempt", attempt))
}

// RPCFinished is deliberately silent: RPCAttempt reports the same attempt with
// the complete bounded event, and logging both would double every line.
func (slogObserver) RPCFinished(string, int, time.Duration, Code) {}

func (observer slogObserver) RPCAttempt(event RPCEvent) {
	observer.logger.LogAttrs(context.Background(), observer.level, "mindclade rpc finished",
		slog.String("method", event.Method),
		slog.Int("attempt", event.Attempt),
		slog.Duration("elapsed", event.Elapsed),
		slog.String("status", string(event.Status)),
		slog.String("request_id", event.RequestID),
		slog.String("trace_id", event.TraceID),
		slog.Any("metadata_keys", event.MetadataKeys),
		slog.Duration("retry_after", event.RetryAfter),
	)
}

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
	jitter jitterSource
	// defaultMetadata is caller metadata attached to every call from this
	// client. It is validated against the same credential denylist as the
	// per-request form, so a default can never smuggle a credential.
	defaultMetadata map[string][]string
	// unaryInterceptors and streamInterceptors are caller escape hatches. They
	// run INSIDE the SDK's own policy interceptor, and credential injection
	// happens beneath the whole chain at the transport layer, so a caller
	// interceptor structurally cannot observe or modify an authorization header.
	unaryInterceptors    []grpc.UnaryClientInterceptor
	streamInterceptors   []grpc.StreamClientInterceptor
	omitPlatformMetadata bool
	environmentSet       bool
	insecureForTesting   bool
	workloadIdentity     bool
	ownedTokenProvider   bool
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
		UserAgent:               "mindclade-internal-go-sdk/" + Version,
	}
}

func WithEnvironment(environment Environment) Option {
	return func(config *Config) error {
		if _, ok := environmentEndpoints[environment]; !ok {
			return fmt.Errorf("mindclade: unknown environment %q", environment)
		}
		config.Environment = environment
		config.environmentSet = true
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

// FromEnvironment reads MINDCLADE_* configuration from the process
// environment. It is the ONLY path in the SDK that consults the environment:
// the ordinary constructor never does, so a process variable can never silently
// redirect a client that did not ask for it.
//
// No credential is ever read from the environment. The recognised variables are
// MINDCLADE_ENVIRONMENT, MINDCLADE_ENDPOINT, MINDCLADE_TENANT_ID,
// MINDCLADE_PROJECT_ID, MINDCLADE_PRINCIPAL_ID, MINDCLADE_AUDIENCE, and
// MINDCLADE_LOG; there is deliberately no variable for a token or a key.
//
// The option only fills fields that are still empty, so an explicit With*
// option wins whichever side of FromEnvironment it appears on.
func FromEnvironment() Option {
	return func(config *Config) error {
		if value := strings.TrimSpace(os.Getenv("MINDCLADE_ENVIRONMENT")); value != "" && !config.environmentSet {
			environment := Environment(strings.ToLower(value))
			if _, ok := environmentEndpoints[environment]; !ok {
				return fmt.Errorf("mindclade: unknown MINDCLADE_ENVIRONMENT %q", value)
			}
			config.Environment = environment
			config.environmentSet = true
		}
		for _, field := range []struct {
			variable string
			target   *string
		}{
			{variable: "MINDCLADE_ENDPOINT", target: &config.Endpoint},
			{variable: "MINDCLADE_TENANT_ID", target: &config.TenantID},
			{variable: "MINDCLADE_PROJECT_ID", target: &config.ProjectID},
			{variable: "MINDCLADE_PRINCIPAL_ID", target: &config.PrincipalID},
			{variable: "MINDCLADE_AUDIENCE", target: &config.Audience},
		} {
			if *field.target == "" {
				*field.target = strings.TrimSpace(os.Getenv(field.variable))
			}
		}
		return applyEnvironmentLogging(config)
	}
}

// applyEnvironmentLogging installs the MINDCLADE_LOG observer when the caller
// has not already installed one of their own. An unset or "off" value leaves
// the SDK silent, which is the default.
func applyEnvironmentLogging(config *Config) error {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("MINDCLADE_LOG")))
	if value == "" || value == "off" {
		return nil
	}
	level, ok := logLevels[value]
	if !ok {
		return fmt.Errorf("mindclade: MINDCLADE_LOG must be one of debug, info, warn, error, off")
	}
	if _, silent := config.Observer.(nopObserver); config.Observer != nil && !silent {
		return nil
	}
	config.Observer = slogObserver{logger: slog.Default(), level: level}
	return nil
}

// logLevels is the fixed MINDCLADE_LOG vocabulary, shared by every language.
var logLevels = map[string]slog.Level{
	"debug": slog.LevelDebug,
	"info":  slog.LevelInfo,
	"warn":  slog.LevelWarn,
	"error": slog.LevelError,
}

// WithLogger installs an slog handler as the SDK observer. It logs method,
// attempt, elapsed time, status, request id, and metadata KEY NAMES — never a
// payload, never a token, and never a metadata value.
func WithLogger(logger *slog.Logger, level slog.Level) Option {
	return func(config *Config) error {
		if logger == nil {
			return errors.New("mindclade: logger cannot be nil")
		}
		config.Observer = slogObserver{logger: logger, level: level}
		return nil
	}
}

// WithDefaultMetadata attaches caller metadata to every call this client makes.
// Keys are validated against the same credential denylist the raw-response
// allowlist uses, and no SDK-authoritative key may be shadowed; a rejected key
// fails client construction rather than being dropped silently.
func WithDefaultMetadata(pairs map[string][]string) Option {
	return func(config *Config) error {
		if err := validateCustomMetadata(pairs); err != nil {
			return err
		}
		merged := map[string][]string{}
		for key, values := range config.defaultMetadata {
			merged[key] = append([]string(nil), values...)
		}
		for key, values := range pairs {
			merged[strings.ToLower(strings.TrimSpace(key))] = append([]string(nil), values...)
		}
		config.defaultMetadata = merged
		return nil
	}
}

// WithOmitPlatformMetadata reduces the structured x-mindclade-sdk value to its
// language and version components. Use it when the operating system, machine
// architecture, and runtime build of a caller are not information the receiving
// environment should hold.
func WithOmitPlatformMetadata() Option {
	return func(config *Config) error {
		config.omitPlatformMetadata = true
		return nil
	}
}

// WithInterceptor appends a caller unary interceptor. It runs INSIDE the SDK's
// own policy interceptor, so retry, timeout, identity metadata, and error
// sanitization are already applied when it is reached. Credential injection is
// performed by the transport beneath the entire interceptor chain and is
// therefore not interceptable: a caller interceptor never sees an authorization
// header and cannot add, alter, or remove one.
func WithInterceptor(interceptor grpc.UnaryClientInterceptor) Option {
	return func(config *Config) error {
		if interceptor == nil {
			return errors.New("mindclade: interceptor cannot be nil")
		}
		config.unaryInterceptors = append(config.unaryInterceptors, interceptor)
		return nil
	}
}

// WithStreamInterceptor appends a caller stream interceptor under the same
// contract as WithInterceptor.
func WithStreamInterceptor(interceptor grpc.StreamClientInterceptor) Option {
	return func(config *Config) error {
		if interceptor == nil {
			return errors.New("mindclade: stream interceptor cannot be nil")
		}
		config.streamInterceptors = append(config.streamInterceptors, interceptor)
		return nil
	}
}

// maxPlatformComponentBytes bounds each structured platform component so the
// assembled x-mindclade-sdk value always stays inside the metadata identifier
// bound, whatever a future runtime reports about itself.
const maxPlatformComponentBytes = 64

// platformMetadata builds the structured x-mindclade-sdk value:
//
//	language=go;version=<Version>;os=<GOOS>;arch=<GOARCH>;runtime=go;runtime_version=<runtime.Version()>
//
// Every component is bounded and stripped to graphic ASCII, minus the two
// characters that structure the value, so the result always satisfies
// validateMetadataIdentifier. WithOmitPlatformMetadata reduces it to the
// language and version pair.
func platformMetadata(config Config) string {
	components := []string{
		"language=go",
		"version=" + boundedPlatformComponent(Version),
	}
	if !config.omitPlatformMetadata {
		components = append(components,
			"os="+boundedPlatformComponent(runtime.GOOS),
			"arch="+boundedPlatformComponent(runtime.GOARCH),
			"runtime=go",
			"runtime_version="+boundedPlatformComponent(runtime.Version()),
		)
	}
	return strings.Join(components, ";")
}

// boundedPlatformComponent keeps one component printable, separator-free, and
// short. An empty or fully rejected component becomes "unknown" so the
// assembled value never contains an empty field.
func boundedPlatformComponent(value string) string {
	var builder strings.Builder
	for index := 0; index < len(value) && builder.Len() < maxPlatformComponentBytes; index++ {
		character := value[index]
		if character < 0x21 || character > 0x7e || character == ';' || character == '=' {
			continue
		}
		builder.WriteByte(character)
	}
	if builder.Len() == 0 {
		return "unknown"
	}
	return builder.String()
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
	// The process environment is never consulted here. FromEnvironment is the
	// only path that reads MINDCLADE_* configuration, and no credential is read
	// from the environment on any path.
	if config.Endpoint == "" {
		config.Endpoint = environmentEndpoints[config.Environment]
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
