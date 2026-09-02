package mindclade

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const fixtureContent = "immutable recipe content"

var fixtureDigest = "sha256:667e46778d9240d0c39fe50c7860ba60e47c6088ed881c58abfdd7ed0e999d66"

type catalogServer struct {
	internalartifactv1.UnimplementedArtifactServiceServer
	mu      sync.Mutex
	upload  *internalartifactv1.ArtifactUploadSession
	content []byte
	begins  int
}

func (*catalogServer) ResolveArtifactAlias(context.Context, *internalartifactv1.ResolveArtifactAliasRequest) (*internalartifactv1.ResolveArtifactAliasResponse, error) {
	return &internalartifactv1.ResolveArtifactAliasResponse{Artifact: fixtureArtifact()}, nil
}

func (*catalogServer) GetArtifact(context.Context, *internalartifactv1.GetArtifactRequest) (*internalartifactv1.GetArtifactResponse, error) {
	return &internalartifactv1.GetArtifactResponse{Artifact: fixtureArtifact()}, nil
}

func (server *catalogServer) GetArtifactUpload(_ context.Context, request *internalartifactv1.GetArtifactUploadRequest) (*internalartifactv1.GetArtifactUploadResponse, error) {
	server.mu.Lock()
	defer server.mu.Unlock()
	if server.upload == nil || server.upload.GetName() != request.GetName() {
		return nil, status.Error(codes.NotFound, "upload not found")
	}
	return &internalartifactv1.GetArtifactUploadResponse{Upload: proto.Clone(server.upload).(*internalartifactv1.ArtifactUploadSession)}, nil
}

func (server *catalogServer) BeginArtifactUpload(_ context.Context, request *internalartifactv1.BeginArtifactUploadRequest) (*internalartifactv1.BeginArtifactUploadResponse, error) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.begins++
	if server.upload == nil {
		now := timestamppb.Now()
		server.upload = &internalartifactv1.ArtifactUploadSession{Name: request.GetParent() + "/artifactUploads/" + request.GetUploadId(), Artifact: proto.Clone(request.GetArtifact()).(*artifactv1.ArtifactRef), State: internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN, ExpireTime: request.GetExpireTime(), CreateTime: now, UpdateTime: now, Revision: 1, Etag: "upload-1"}
	}
	return &internalartifactv1.BeginArtifactUploadResponse{Upload: proto.Clone(server.upload).(*internalartifactv1.ArtifactUploadSession)}, nil
}

func (server *catalogServer) UploadArtifactChunk(_ context.Context, request *internalartifactv1.UploadArtifactChunkRequest) (*internalartifactv1.UploadArtifactChunkResponse, error) {
	server.mu.Lock()
	defer server.mu.Unlock()
	if server.upload == nil || request.GetOffset() != int64(len(server.content)) || request.GetChunkIndex() != server.upload.GetNextChunkIndex() || request.GetEtag() != server.upload.GetEtag() {
		return nil, status.Error(codes.Aborted, "stale upload")
	}
	server.content = append(server.content, request.GetData()...)
	server.upload.CommittedOffset = int64(len(server.content))
	server.upload.NextChunkIndex++
	server.upload.Revision++
	server.upload.Etag = "upload-next"
	return &internalartifactv1.UploadArtifactChunkResponse{Upload: proto.Clone(server.upload).(*internalartifactv1.ArtifactUploadSession)}, nil
}

func (server *catalogServer) FinalizeArtifactUpload(_ context.Context, request *internalartifactv1.FinalizeArtifactUploadRequest) (*internalartifactv1.FinalizeArtifactUploadResponse, error) {
	server.mu.Lock()
	defer server.mu.Unlock()
	if server.upload == nil || request.GetEtag() != server.upload.GetEtag() || int64(len(server.content)) != server.upload.GetArtifact().GetSizeBytes() {
		return nil, status.Error(codes.FailedPrecondition, "incomplete upload")
	}
	receipt := &internalartifactv1.ArtifactStagingReceipt{ReceiptDigest: "sha256:" + strings.Repeat("b", 64), Artifact: proto.Clone(server.upload.GetArtifact()).(*artifactv1.ArtifactRef), ExpireTime: request.GetReceiptExpireTime()}
	server.upload.State, server.upload.StagingReceipt = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_FINALIZED, receipt
	return &internalartifactv1.FinalizeArtifactUploadResponse{Upload: proto.Clone(server.upload).(*internalartifactv1.ArtifactUploadSession), StagingReceipt: proto.Clone(receipt).(*internalartifactv1.ArtifactStagingReceipt)}, nil
}

