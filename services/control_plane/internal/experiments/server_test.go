package experiments

import (
	"context"
	"errors"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
	internalexperimentv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/experiment/v1"
)

type networkExperimentRepository struct {
	Repository
	mu         sync.Mutex
	experiment *experimentv1.Experiment
	keys       []string
}

func (repository *networkExperimentRepository) CreateExperiment(_ context.Context, identity Identity, command *experimentv1.CreateExperimentCommand, digest string, _ time.Time) (*experimentv1.Experiment, bool, error) {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if digest == "" || command.GetContext().GetIdempotencyKey() == "" {
		return nil, false, ErrInvalidArgument
	}
	repository.keys = append(repository.keys, command.GetContext().GetIdempotencyKey())
	repository.experiment = &experimentv1.Experiment{
		Name:        projectParent(identity) + "/experiments/" + command.GetExperimentId(),
		Revision:    1,
		Etag:        "sha256:" + strings.Repeat("a", 64),
		DisplayName: command.GetDisplayName(),
		Kind:        command.GetKind(),
		State:       experimentv1.ExperimentState_EXPERIMENT_STATE_DRAFT,
		TenantName:  "tenants/" + identity.TenantID,
		ProjectName: projectParent(identity),
	}
	return clone(repository.experiment), false, nil
}

func (repository *networkExperimentRepository) TransitionExperiment(_ context.Context, _ Identity, command *experimentv1.TransitionExperimentCommand, digest string, _ time.Time) (*experimentv1.Experiment, bool, error) {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if repository.experiment == nil || digest == "" || command.GetContext().GetIdempotencyKey() == "" {
		return nil, false, ErrInvalidArgument
	}
	repository.keys = append(repository.keys, command.GetContext().GetIdempotencyKey())
	repository.experiment.State = command.GetTargetState()
	repository.experiment.Revision++
	repository.experiment.Etag = "sha256:" + strings.Repeat("b", 64)
	return clone(repository.experiment), false, nil
}

type networkIdentityResolver struct {
	mu              sync.Mutex
	canonicalAuth   int
	idempotencyKeys []string
}

func (resolver *networkIdentityResolver) Resolve(ctx context.Context) (Identity, error) {
	requestMetadata, _ := metadata.FromIncomingContext(ctx)
	authorization := requestMetadata.Get("authorization")
	if len(authorization) != 1 || authorization[0] != "Bearer integration-token" {
		return Identity{}, ErrUnauthenticated
	}
	keys := requestMetadata.Get("idempotency-key")
	if len(keys) != 1 || keys[0] == "" {
		return Identity{}, ErrUnauthenticated
	}
	resolver.mu.Lock()
	resolver.canonicalAuth++
	resolver.idempotencyKeys = append(resolver.idempotencyKeys, keys[0])
	resolver.mu.Unlock()
	return Identity{TenantID: "tenant-a", ProjectID: "project-a", Principal: "principal-a"}, nil
}

func TestPaginationTokensAreScopedAndBounded(t *testing.T) {
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("experiment-page-key", 2)))
	if err != nil {
		t.Fatal(err)
	}
	token, err := codec.encode(pageToken{Kind: "experiments", Tenant: "tenant-a", Project: "project-a", Parent: "parent", Filter: "state=active", Order: "create_time desc,name desc", AfterTime: time.Now().UTC().Format(time.RFC3339Nano), AfterName: "name"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = codec.decode(token, pageToken{Kind: "experiments", Tenant: "tenant-b", Project: "project-a", Parent: "parent", Filter: "state=active", Order: "create_time desc,name desc"}); !errors.Is(err, ErrPermissionDenied) {
		t.Fatalf("cross-tenant page token error=%v", err)
	}
	if _, err = pageLimit(201); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("unbounded page size error=%v", err)
	}
}

func TestServerConstructionAndStatusMappingFailClosed(t *testing.T) {
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("experiment-page-key", 2)))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = NewServer(nil, nil, codec); err == nil {
		t.Fatal("server accepted missing production dependencies")
	}
	if status.Code(rpcError(ErrInvalidArgument)) != codes.InvalidArgument {
		t.Fatalf("status=%v error=%v", status.Code(err), err)
	}
	if status.Code(rpcError(ErrRevisionConflict)) != codes.FailedPrecondition {
		t.Fatalf("revision status=%v", status.Code(rpcError(ErrRevisionConflict)))
	}
}

