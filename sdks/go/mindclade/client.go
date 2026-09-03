package mindclade

import (
	"context"
	"crypto/tls"
	"errors"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
)

const maxWireMessageBytes = 8 << 20

// Client owns a generated gRPC transport estate and ergonomic internal
// services. It is safe for concurrent use.
type Client struct {
	Admin       *AdminService
	Agents      *AgentService
	Training    *TrainingService
	Operations  *OperationService
	Artifacts   *ArtifactService
	Datasets    *DatasetService
	Evaluations *EvaluationService
	Experiments *ExperimentService
	Inference   *InferenceService
	Jobs        *JobService
	Models      *ModelService
	Policies    *PolicyService
	Runs        *RunService
	Workflows   *WorkflowService
	Approvals   *ApprovalService

	config    Config
	transport TransportClients
	conn      *grpc.ClientConn
	closeOnce sync.Once
	closeErr  error
	closeAuth func() error
}

// New configures secure generated gRPC clients and the handwritten ergonomic
// façade. The call performs credential discovery but does not require the
// endpoint to be reachable until the first RPC.
func New(options ...Option) (*Client, error) {
	config := defaultConfig()
	for _, option := range options {
		if option != nil {
			if err := option(&config); err != nil {
				return nil, err
			}
		}
	}
	if err := config.finalize(); err != nil {
		return nil, err
	}
	if config.workloadIdentity {
		provider, err := newWorkloadIdentityProvider(config.Audience, config.DefaultRPCTimeout)
		if err != nil {
			return nil, err
		}
		config.TokenProvider = provider
		config.ownedTokenProvider = true
	}

	dialOptions := []grpc.DialOption{
		grpc.WithDisableRetry(),
		grpc.WithUserAgent(config.UserAgent),
		grpc.WithUnaryInterceptor(unaryInterceptor(config)),
		grpc.WithStreamInterceptor(streamInterceptor(config)),
		grpc.WithDefaultCallOptions(
			grpc.MaxCallRecvMsgSize(maxWireMessageBytes),
			grpc.MaxCallSendMsgSize(maxWireMessageBytes),
		),
	}
	if config.insecureForTesting {
		dialOptions = append(dialOptions, grpc.WithTransportCredentials(insecure.NewCredentials()))
	} else {
		tlsConfig := config.TLSConfig
		if tlsConfig == nil {
			tlsConfig = &tls.Config{MinVersion: tls.VersionTLS13, ServerName: config.ServerName}
		} else {
			tlsConfig = tlsConfig.Clone()
			if tlsConfig.MinVersion < tls.VersionTLS12 {
				tlsConfig.MinVersion = tls.VersionTLS12
			}
			if config.ServerName != "" {
				tlsConfig.ServerName = config.ServerName
			}
		}
		dialOptions = append(
			dialOptions,
			grpc.WithTransportCredentials(credentials.NewTLS(tlsConfig)),
			grpc.WithPerRPCCredentials(bearerCredentials{provider: config.TokenProvider}),
		)
	}

	connection, err := grpc.NewClient(config.Endpoint, dialOptions...)
	if err != nil {
		closeOwnedTokenProvider(config)
		return nil, normalizeError(err)
	}
	client, err := newClient(config, newTransportClients(connection), connection)
	if err != nil {
		_ = connection.Close()
		closeOwnedTokenProvider(config)
		return nil, err
	}
	return client, nil
}

func closeOwnedTokenProvider(config Config) {
	if !config.ownedTokenProvider {
		return
	}
	if closer, ok := config.TokenProvider.(interface{ Close() error }); ok {
		_ = closer.Close()
	}
}