func (server *catalogServer) AbortArtifactUpload(_ context.Context, request *internalartifactv1.AbortArtifactUploadRequest) (*internalartifactv1.AbortArtifactUploadResponse, error) {
	server.mu.Lock()
	defer server.mu.Unlock()
	if server.upload == nil || request.GetEtag() != server.upload.GetEtag() || request.GetContext().GetCanonicalRequestDigest() == "" {
		return nil, status.Error(codes.Aborted, "stale upload")
	}
	server.upload.State = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_ABORTED
	server.upload.Revision++
	server.upload.Etag = "upload-aborted"
	return &internalartifactv1.AbortArtifactUploadResponse{Upload: proto.Clone(server.upload).(*internalartifactv1.ArtifactUploadSession)}, nil
}

func (server *catalogServer) QuarantineArtifactUpload(_ context.Context, request *internalartifactv1.QuarantineArtifactUploadRequest) (*internalartifactv1.QuarantineArtifactUploadResponse, error) {
	server.mu.Lock()
	defer server.mu.Unlock()
	if server.upload == nil || request.GetEtag() != server.upload.GetEtag() || request.GetContext().GetCanonicalRequestDigest() == "" {
		return nil, status.Error(codes.Aborted, "stale upload")
	}
	server.upload.State = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_QUARANTINED
	server.upload.Revision++
	server.upload.Etag = "upload-quarantined"
	return &internalartifactv1.QuarantineArtifactUploadResponse{Upload: proto.Clone(server.upload).(*internalartifactv1.ArtifactUploadSession)}, nil
}

func (server *catalogServer) CommitArtifact(_ context.Context, request *internalartifactv1.CommitArtifactRequest) (*internalartifactv1.CommitArtifactResponse, error) {
	return &internalartifactv1.CommitArtifactResponse{Artifact: proto.Clone(request.GetCommand().GetArtifact()).(*artifactv1.ArtifactRef)}, nil
}

func (server *catalogServer) DownloadArtifact(_ *internalartifactv1.DownloadArtifactRequest, stream grpc.ServerStreamingServer[internalartifactv1.DownloadArtifactResponse]) error {
	server.mu.Lock()
	content := append([]byte(nil), server.content...)
	server.mu.Unlock()
	if len(content) == 0 {
		content = []byte(fixtureContent)
	}
	for offset := 0; offset < len(content); offset += 5 {
		end := offset + 5
		if end > len(content) {
			end = len(content)
		}
		part := content[offset:end]
		digest := sha256.Sum256(part)
		if err := stream.Send(&internalartifactv1.DownloadArtifactResponse{Artifact: fixtureArtifact(), Offset: int64(offset), Data: part, ChunkDigest: "sha256:" + hex.EncodeToString(digest[:]), Complete: end == len(content)}); err != nil {
			return err
		}
	}
	return nil
}

type trainingServer struct {
	internaltrainingv1.UnimplementedTrainingServiceServer
	mu      sync.Mutex
	request *internaltrainingv1.CreateTrainingRunRequest
}

func (server *trainingServer) CreateTrainingRun(_ context.Context, request *internaltrainingv1.CreateTrainingRunRequest) (*internaltrainingv1.CreateTrainingRunResponse, error) {
	server.mu.Lock()
	server.request = proto.Clone(request).(*internaltrainingv1.CreateTrainingRunRequest)
	server.mu.Unlock()
	return &internaltrainingv1.CreateTrainingRunResponse{Operation: &jobv1.Operation{
		OperationId: "operations/operation-1",
		TenantId:    "tenant-a",
		ProjectId:   "project-a",
		JobId:       "jobs/job-1",
		State:       jobv1.OperationState_OPERATION_STATE_PENDING,
		Target:      resourceRef(Config{TenantID: "tenant-a", ProjectID: "project-a"}, "training_run", "trainingRuns/run-1"),
	}}, nil
}

type operationServer struct {
	internaljobv1.UnimplementedOperationServiceServer
	mu    sync.Mutex
	reads int
}

func (server *operationServer) GetOperation(context.Context, *internaljobv1.GetOperationRequest) (*internaljobv1.GetOperationResponse, error) {
	server.mu.Lock()
	defer server.mu.Unlock()
	server.reads++
	state := jobv1.OperationState_OPERATION_STATE_RUNNING
	done := false
	if server.reads > 1 {
		state = jobv1.OperationState_OPERATION_STATE_SUCCEEDED
		done = true
	}
	return &internaljobv1.GetOperationResponse{Operation: &jobv1.Operation{
		OperationId: "operations/operation-1",
		State:       state,
		Done:        done,
		Target:      resourceRef(Config{TenantID: "tenant-a", ProjectID: "project-a"}, "training_run", "trainingRuns/run-1"),
	}}, nil
}

