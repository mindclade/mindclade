package mindclade

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
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
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
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

type trainingAliasClient struct {
	internaltrainingv1.TrainingServiceClient
	operation *jobv1.Operation
	run       *trainingv1.TrainingRun
}

func (client *trainingAliasClient) CreateTrainingRun(_ context.Context, _ *internaltrainingv1.CreateTrainingRunRequest, _ ...grpc.CallOption) (*internaltrainingv1.CreateTrainingRunResponse, error) {
	return &internaltrainingv1.CreateTrainingRunResponse{Operation: client.operation}, nil
}

func (client *trainingAliasClient) ListTrainingRuns(_ context.Context, _ *internaltrainingv1.ListTrainingRunsRequest, _ ...grpc.CallOption) (*internaltrainingv1.ListTrainingRunsResponse, error) {
	return &internaltrainingv1.ListTrainingRunsResponse{TrainingRuns: []*trainingv1.TrainingRun{client.run}}, nil
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

type scriptedOperationClient struct {
	internaljobv1.OperationServiceClient
	stream grpc.ServerStreamingClient[internaljobv1.WatchOperationResponse]
}

func (client *scriptedOperationClient) WatchOperation(context.Context, *internaljobv1.WatchOperationRequest, ...grpc.CallOption) (grpc.ServerStreamingClient[internaljobv1.WatchOperationResponse], error) {
	return client.stream, nil
}

type scriptedOperationStream struct {
	grpc.ClientStream
	responses []*internaljobv1.WatchOperationResponse
}

func (stream *scriptedOperationStream) Recv() (*internaljobv1.WatchOperationResponse, error) {
	if len(stream.responses) == 0 {
		return nil, io.EOF
	}
	response := stream.responses[0]
	stream.responses = stream.responses[1:]
	return response, nil
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

func TestTrainingFacadeDetachesGeneratedTransportValues(t *testing.T) {
	client, _, _ := testClient(t)
	parent := projectName(client.config.TenantID, client.config.ProjectID)
	transport := &trainingAliasClient{
		operation: &jobv1.Operation{OperationId: parent + "/operations/op-alias", TenantId: client.config.TenantID, ProjectId: client.config.ProjectID, State: jobv1.OperationState_OPERATION_STATE_PENDING},
		run:       &trainingv1.TrainingRun{Name: parent + "/trainingRuns/run-alias", State: trainingv1.TrainingRunState_TRAINING_RUN_STATE_CREATED},
	}
	client.Training.transport = transport

	operation, err := client.Training.Submit(context.Background(), TrainingJob{
		Model:          Model("nova-1"),
		Dataset:        Dataset("datasets/pdb-2026-08"),
		Recipe:         Recipe("pretrain-v4"),
		IdempotencyKey: "alias-safety",
	})
	if err != nil {
		t.Fatalf("Submit: %v", err)
	}
	operation.Etag = "caller-mutated"
	if transport.operation.GetEtag() == operation.GetEtag() {
		t.Fatal("Submit exposed transport-owned generated message memory")
	}

	page, err := client.Training.List(context.Background(), 20, "")
	if err != nil || len(page.Runs) != 1 {
		t.Fatalf("List: page=%v err=%v", page, err)
	}
	page.Runs[0].Etag = "caller-mutated"
	if transport.run.GetEtag() == page.Runs[0].GetEtag() {
		t.Fatal("List exposed transport-owned generated message memory")
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
	defer func() { _ = watcher.Close() }()
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

func TestOperationWatchRejectsMissingOrCrossResourceIdentity(t *testing.T) {
	client, _, _ := testClient(t)
	for _, operationID := range []string{"", "operations/wrong"} {
		client.Operations.transport = &scriptedOperationClient{stream: &scriptedOperationStream{
			responses: []*internaljobv1.WatchOperationResponse{{
				Sequence: 1,
				Operation: &jobv1.Operation{
					OperationId: operationID,
					State:       jobv1.OperationState_OPERATION_STATE_RUNNING,
				},
			}},
		}}
		watcher, err := client.Operations.Watch(context.Background(), "operations/expected", 0)
		if err != nil {
			t.Fatalf("Watch(%q): %v", operationID, err)
		}
		_, err = watcher.Recv()
		_ = watcher.Close()
		var sdkError *Error
		if !errors.As(err, &sdkError) || sdkError.Code != CodeDataLoss {
			t.Fatalf("Watch(%q) error = %#v, want data_loss", operationID, err)
		}
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

func TestArtifactDownloadFilePublishesAtomicallyWithoutClobbering(t *testing.T) {
	client, _, _ := testClient(t)
	directory := t.TempDir()
	destination := directory + "/artifact.bin"
	if err := client.Artifacts.DownloadFile(context.Background(), fixtureArtifact(), destination); err != nil {
		t.Fatalf("atomic download: %v", err)
	}
	content, err := os.ReadFile(destination)
	if err != nil || string(content) != fixtureContent {
		t.Fatalf("published content = %q, err=%v", content, err)
	}
	info, err := os.Stat(destination)
	if err != nil {
		t.Fatalf("published stat: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("published mode = %v", info.Mode().Perm())
	}
	if err = client.Artifacts.DownloadFile(context.Background(), fixtureArtifact(), destination); !hasErrorCode(err, CodeAlreadyExists) {
		t.Fatalf("existing destination was not protected: %v", err)
	}
	content, err = os.ReadFile(destination)
	if err != nil || string(content) != fixtureContent {
		t.Fatalf("existing destination changed: %q, err=%v", content, err)
	}

	corrupt := fixtureArtifact()
	corrupt.Digest = "sha256:" + strings.Repeat("0", 64)
	corruptDestination := directory + "/corrupt.bin"
	if err = client.Artifacts.DownloadFile(context.Background(), corrupt, corruptDestination); err == nil {
		t.Fatal("corrupt artifact was published")
	}
	if _, statErr := os.Stat(corruptDestination); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("corrupt destination exists: %v", statErr)
	}

	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	canceledDestination := directory + "/cancelled.bin"
	if err = client.Artifacts.DownloadFile(canceled, fixtureArtifact(), canceledDestination); !hasErrorCode(err, CodeCanceled) {
		t.Fatalf("cancelled download error = %v", err)
	}
	if _, statErr := os.Stat(canceledDestination); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("cancelled destination exists: %v", statErr)
	}

	raceDestination := directory + "/race.bin"
	start := make(chan struct{})
	results := make(chan error, 2)
	var writers sync.WaitGroup
	writers.Add(2)
	for range 2 {
		go func() {
			defer writers.Done()
			<-start
			results <- client.Artifacts.DownloadFile(context.Background(), fixtureArtifact(), raceDestination)
		}()
	}
	close(start)
	writers.Wait()
	close(results)
	successes, conflicts := 0, 0
	for result := range results {
		switch {
		case result == nil:
			successes++
		case hasErrorCode(result, CodeAlreadyExists):
			conflicts++
		default:
			t.Fatalf("racing download error = %v", result)
		}
	}
	if successes != 1 || conflicts != 1 {
		t.Fatalf("racing publication results: success=%d, already-exists=%d", successes, conflicts)
	}
	content, err = os.ReadFile(raceDestination)
	if err != nil || string(content) != fixtureContent {
		t.Fatalf("racing destination content = %q, err=%v", content, err)
	}

	staging := directory + "/.mindclade-download-commit-point"
	commitDestination := directory + "/commit-point.bin"
	if err = os.WriteFile(staging, []byte(fixtureContent), 0o600); err != nil {
		t.Fatal(err)
	}
	removeCalls, syncCalls := 0, 0
	err = publishArtifactFile(
		staging,
		commitDestination,
		directory,
		os.Link,
		func(string) error {
			removeCalls++
			return errors.New("simulated staging cleanup failure")
		},
		func(string) error {
			syncCalls++
			return errors.New("simulated directory sync failure")
		},
	)
	if err != nil {
		t.Fatalf("post-commit cleanup changed success to error: %v", err)
	}
	if removeCalls != 1 || syncCalls != 2 {
		t.Fatalf("post-commit cleanup calls: remove=%d sync=%d", removeCalls, syncCalls)
	}
	content, err = os.ReadFile(commitDestination)
	if err != nil || string(content) != fixtureContent {
		t.Fatalf("committed destination content = %q, err=%v", content, err)
	}
	if err = os.Remove(staging); err != nil {
		t.Fatal(err)
	}

	entries, err := os.ReadDir(directory)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".mindclade-download-") {
			t.Fatalf("temporary artifact file leaked: %s", entry.Name())
		}
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

func TestRetryPolicyHonorsBoundedServerHintAndRemoteDeadline(t *testing.T) {
	config := defaultConfig()
	config.RetryMaxDelay = 2 * time.Second
	if delay := retryDelayForError(config, 1, &Error{RetryAfter: 5 * time.Second}); delay != config.RetryMaxDelay {
		t.Fatalf("bounded retry delay = %s, want %s", delay, config.RetryMaxDelay)
	}
	if delay := retryDelayForError(config, 1, &Error{}); delay < 0 || delay > config.RetryBaseDelay {
		t.Fatalf("jittered retry delay outside policy: %s", delay)
	}
	if !retryableCode(codes.DeadlineExceeded) {
		t.Fatal("remote deadline exceeded was not retryable for a classified safe call")
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

func TestRawTransportCannotOverrideSDKIdentityOrInjectCredentials(t *testing.T) {
	config := defaultConfig()
	config.TenantID = "tenant-authoritative"
	config.ProjectID = "project-authoritative"
	config.PrincipalID = "principal-authoritative"
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs(
		"authorization", "Bearer caller-controlled",
		"proxy-authorization", "Basic caller-controlled",
		"cookie", "session=caller-controlled",
		"x-api-key", "caller-controlled",
		"x-mindclade-expected-tenant", "tenant-forged",
		"x-request-id", "request-forged",
		"x-custom-safe", "preserved",
	))
	ctx, _, err := withRequestOptions(
		ctx,
		WithRequestID("request-authoritative"),
		WithTraceID("trace-authoritative"),
		WithIdempotencyKey("idempotency-authoritative"),
	)
	if err != nil {
		t.Fatal(err)
	}
	ctx = attachRequestMetadata(ctx, config, "/mindclade.internal.job.v1.OperationService/GetOperation")
	values, ok := metadata.FromOutgoingContext(ctx)
	if !ok {
		t.Fatal("SDK metadata was not attached")
	}
	for _, key := range []string{"authorization", "proxy-authorization", "cookie", "x-api-key"} {
		if values.Get(key) != nil {
			t.Fatalf("caller credential metadata %q survived policy enforcement", key)
		}
	}
	for key, expected := range map[string]string{
		"x-custom-safe":                  "preserved",
		"x-mindclade-expected-tenant":    "tenant-authoritative",
		"x-mindclade-expected-project":   "project-authoritative",
		"x-mindclade-expected-principal": "principal-authoritative",
		"x-request-id":                   "request-authoritative",
		"x-trace-id":                     "trace-authoritative",
		"idempotency-key":                "idempotency-authoritative",
	} {
		actual := values.Get(key)
		if len(actual) != 1 || actual[0] != expected {
			t.Fatalf("metadata %q = %v, want exactly %q", key, actual, expected)
		}
	}
}

func TestCallIdentityIsValidatedBeforeTransport(t *testing.T) {
	for name, option := range map[string]RequestOption{
		"request":     WithRequestID(strings.Repeat("r", 257)),
		"trace":       WithTraceID("trace\nforged"),
		"idempotency": WithIdempotencyKey("idempotency\x00forged"),
	} {
		t.Run(name, func(t *testing.T) {
			if _, _, err := withRequestOptions(context.Background(), option); err == nil {
				t.Fatal("unsafe call identity was accepted")
			}
		})
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

func TestRawUnaryDeadlineIsBoundedBySDKPolicy(t *testing.T) {
	config := defaultConfig()
	config.DefaultRPCTimeout = time.Second
	interceptor := unaryInterceptor(config)
	ctx, cancel := context.WithTimeout(context.Background(), time.Hour)
	defer cancel()
	err := interceptor(ctx, "/mindclade.internal.job.v1.OperationService/GetOperation", nil, nil, nil,
		func(callContext context.Context, _ string, _, _ any, _ *grpc.ClientConn, _ ...grpc.CallOption) error {
			deadline, ok := callContext.Deadline()
			if !ok || time.Until(deadline) > config.DefaultRPCTimeout {
				t.Fatalf("raw deadline was not bounded: %v", deadline)
			}
			return nil
		},
	)
	if err != nil {
		t.Fatal(err)
	}
}

func TestRawStreamDeadlineIsBoundedBySDKPolicy(t *testing.T) {
	config := defaultConfig()
	config.DefaultRPCTimeout = time.Second
	interceptor := streamInterceptor(config)
	description := &internaljobv1.OperationService_ServiceDesc.Streams[0]
	assertDeadline := func(ctx context.Context, wantMaximum, wantMinimum time.Duration) {
		t.Helper()
		stream, err := interceptor(ctx, description, nil, "/mindclade.internal.job.v1.OperationService/WatchOperation",
			func(callContext context.Context, _ *grpc.StreamDesc, _ *grpc.ClientConn, _ string, _ ...grpc.CallOption) (grpc.ClientStream, error) {
				deadline, ok := callContext.Deadline()
				if !ok {
					t.Fatal("stream call has no deadline")
				}
				remaining := time.Until(deadline)
				if remaining > wantMaximum || remaining < wantMinimum {
					t.Fatalf("stream deadline remaining=%v, want within [%v, %v]", remaining, wantMinimum, wantMaximum)
				}
				return &deadlineClientStream{ctx: callContext}, nil
			},
		)
		if err != nil {
			t.Fatal(err)
		}
		if err = stream.RecvMsg(nil); !errors.Is(err, io.EOF) {
			t.Fatalf("stream terminal receive = %v, want EOF", err)
		}
	}

	assertDeadline(context.Background(), time.Second, 900*time.Millisecond)
	longContext, cancel := context.WithTimeout(context.Background(), time.Hour)
	defer cancel()
	assertDeadline(longContext, time.Second, 900*time.Millisecond)
}

func TestPaginatePreservesOpaqueTokensAndEnforcesBounds(t *testing.T) {
	seen := []string{}
	values := []int{}
	for value, err := range Paginate(
		context.Background(),
		" initial token ",
		PaginationLimits{},
		func(_ context.Context, token string) (Page[int], error) {
			seen = append(seen, token)
			if len(seen) == 1 {
				return Page[int]{Items: []int{1, 2}, NextPageToken: " next token "}, nil
			}
			return Page[int]{Items: []int{3}}, nil
		},
	) {
		if err != nil {
			t.Fatal(err)
		}
		values = append(values, value)
	}
	if got, want := strings.Join(seen, ","), " initial token , next token "; got != want {
		t.Fatalf("page tokens = %q, want %q", got, want)
	}
	if got, want := fmt.Sprint(values), "[1 2 3]"; got != want {
		t.Fatalf("values = %s, want %s", got, want)
	}

	var terminal error
	for _, err := range Paginate(
		context.Background(),
		"opaque",
		PaginationLimits{},
		func(_ context.Context, token string) (Page[int], error) {
			return Page[int]{Items: []int{1}, NextPageToken: token}, nil
		},
	) {
		terminal = err
	}
	var sdkError *Error
	if !errors.As(terminal, &sdkError) || sdkError.Code != CodeDataLoss {
		t.Fatalf("repeated-token error = %#v, want data_loss", terminal)
	}

	values = values[:0]
	terminal = nil
	for value, err := range Paginate(
		context.Background(),
		"",
		PaginationLimits{MaxPages: 2, MaxItems: 2},
		func(context.Context, string) (Page[int], error) {
			return Page[int]{Items: []int{1, 2, 3}, NextPageToken: "more"}, nil
		},
	) {
		if err != nil {
			terminal = err
			continue
		}
		values = append(values, value)
	}
	if fmt.Sprint(values) != "[1 2]" {
		t.Fatalf("bounded values = %v", values)
	}
	if !errors.As(terminal, &sdkError) || sdkError.Code != CodeResourceExhausted {
		t.Fatalf("budget error = %#v, want resource_exhausted", terminal)
	}
}

type deadlineClientStream struct {
	ctx context.Context
}

func (stream *deadlineClientStream) Header() (metadata.MD, error) { return nil, nil }
func (stream *deadlineClientStream) Trailer() metadata.MD         { return nil }
func (stream *deadlineClientStream) CloseSend() error             { return nil }
func (stream *deadlineClientStream) Context() context.Context     { return stream.ctx }
func (stream *deadlineClientStream) SendMsg(any) error            { return nil }
func (stream *deadlineClientStream) RecvMsg(any) error            { return io.EOF }

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