// NewWithTransportForTesting builds the same façade over generated client
// interfaces supplied by a hermetic fake or bufconn server. It never performs
// credential discovery or network I/O.
func NewWithTransportForTesting(transport TransportClients, options ...Option) (*Client, error) {
	config := defaultConfig()
	for _, option := range options {
		if option != nil {
			if err := option(&config); err != nil {
				return nil, err
			}
		}
	}
	config.Environment = Local
	config.Endpoint = "bufnet:1"
	config.TokenProvider = nil
	config.workloadIdentity = false
	config.insecureForTesting = true
	if err := config.finalize(); err != nil {
		return nil, err
	}
	return newClient(config, transport, nil)
}

func newClient(config Config, transport TransportClients, connection *grpc.ClientConn) (*Client, error) {
	if err := transport.validate(); err != nil {
		return nil, err
	}
	client := &Client{config: config, transport: transport, conn: connection}
	if config.ownedTokenProvider {
		if closer, ok := config.TokenProvider.(interface{ Close() error }); ok {
			client.closeAuth = closer.Close
		}
	}
	client.Admin = &AdminService{client: client, transport: transport.Admin}
	client.Agents = &AgentService{client: client, transport: transport.Agent}
	client.Artifacts = &ArtifactService{client: client, transport: transport.Artifact}
	client.Datasets = &DatasetService{client: client, transport: transport.Dataset}
	client.Evaluations = &EvaluationService{client: client, transport: transport.Evaluation}
	client.Experiments = &ExperimentService{client: client, transport: transport.Experiment}
	client.Inference = &InferenceService{client: client, transport: transport.Inference}
	client.Jobs = &JobService{client: client, transport: transport.Job}
	client.Models = &ModelService{client: client, transport: transport.Model}
	client.Operations = &OperationService{client: client, transport: transport.Operation}
	client.Policies = &PolicyService{client: client, transport: transport.Policy}
	client.Runs = &RunService{client: client, transport: transport.Run}
	client.Training = &TrainingService{client: client, transport: transport.Training}
	client.Workflows = &WorkflowService{client: client, transport: transport.Workflow}
	client.Approvals = &ApprovalService{client: client, transport: transport.Approval}
	return client, nil
}

// Transport returns the complete generated client estate. Prefer ergonomic
// services for common workflows; use this escape hatch only when a façade has
// not yet activated a domain RPC.
func (client *Client) Transport() TransportClients { return client.transport }

// Close releases the owned gRPC connection. Injected test transports do not
// own a connection and close as a no-op.
func (client *Client) Close() error {
	if client == nil {
		return nil
	}
	client.closeOnce.Do(func() {
		var connectionErr error
		if client.conn != nil {
			connectionErr = client.conn.Close()
		}
		var authErr error
		if client.closeAuth != nil {
			authErr = client.closeAuth()
		}
		client.closeErr = errors.Join(connectionErr, authErr)
	})
	return client.closeErr
}

func (client *Client) context(ctx context.Context, options ...RequestOption) (context.Context, requestMetadata, context.CancelFunc, error) {
	if ctx == nil {
		return nil, requestMetadata{}, nil, errors.New("mindclade: context cannot be nil")
	}
	if deadline, ok := ctx.Deadline(); !ok || time.Until(deadline) > client.config.DefaultRPCTimeout {
		bounded, cancel := context.WithTimeout(ctx, client.config.DefaultRPCTimeout)
		decorated, metadata, err := withRequestOptions(bounded, options...)
		return decorated, metadata, cancel, err
	}
	decorated, metadata, err := withRequestOptions(ctx, options...)
	return decorated, metadata, func() {}, err
}

func (client *Client) workflowMutationContext(ctx context.Context, commandKey string, requireLease bool, options ...RequestOption) (context.Context, requestMetadata, context.CancelFunc, error) {
	callContext, metadata, cancel, err := client.mutationContext(ctx, commandKey, options...)
	if err != nil {
		return nil, requestMetadata{}, cancel, err
	}
	if requireLease && metadata.leaseToken == "" {
		cancel()
		return nil, requestMetadata{}, func() {}, invalidArgument("workflow transition requires WithLeaseToken transport metadata")
	}
	return callContext, metadata, cancel, nil
}