func (server *operationServer) WatchOperation(_ *internaljobv1.WatchOperationRequest, stream grpc.ServerStreamingServer[internaljobv1.WatchOperationResponse]) error {
	for sequence, state := range []jobv1.OperationState{
		jobv1.OperationState_OPERATION_STATE_RUNNING,
		jobv1.OperationState_OPERATION_STATE_SUCCEEDED,
	} {
		if err := stream.Send(&internaljobv1.WatchOperationResponse{
			Sequence: uint64(sequence + 1),
			Operation: &jobv1.Operation{
				OperationId: "operations/operation-1",
				State:       state,
				Done:        state == jobv1.OperationState_OPERATION_STATE_SUCCEEDED,
			},
		}); err != nil {
			return err
		}
	}
	return nil
}

func TestTrainingSubmitUsesGeneratedContracts(t *testing.T) {
	client, training, _ := testClient(t)
	operation, err := client.Training.Submit(context.Background(), TrainingJob{
		Model:          Model("nova-1"),
		Dataset:        Dataset("datasets/pdb-2026-08"),
		Recipe:         Recipe("pretrain-v4"),
		IdempotencyKey: "submission-1",
	})
	if err != nil {
		t.Fatalf("submit: %v", err)
	}
	if operation.GetTarget().GetName() != "trainingRuns/run-1" {
		t.Fatalf("operation target = %v", operation.GetTarget())
	}
	training.mu.Lock()
	request := training.request
	training.mu.Unlock()
	command := request.GetCommand()
	if command == nil || command.GetContext() == nil || !isSHA256Digest(command.GetContext().GetCanonicalRequestDigest()) {
		t.Fatalf("generated command context = %v", command)
	}
	if command.GetContext().GetIdempotencyKey() != "submission-1" || command.GetProject().GetTenantId() != "tenant-a" {
		t.Fatalf("generated command identity = %v", command)
	}
	if !proto.Equal(command.GetTrainingRecipe(), fixtureArtifact()) {
		t.Fatalf("resolved generated ArtifactRef = %v", command.GetTrainingRecipe())
	}
}

func TestOperationWaitAndWatch(t *testing.T) {
	client, _, _ := testClient(t)
	context, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	operation, err := client.Operations.Wait(context, "operations/operation-1", WaitOptions{PollInterval: time.Millisecond})
	if err != nil || !operation.GetDone() {
		t.Fatalf("wait: operation=%v err=%v", operation, err)
	}
	watcher, err := client.Operations.Watch(context, "operations/operation-1", 0)
	if err != nil {
		t.Fatalf("watch: %v", err)
	}
	defer watcher.Close()
	first, err := watcher.Recv()
	if err != nil || first.GetSequence() != 1 {
		t.Fatalf("first watch event: response=%v err=%v", first, err)
	}
	second, err := watcher.Recv()
	if err != nil || second.GetSequence() != 2 || !second.GetOperation().GetDone() {
		t.Fatalf("terminal watch event: response=%v err=%v", second, err)
	}
	if _, err = watcher.Recv(); !errors.Is(err, io.EOF) {
		t.Fatalf("terminal watcher must end with EOF: %v", err)
	}
}

func TestArtifactTransferVerifiesContent(t *testing.T) {
	client, _, _ := testClient(t)
	var destination bytes.Buffer
	if err := client.Artifacts.Download(context.Background(), fixtureArtifact(), &destination); err != nil {
		t.Fatalf("download: %v", err)
	}
	if destination.String() != fixtureContent {
		t.Fatalf("downloaded %q", destination.String())
	}
	receipt, err := client.Artifacts.Upload(context.Background(), fixtureArtifact(), strings.NewReader(fixtureContent), ArtifactUploadOptions{UploadID: "upload-sdk", ChunkBytes: 7})
	if err != nil || receipt.GetArtifact().GetDigest() != fixtureDigest {
		t.Fatalf("upload: receipt=%v err=%v", receipt, err)
	}
	uploaded, err := client.Artifacts.Commit(context.Background(), receipt)
	if err != nil || uploaded.GetDigest() != fixtureDigest {
		t.Fatalf("commit: artifact=%v err=%v", uploaded, err)
	}
	corrupt := fixtureArtifact()
	corrupt.Digest = "sha256:" + strings.Repeat("0", 64)
	if err = client.Artifacts.Download(context.Background(), corrupt, io.Discard); err == nil {
		t.Fatal("corrupt content was accepted")
	}
}