func TestGeneratedClientExecutesAuthenticatedIdempotentLifecycleOverBufconn(t *testing.T) {
	repository := &networkExperimentRepository{}
	identities := &networkIdentityResolver{}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("experiment-network-key", 2)))
	if err != nil {
		t.Fatal(err)
	}
	service, err := NewServer(repository, identities, codec)
	if err != nil {
		t.Fatal(err)
	}
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	if err = Register(grpcServer, service); err != nil {
		t.Fatal(err)
	}
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() {
		grpcServer.Stop()
		_ = listener.Close()
	})
	connection, err := grpc.NewClient(
		"passthrough:///experiment-network-test",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) {
			return listener.Dial()
		}),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internalexperimentv1.NewExperimentServiceClient(connection)

	created := callCreateExperiment(t, client)
	transitioned := callTransitionExperiment(t, client, created)
	if transitioned.GetState() != experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE || transitioned.GetRevision() != 2 {
		t.Fatalf("transitioned experiment=%+v", transitioned)
	}
	repository.mu.Lock()
	repositoryKeys := append([]string(nil), repository.keys...)
	repository.mu.Unlock()
	identities.mu.Lock()
	transportKeys := append([]string(nil), identities.idempotencyKeys...)
	authenticatedCalls := identities.canonicalAuth
	identities.mu.Unlock()
	if authenticatedCalls != 2 || strings.Join(repositoryKeys, ",") != "experiment-create,experiment-transition" || strings.Join(transportKeys, ",") != "experiment-create,experiment-transition" {
		t.Fatalf("auth calls=%d repository keys=%v transport keys=%v", authenticatedCalls, repositoryKeys, transportKeys)
	}
}

func callCreateExperiment(t *testing.T, client internalexperimentv1.ExperimentServiceClient) *experimentv1.Experiment {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ctx = metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer integration-token", "idempotency-key", "experiment-create"))
	response, err := client.CreateExperiment(ctx, &internalexperimentv1.CreateExperimentRequest{Command: &experimentv1.CreateExperimentCommand{
		Context:      networkCommandContext("create-request", "experiment-create"),
		ExperimentId: "experiment-1",
		DisplayName:  "Networked experiment",
		Kind:         experimentv1.ExperimentKind_EXPERIMENT_KIND_SCIENTIFIC,
	}})
	if err != nil {
		t.Fatal(err)
	}
	return response.GetExperiment()
}

func callTransitionExperiment(t *testing.T, client internalexperimentv1.ExperimentServiceClient, created *experimentv1.Experiment) *experimentv1.Experiment {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ctx = metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer integration-token", "idempotency-key", "experiment-transition"))
	response, err := client.TransitionExperiment(ctx, &internalexperimentv1.TransitionExperimentRequest{Command: &experimentv1.TransitionExperimentCommand{
		Context: networkCommandContext("transition-request", "experiment-transition"),
		Experiment: &commonv1.ResourceRef{
			ResourceType:    "experiment",
			ResourceId:      "experiment-1",
			ResourceVersion: created.GetRevision(),
			Name:            created.GetName(),
			TenantId:        "tenant-a",
			ProjectId:       "project-a",
			Etag:            created.GetEtag(),
		},
		ExpectedState: experimentv1.ExperimentState_EXPERIMENT_STATE_DRAFT,
		TargetState:   experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE,
		Etag:          created.GetEtag(),
		ReasonCode:    "INTENT_APPROVED",
	}})
	if err != nil {
		t.Fatal(err)
	}
	return response.GetExperiment()
}

func networkCommandContext(requestID, idempotencyKey string) *commonv1.CommandContext {
	return &commonv1.CommandContext{
		RequestId:      requestID,
		IdempotencyKey: idempotencyKey,
		TenantId:       "tenant-a",
		ProjectId:      "project-a",
		PrincipalId:    "principal-a",
	}
}