func TestArtifactUploadResumesAcrossFreshClientWithoutExpiryDigestConflict(t *testing.T) {
	client, _, catalog := testClient(t)
	partial := fixtureContent[:7]
	if _, err := client.Artifacts.Upload(context.Background(), fixtureArtifact(), strings.NewReader(partial), ArtifactUploadOptions{UploadID: "upload-process-boundary", ChunkBytes: len(partial)}); err == nil {
		t.Fatal("partial upload unexpectedly finalized")
	}
	catalog.mu.Lock()
	if catalog.upload.GetCommittedOffset() != int64(len(partial)) || catalog.begins != 1 {
		catalog.mu.Unlock()
		t.Fatalf("partial durable state = upload=%v begins=%d", catalog.upload, catalog.begins)
	}
	catalog.mu.Unlock()

	fresh, err := NewWithTransportForTesting(
		client.transport,
		WithTenantProject("tenant-a", "project-a"),
		WithPrincipal("principal-a"),
		WithPollInterval(time.Millisecond),
	)
	if err != nil {
		t.Fatalf("new fresh client: %v", err)
	}
	receipt, err := fresh.Artifacts.Upload(context.Background(), fixtureArtifact(), strings.NewReader(fixtureContent), ArtifactUploadOptions{UploadID: "upload-process-boundary", ChunkBytes: len(partial)})
	if err != nil || receipt.GetArtifact().GetDigest() != fixtureDigest {
		t.Fatalf("resumed upload: receipt=%v err=%v", receipt, err)
	}
	catalog.mu.Lock()
	defer catalog.mu.Unlock()
	if catalog.begins != 1 {
		t.Fatalf("fresh client issued a second BeginArtifactUpload: %d", catalog.begins)
	}
}

func TestArtifactUploadStatusAbortAndQuarantineUseGeneratedLifecycle(t *testing.T) {
	client, _, catalog := testClient(t)
	catalog.mu.Lock()
	now := timestamppb.Now()
	catalog.upload = &internalartifactv1.ArtifactUploadSession{Name: "tenants/tenant-a/projects/project-a/artifactUploads/terminal-1", Artifact: fixtureArtifact(), State: internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN, CreateTime: now, UpdateTime: now, Revision: 1, Etag: "upload-open"}
	catalog.mu.Unlock()
	statusValue, err := client.Artifacts.GetUpload(context.Background(), catalog.upload.GetName())
	if err != nil || statusValue.GetState() != internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN {
		t.Fatalf("get upload: status=%v err=%v", statusValue, err)
	}
	aborted, err := client.Artifacts.AbortUpload(context.Background(), statusValue.GetName(), statusValue.GetEtag(), "CLIENT_CANCELLED")
	if err != nil || aborted.GetState() != internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_ABORTED {
		t.Fatalf("abort upload: status=%v err=%v", aborted, err)
	}
	catalog.mu.Lock()
	catalog.upload.State = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN
	catalog.upload.Etag = "upload-open-again"
	catalog.mu.Unlock()
	quarantined, err := client.Artifacts.QuarantineUpload(context.Background(), statusValue.GetName(), "upload-open-again", "DIGEST_MISMATCH")
	if err != nil || quarantined.GetState() != internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_QUARANTINED {
		t.Fatalf("quarantine upload: status=%v err=%v", quarantined, err)
	}
}

func TestConfigFailsClosed(t *testing.T) {
	if _, err := New(WithEnvironment(Production), WithInsecureTransportForTesting()); err == nil {
		t.Fatal("production insecure transport was accepted")
	}
	if _, err := New(WithEnvironment(Local), WithEndpoint("example.com:80"), WithInsecureTransportForTesting()); err == nil {
		t.Fatal("non-loopback insecure transport was accepted")
	}
	credentials := bearerCredentials{provider: staticTokenProvider{Token{AccessToken: "expired", Expiry: time.Now().Add(-time.Minute)}}}
	if _, err := credentials.GetRequestMetadata(context.Background()); err == nil {
		t.Fatal("expired token was accepted")
	}
	longLived := bearerCredentials{provider: staticTokenProvider{Token{AccessToken: "long-lived", Expiry: time.Now().Add(24 * time.Hour)}}}
	if _, err := longLived.GetRequestMetadata(context.Background()); err == nil {
		t.Fatal("long-lived token was accepted")
	}
	if _, err := New(
		WithEnvironment(Development),
		WithEndpoint("control-plane.example:443/path"),
		WithTenantProject("tenant-a", "project-a"),
		WithPrincipal("principal-a"),
		WithTokenProvider(staticTokenProvider{Token{AccessToken: "token", Expiry: time.Now().Add(time.Hour)}}),
	); err == nil {
		t.Fatal("endpoint path was accepted")
	}
	if _, err := NewWithTransportForTesting(
		TransportClients{},
		WithTenantProject("tenant\nforged", "project-a"),
		WithPrincipal("principal-a"),
	); err == nil {
		t.Fatal("metadata injection was accepted")
	}
}

func TestErrorsAndCredentialFailuresDoNotExposeProviderPayloads(t *testing.T) {
	const secret = "secret-provider-payload"
	credentials := bearerCredentials{provider: failingTokenProvider{err: errors.New(secret)}}
	_, err := credentials.GetRequestMetadata(context.Background())
	if err == nil || strings.Contains(err.Error(), secret) || errors.Unwrap(err) != nil {
		t.Fatalf("credential error was not sanitized: %#v", err)
	}

	remote := enrichError(
		status.Error(codes.Unavailable, secret),
		map[string][]string{
			"x-request-id":   {strings.Repeat("x", 257)},
			"retry-after-ms": {"999999999999999999"},
		},
	)
	var sdkError *Error
	if !errors.As(remote, &sdkError) || strings.Contains(remote.Error(), secret) || sdkError.RequestID != "" || sdkError.RetryAfter != 0 || errors.Unwrap(remote) != nil {
		t.Fatalf("remote error was not bounded and sanitized: %#v", remote)
	}
}

func TestObserverPanicsCannotChangeRPCOutcome(t *testing.T) {
	config := defaultConfig()
	config.Observer = panicObserver{}
	interceptor := unaryInterceptor(config)
	err := interceptor(context.Background(), "/mindclade.internal.job.v1.OperationService/GetOperation", nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error { return nil },
	)
	if err != nil {
		t.Fatalf("observer panic changed RPC outcome: %v", err)
	}
}

func TestUnaryRetryIsBoundedAndIdempotent(t *testing.T) {
	config := defaultConfig()
	config.MaxAttempts = 3
	config.RetryBaseDelay = time.Nanosecond
	config.RetryMaxDelay = time.Nanosecond
	interceptor := unaryInterceptor(config)
	attempts := 0
	err := interceptor(context.Background(), "/mindclade.internal.job.v1.OperationService/GetOperation", nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
			attempts++
			if attempts < 3 {
				return status.Error(codes.Unavailable, "retry")
			}
			return nil
		},
	)
	if err != nil || attempts != 3 {
		t.Fatalf("retry result: attempts=%d err=%v", attempts, err)
	}
	attempts = 0
	err = interceptor(context.Background(), "/mindclade.internal.job.v1.RunService/CommitAttempt", nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
			attempts++
			return status.Error(codes.Unavailable, "do not retry unsafe call")
		},
	)
	if err == nil || attempts != 1 {
		t.Fatalf("unsafe retry result: attempts=%d err=%v", attempts, err)
	}
}

func testClient(t *testing.T) (*Client, *trainingServer, *catalogServer) {
	t.Helper()
	listener := bufconn.Listen(1 << 20)
	server := grpc.NewServer()
	training := &trainingServer{}
	catalog := &catalogServer{}
	internalartifactv1.RegisterArtifactServiceServer(server, catalog)
	internaltrainingv1.RegisterTrainingServiceServer(server, training)
	internaljobv1.RegisterOperationServiceServer(server, &operationServer{})
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(server.Stop)
	connection, err := grpc.NewClient(
		"passthrough:///bufnet",
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
	)
	if err != nil {
		t.Fatalf("dial bufconn: %v", err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client, err := NewWithTransportForTesting(
		newTransportClients(connection),
		WithTenantProject("tenant-a", "project-a"),
		WithPrincipal("principal-a"),
		WithPollInterval(time.Millisecond),
	)
	if err != nil {
		t.Fatalf("new test client: %v", err)
	}
	return client, training, catalog
}

type staticTokenProvider struct{ token Token }

func (provider staticTokenProvider) Token(context.Context) (Token, error) { return provider.token, nil }

type failingTokenProvider struct{ err error }

func (provider failingTokenProvider) Token(context.Context) (Token, error) {
	return Token{}, provider.err
}

type panicObserver struct{}

func (panicObserver) RPCStarted(string, int)                       { panic("observer failure") }
func (panicObserver) RPCFinished(string, int, time.Duration, Code) { panic("observer failure") }

func fixtureArtifact() *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: fixtureDigest, IntegrityDigest: fixtureDigest, SizeBytes: int64(len(fixtureContent)), MediaType: "application/json", ArtifactKind: "recipe", SchemaId: "recipe", SchemaVersion: "v1"}
}
