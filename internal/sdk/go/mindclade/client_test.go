package mindclade

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"path"
	"runtime"
	"slices"
	"strconv"
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
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	inferencev1 "github.com/mindclade/mindclade/protocols/generated/go/inference/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
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
	content := readTempArtifactFile(t, destination)
	if string(content) != fixtureContent {
		t.Fatalf("published content = %q", content)
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
	content = readTempArtifactFile(t, destination)
	if string(content) != fixtureContent {
		t.Fatalf("existing destination changed: %q", content)
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
	content = readTempArtifactFile(t, raceDestination)
	if string(content) != fixtureContent {
		t.Fatalf("racing destination content = %q", content)
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
	content = readTempArtifactFile(t, commitDestination)
	if string(content) != fixtureContent {
		t.Fatalf("committed destination content = %q", content)
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
	ctx context.Context //nolint:containedctx // The generated gRPC stream test double must return the exact interceptor context.
}

func (stream *deadlineClientStream) Header() (metadata.MD, error) { return nil, nil }
func (stream *deadlineClientStream) Trailer() metadata.MD         { return nil }
func (stream *deadlineClientStream) CloseSend() error             { return nil }
func (stream *deadlineClientStream) Context() context.Context     { return stream.ctx }
func (stream *deadlineClientStream) SendMsg(any) error            { return nil }
func (stream *deadlineClientStream) RecvMsg(any) error            { return io.EOF }

func readTempArtifactFile(t *testing.T, path string) []byte {
	t.Helper()
	content, err := os.ReadFile(path) //nolint:gosec // All callers pass paths created beneath this test's t.TempDir.
	if err != nil {
		t.Fatalf("read temporary artifact file %q: %v", path, err)
	}
	return content
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

const safeUnaryMethod = "/mindclade.internal.job.v1.OperationService/GetOperation"

// scriptedTrailers writes the server trailers a scripted invoke wants the
// interceptor to observe, exactly as the transport would.
func scriptedTrailers(options []grpc.CallOption, trailers metadata.MD) {
	for _, option := range options {
		if trailer, ok := option.(grpc.TrailerCallOption); ok && trailer.TrailerAddr != nil {
			*trailer.TrailerAddr = trailers
		}
	}
}

func retryTestConfig(t *testing.T, jitter jitterSource) Config {
	t.Helper()
	config := defaultConfig()
	config.TenantID = "tenant-a"
	config.ProjectID = "project-a"
	config.PrincipalID = "principal-a"
	config.jitter = jitter
	return config
}

func TestRetryBudgetIsTotalAcrossAttemptsAndBackoff(t *testing.T) {
	config := retryTestConfig(t, func(bound int64) int64 { return bound })
	config.RetryBaseDelay = 20 * time.Millisecond
	config.RetryMaxDelay = 20 * time.Millisecond
	ctx, _, err := withRequestOptions(context.Background(), WithTimeout(50*time.Millisecond))
	if err != nil {
		t.Fatal(err)
	}
	attempts := 0
	started := time.Now()
	err = unaryInterceptor(config)(ctx, safeUnaryMethod, nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
			attempts++
			return status.Error(codes.Unavailable, "transport failure")
		},
	)
	elapsed := time.Since(started)
	if elapsed > time.Second {
		t.Fatalf("retry budget was not total: elapsed=%s", elapsed)
	}
	if attempts < 2 || attempts >= config.MaxAttempts {
		t.Fatalf("attempts = %d, want at least 2 and fewer than the configured %d", attempts, config.MaxAttempts)
	}
	var sdkError *Error
	if !errors.As(err, &sdkError) {
		t.Fatalf("terminal error was not an SDK error: %#v", err)
	}
	if sdkError.Attempts != attempts || sdkError.CumulativeDelay < config.RetryBaseDelay {
		t.Fatalf("retry outcome = attempts %d delay %s, want %d attempts and at least %s of backoff",
			sdkError.Attempts, sdkError.CumulativeDelay, attempts, config.RetryBaseDelay)
	}
	if sdkError.Code != CodeDeadlineExceeded {
		t.Fatalf("final cause = %s, want the exhausted budget", sdkError.Code)
	}
}

func TestJitterSourceIsInjectableAndFullRange(t *testing.T) {
	bounds := []int64{}
	config := retryTestConfig(t, func(bound int64) int64 {
		bounds = append(bounds, bound)
		return 0
	})
	if delay := retryDelay(config, 1); delay != 0 {
		t.Fatalf("floor of the full-jitter interval = %s, want 0", delay)
	}
	config.jitter = func(bound int64) int64 {
		bounds = append(bounds, bound)
		return bound
	}
	if delay := retryDelay(config, 1); delay != config.RetryBaseDelay {
		t.Fatalf("ceiling of the first interval = %s, want %s", delay, config.RetryBaseDelay)
	}
	if delay := retryDelay(config, 3); delay != 4*config.RetryBaseDelay {
		t.Fatalf("ceiling of the third interval = %s, want %s", delay, 4*config.RetryBaseDelay)
	}
	if delay := retryDelay(config, 1<<30); delay != config.RetryMaxDelay {
		t.Fatalf("saturated ceiling = %s, want the configured cap %s", delay, config.RetryMaxDelay)
	}
	want := []int64{
		int64(config.RetryBaseDelay),
		int64(config.RetryBaseDelay),
		int64(4 * config.RetryBaseDelay),
		int64(config.RetryMaxDelay),
	}
	if fmt.Sprint(bounds) != fmt.Sprint(want) {
		t.Fatalf("jitter bounds = %v, want %v", bounds, want)
	}
	if value := cryptographicJitter(0); value != 0 {
		t.Fatalf("default jitter of an empty interval = %d, want 0", value)
	}
	if value := cryptographicJitter(1000); value < 0 || value > 1000 {
		t.Fatalf("default jitter escaped its interval: %d", value)
	}
}

func TestRetryCountAndTimeoutMetadataAreSentEveryAttempt(t *testing.T) {
	config := retryTestConfig(t, func(bound int64) int64 { return bound })
	config.MaxAttempts = 3
	config.RetryBaseDelay = 10 * time.Millisecond
	config.RetryMaxDelay = 10 * time.Millisecond
	ctx, _, err := withRequestOptions(context.Background(), WithTimeout(2*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	counts := []string{}
	budgets := []int64{}
	err = unaryInterceptor(config)(ctx, safeUnaryMethod, nil, nil, nil,
		func(callContext context.Context, _ string, _, _ any, _ *grpc.ClientConn, _ ...grpc.CallOption) error {
			values, ok := metadata.FromOutgoingContext(callContext)
			if !ok {
				t.Fatal("attempt carried no outgoing metadata")
			}
			retryCount := values.Get("x-mindclade-retry-count")
			timeout := values.Get("x-mindclade-timeout-ms")
			if len(retryCount) != 1 || len(timeout) != 1 {
				t.Fatalf("per-attempt metadata = retry %v timeout %v, want exactly one value each", retryCount, timeout)
			}
			counts = append(counts, retryCount[0])
			remaining, parseErr := strconv.ParseInt(timeout[0], 10, 64)
			if parseErr != nil || remaining < 0 {
				t.Fatalf("remaining budget %q is not a non-negative integer of milliseconds", timeout[0])
			}
			budgets = append(budgets, remaining)
			return status.Error(codes.Unavailable, "transport failure")
		},
	)
	if err == nil {
		t.Fatal("exhausted retry policy returned success")
	}
	if got, want := strings.Join(counts, ","), "0,1,2"; got != want {
		t.Fatalf("retry counter sequence = %q, want %q", got, want)
	}
	for index := 1; index < len(budgets); index++ {
		if budgets[index] >= budgets[index-1] {
			t.Fatalf("remaining budget did not decrease across attempts: %v", budgets)
		}
	}
}

func TestServerRetryOverrideWorksInBothDirections(t *testing.T) {
	config := retryTestConfig(t, func(int64) int64 { return 0 })
	config.MaxAttempts = 3
	invokeWithTrailer := func(code codes.Code, trailer metadata.MD) int {
		t.Helper()
		attempts := 0
		_ = unaryInterceptor(config)(context.Background(), safeUnaryMethod, nil, nil, nil,
			func(_ context.Context, _ string, _, _ any, _ *grpc.ClientConn, options ...grpc.CallOption) error {
				attempts++
				scriptedTrailers(options, trailer)
				return status.Error(code, "scripted failure")
			},
		)
		return attempts
	}
	if attempts := invokeWithTrailer(codes.Unavailable, metadata.Pairs("x-mindclade-should-retry", "false")); attempts != 1 {
		t.Fatalf("server retry veto was ignored: attempts=%d", attempts)
	}
	if attempts := invokeWithTrailer(codes.FailedPrecondition, metadata.Pairs("x-mindclade-should-retry", "true")); attempts != config.MaxAttempts {
		t.Fatalf("server retry override was ignored: attempts=%d, want %d", attempts, config.MaxAttempts)
	}
	if attempts := invokeWithTrailer(codes.FailedPrecondition, metadata.Pairs("x-mindclade-should-retry", "maybe")); attempts != 1 {
		t.Fatalf("malformed retry override changed policy: attempts=%d", attempts)
	}
	if attempts := invokeWithTrailer(codes.FailedPrecondition, nil); attempts != 1 {
		t.Fatalf("terminal status was retried without a server override: attempts=%d", attempts)
	}
}

func TestRetryAfterTrailerIsClampedToMaxBackoff(t *testing.T) {
	config := defaultConfig()
	config.RetryMaxDelay = 2 * time.Second
	hinted := enrichError(status.Error(codes.Unavailable, "throttled"), metadata.Pairs("retry-after-ms", "60000"))
	if delay := retryDelayForError(config, 1, hinted); delay != config.RetryMaxDelay {
		t.Fatalf("server hint = %s, want it clamped to the %s cap", delay, config.RetryMaxDelay)
	}
	var sdkError *Error
	if !errors.As(hinted, &sdkError) || sdkError.RetryAfter != time.Minute {
		t.Fatalf("retry-after hint was not carried on the error: %#v", hinted)
	}
	if hint, ok := sdkError.RetryAfterHint(); !ok || hint != time.Minute {
		t.Fatalf("retry-after accessor = %s, %t", hint, ok)
	}
	bounded := enrichError(status.Error(codes.Unavailable, "throttled"), metadata.Pairs("retry-after-ms", "-1"))
	if !errors.As(bounded, &sdkError) || sdkError.RetryAfter != 0 {
		t.Fatalf("negative retry-after hint was accepted: %#v", bounded)
	}
}

func TestTypedErrorHierarchyPreservesErrorsAsAndIs(t *testing.T) {
	sanitized := func(code codes.Code, trailers metadata.MD) error {
		return enrichError(status.Error(code, "raw provider text"), trailers)
	}
	failedOperation := &OperationError{Operation: &jobv1.Operation{
		OperationId: "operations/failed-a",
		State:       jobv1.OperationState_OPERATION_STATE_FAILED,
		Done:        true,
		Etag:        "operation-etag-4",
	}}
	for name, test := range map[string]struct {
		err          error
		match        func(error) bool
		wantUnwrap   error
		wantSanitize bool
	}{
		"authentication":   {err: sanitized(codes.Unauthenticated, nil), match: func(err error) bool { var t *AuthenticationError; return errors.As(err, &t) }, wantSanitize: true},
		"authorization":    {err: sanitized(codes.PermissionDenied, nil), match: func(err error) bool { var t *AuthorizationError; return errors.As(err, &t) }, wantSanitize: true},
		"validation":       {err: sanitized(codes.InvalidArgument, nil), match: func(err error) bool { var t *ValidationError; return errors.As(err, &t) }, wantSanitize: true},
		"out_of_range":     {err: sanitized(codes.OutOfRange, nil), match: func(err error) bool { var t *ValidationError; return errors.As(err, &t) }, wantSanitize: true},
		"conflict":         {err: sanitized(codes.Aborted, nil), match: func(err error) bool { var t *ConflictError; return errors.As(err, &t) }, wantSanitize: true},
		"not_found":        {err: sanitized(codes.NotFound, nil), match: func(err error) bool { var t *NotFoundError; return errors.As(err, &t) }, wantSanitize: true},
		"rate_limit":       {err: sanitized(codes.ResourceExhausted, metadata.Pairs("retry-after-ms", "250")), match: func(err error) bool { var t *RateLimitError; return errors.As(err, &t) }, wantSanitize: true},
		"quota":            {err: sanitized(codes.ResourceExhausted, nil), match: func(err error) bool { var t *QuotaError; return errors.As(err, &t) }, wantSanitize: true},
		"retryable":        {err: sanitized(codes.Unavailable, nil), match: func(err error) bool { var t *RetryableServiceError; return errors.As(err, &t) }, wantSanitize: true},
		"transport":        {err: sanitized(codes.Unknown, nil), match: func(err error) bool { var t *TransportError; return errors.As(err, &t) }, wantSanitize: true},
		"cancelled":        {err: normalizeError(context.Canceled), match: func(err error) bool { var t *CancelledError; return errors.As(err, &t) }, wantUnwrap: context.Canceled},
		"deadline":         {err: normalizeError(context.DeadlineExceeded), match: func(err error) bool { var t *TransportError; return errors.As(err, &t) }, wantUnwrap: context.DeadlineExceeded},
		"operation_failed": {err: failedOperation, match: func(err error) bool { var t *OperationFailedError; return errors.As(err, &t) }},
	} {
		t.Run(name, func(t *testing.T) {
			if !test.match(test.err) {
				t.Fatalf("concrete type did not match: %#v", test.err)
			}
			var sdkError *Error
			if !errors.As(test.err, &sdkError) {
				t.Fatalf("base carrier was unreachable through errors.As: %#v", test.err)
			}
			var base MindcladeError
			if !errors.As(test.err, &base) || base.ErrorCode() != sdkError.Code {
				t.Fatalf("MindcladeError target did not match: %#v", test.err)
			}
			if test.wantSanitize {
				if strings.Contains(test.err.Error(), "raw provider text") {
					t.Fatalf("server text escaped into the message: %s", test.err.Error())
				}
				if errors.Unwrap(test.err) != nil {
					t.Fatalf("sanitized status exposed a cause chain: %#v", errors.Unwrap(test.err))
				}
			}
			if test.wantUnwrap != nil && !errors.Is(test.err, test.wantUnwrap) {
				t.Fatalf("errors.Is lost the cause %v", test.wantUnwrap)
			}
		})
	}
	var typedOperation *OperationError
	if !errors.As(failedOperation, &typedOperation) || typedOperation.Operation != failedOperation.Operation {
		t.Fatal("typed operation failure no longer preserves the generated operation")
	}
	var operationBase *Error
	if !errors.As(failedOperation, &operationBase) || operationBase.OperationID != "operations/failed-a" || operationBase.ConflictRevision != "operation-etag-4" {
		t.Fatalf("terminal operation identity was not projected: %#v", operationBase)
	}
}

func TestStructuredErrorDetailIsExposedThroughTypedFieldsOnly(t *testing.T) {
	const providerText = "ERROR: duplicate key value violates unique constraint (SQLSTATE 23505)"
	violations := make([]*commonv1.FieldViolation, 0, 40)
	for index := range 40 {
		violations = append(violations, &commonv1.FieldViolation{
			Field:       fmt.Sprintf("training_run.spec.field_%d", index),
			Description: "value is outside the accepted range",
		})
	}
	detail := &commonv1.ErrorDetail{
		Code:       commonv1.ErrorCode_ERROR_CODE_CONFLICT,
		Message:    providerText,
		RetryClass: commonv1.RetryClass_RETRY_CLASS_AFTER_RECONCILIATION,
		Subject: &commonv1.ResourceRef{
			ResourceType: "operation",
			ResourceId:   "op-a",
			Name:         "operations/op-a",
			Etag:         "operation-etag-9",
		},
		FieldViolations: violations,
		PreconditionViolations: []*commonv1.PreconditionViolation{
			{Type: "LEASE_EPOCH", Subject: "attempts/attempt-a", Description: "lease epoch was fenced"},
			{Type: "CONTROL", Subject: "binary\x00subject", Description: "line\nbreak"},
		},
		RetryAfter: durationpb.New(3 * time.Second),
		ErrorId:    "diagnostic-reference-a",
	}
	grpcStatus, err := status.New(codes.FailedPrecondition, providerText).WithDetails(detail)
	if err != nil {
		t.Fatal(err)
	}
	fence := &jobv1.LeaseFence{JobId: "jobs/job-a", RunId: "runs/run-a", AttemptId: "attempt-a", LeaseEpoch: 7, LeaseTokenDigest: "sha256:" + strings.Repeat("a", 64)}
	grpcStatus, err = grpcStatus.WithDetails(fence)
	if err != nil {
		t.Fatal(err)
	}

	failure := enrichError(grpcStatus.Err(), metadata.Pairs("x-request-id", "request-a", "x-trace-id", "trace-a"))
	if strings.Contains(failure.Error(), providerText) || strings.Contains(failure.Error(), "23505") {
		t.Fatalf("structured detail leaked provider text into the message: %s", failure.Error())
	}
	var conflict *ConflictError
	if !errors.As(failure, &conflict) {
		t.Fatalf("detail code did not refine the transport classification: %#v", failure)
	}
	var sdkError *Error
	if !errors.As(failure, &sdkError) {
		t.Fatal("base carrier was unreachable")
	}
	if sdkError.Code != CodeAborted || sdkError.Retry != RetryAfterReconciliation {
		t.Fatalf("classification = %s/%s, want aborted/after_reconciliation", sdkError.Code, sdkError.Retry)
	}
	if len(sdkError.FieldViolations) != maxErrorDetailViolations {
		t.Fatalf("field violations = %d, want the %d bound", len(sdkError.FieldViolations), maxErrorDetailViolations)
	}
	if sdkError.FieldViolations[0].GetField() != "training_run.spec.field_0" {
		t.Fatalf("field violation was not surfaced through the generated type: %#v", sdkError.FieldViolations[0])
	}
	if len(sdkError.PreconditionViolations) != 2 {
		t.Fatalf("precondition violations = %d, want 2", len(sdkError.PreconditionViolations))
	}
	if sdkError.PreconditionViolations[1].GetSubject() != "" || sdkError.PreconditionViolations[1].GetDescription() != "" {
		t.Fatalf("non-printable detail text was surfaced: %#v", sdkError.PreconditionViolations[1])
	}
	if sdkError.DiagnosticReference != "diagnostic-reference-a" || sdkError.ConflictRevision != "operation-etag-9" || sdkError.OperationID != "operations/op-a" {
		t.Fatalf("typed identity fields were not populated: %#v", sdkError)
	}
	if sdkError.RequestID != "request-a" || sdkError.TraceID != "trace-a" {
		t.Fatalf("request identity was not carried: %#v", sdkError)
	}
	if sdkError.RetryAfter != 3*time.Second {
		t.Fatalf("retry-after detail = %s, want 3s", sdkError.RetryAfter)
	}
	if sdkError.Fence.GetLeaseEpoch() != 7 || sdkError.Fence.GetAttemptId() != "attempt-a" {
		t.Fatalf("fence state was not surfaced: %#v", sdkError.Fence)
	}
	fields, preconditions := conflict.Violations()
	if len(fields) != maxErrorDetailViolations || len(preconditions) != 2 {
		t.Fatal("typed accessor did not mirror the carrier")
	}
	if conflict.Diagnostic() != "diagnostic-reference-a" || conflict.Revision() != "operation-etag-9" || conflict.OperationIdentity() != "operations/op-a" {
		t.Fatal("typed accessors did not mirror the carrier identity")
	}
	requestID, traceID := conflict.RequestIdentity()
	if requestID != "request-a" || traceID != "trace-a" {
		t.Fatalf("typed request identity = %q/%q", requestID, traceID)
	}
}

func TestExhaustedQuotaIsReportedAsBoundedTelemetry(t *testing.T) {
	detail := &commonv1.ErrorDetail{
		Code:       commonv1.ErrorCode_ERROR_CODE_RESOURCE_EXHAUSTED,
		RetryClass: commonv1.RetryClass_RETRY_CLASS_SAFE,
		Subject:    &commonv1.ResourceRef{ResourceType: "project", ResourceId: "project-a", Name: "projects/project-a"},
		PreconditionViolations: []*commonv1.PreconditionViolation{
			{Type: "QUOTA", Subject: "limit", Description: "1000"},
			{Type: "QUOTA", Subject: "remaining", Description: "0"},
			{Type: "QUOTA", Subject: "limit", Description: "not-a-number"},
		},
	}
	grpcStatus, err := status.New(codes.ResourceExhausted, "quota").WithDetails(detail)
	if err != nil {
		t.Fatal(err)
	}
	failure := enrichError(grpcStatus.Err(), metadata.Pairs("retry-after-ms", "500"))
	var limited *RateLimitError
	if !errors.As(failure, &limited) {
		t.Fatalf("a hinted exhaustion was not classified as rate limiting: %#v", failure)
	}
	quota := limited.QuotaTelemetry()
	if quota == nil || quota.Subject != "projects/project-a" || quota.Limit != 1000 || quota.Remaining != 0 {
		t.Fatalf("quota telemetry = %#v", quota)
	}
	if quota.ResetAt.IsZero() {
		t.Fatal("quota reset instant was not derived from the retry hint")
	}

	unhinted := enrichError(grpcStatus.Err(), nil)
	var exhausted *QuotaError
	if !errors.As(unhinted, &exhausted) {
		t.Fatalf("an unhinted exhaustion was not classified as a quota failure: %#v", unhinted)
	}
	unhintedQuota := exhausted.QuotaTelemetry()
	if unhintedQuota == nil || unhintedQuota.Limit != 1000 || !unhintedQuota.ResetAt.IsZero() {
		t.Fatalf("quota telemetry without a retry hint = %#v", unhintedQuota)
	}
}

func TestUnrecognizedRetryClassNeverAuthorizesRetry(t *testing.T) {
	detail := &commonv1.ErrorDetail{Code: commonv1.ErrorCode_ERROR_CODE_UNAVAILABLE, RetryClass: commonv1.RetryClass(9999)}
	grpcStatus, err := status.New(codes.Unavailable, "unavailable").WithDetails(detail)
	if err != nil {
		t.Fatal(err)
	}
	failure := enrichError(grpcStatus.Err(), nil)
	var sdkError *Error
	if !errors.As(failure, &sdkError) || sdkError.Retryability() != RetryNever {
		t.Fatalf("unrecognized retry class was not fail-closed: %#v", sdkError)
	}
	if retryableStatus(failure) {
		t.Fatal("unrecognized retry class authorized a retry")
	}

	config := retryTestConfig(t, func(int64) int64 { return 0 })
	attempts := 0
	_ = unaryInterceptor(config)(context.Background(), safeUnaryMethod, nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error {
			attempts++
			return grpcStatus.Err()
		},
	)
	if attempts != 1 {
		t.Fatalf("unrecognized retry class was retried: attempts=%d", attempts)
	}
}

// scriptedHeaders installs response headers on a scripted unary invocation, so
// a test can assert what the SDK does and does not surface from a server.
func scriptedHeaders(options []grpc.CallOption, headers metadata.MD) {
	for _, option := range options {
		if header, ok := option.(grpc.HeaderCallOption); ok && header.HeaderAddr != nil {
			*header.HeaderAddr = headers
		}
	}
}

func TestResponseMetadataIsCapturedOnSuccess(t *testing.T) {
	config := retryTestConfig(t, nil)
	var captured ResponseMetadata
	ctx, _, err := withRequestOptions(context.Background(),
		WithRequestID("request-success"),
		WithTraceID("trace-success"),
		WithResponseMetadata(&captured),
	)
	if err != nil {
		t.Fatal(err)
	}
	err = unaryInterceptor(config)(ctx, safeUnaryMethod, nil, nil, nil,
		func(_ context.Context, _ string, _, _ any, _ *grpc.ClientConn, options ...grpc.CallOption) error {
			scriptedHeaders(options, metadata.Pairs(
				"x-request-id", "request-success",
				"x-trace-id", "trace-success",
				"content-type", "application/grpc",
			))
			return nil
		},
	)
	if err != nil {
		t.Fatalf("successful call returned %v", err)
	}
	if captured.Status != "ok" {
		t.Fatalf("captured status = %q, want ok", captured.Status)
	}
	if captured.RequestID != "request-success" || captured.TraceID != "trace-success" {
		t.Fatalf("captured identity = %q/%q, want request-success/trace-success", captured.RequestID, captured.TraceID)
	}
	if got := captured.Metadata["content-type"]; len(got) != 1 || got[0] != "application/grpc" {
		t.Fatalf("allowlisted response metadata = %v, want the transport content type", captured.Metadata)
	}
}

func TestResponseMetadataFallsBackToSentIdentity(t *testing.T) {
	config := retryTestConfig(t, nil)
	var captured ResponseMetadata
	ctx, request, err := withRequestOptions(context.Background(), WithResponseMetadata(&captured))
	if err != nil {
		t.Fatal(err)
	}
	err = unaryInterceptor(config)(ctx, safeUnaryMethod, nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error { return nil },
	)
	if err != nil {
		t.Fatalf("successful call returned %v", err)
	}
	if captured.RequestID != request.requestID || captured.TraceID != request.traceID {
		t.Fatalf("captured identity = %q/%q, want the identity the SDK sent (%q/%q)",
			captured.RequestID, captured.TraceID, request.requestID, request.traceID)
	}
}

func TestResponseMetadataAllowlistExcludesCredentials(t *testing.T) {
	config := retryTestConfig(t, nil)
	var captured ResponseMetadata
	ctx, _, err := withRequestOptions(context.Background(), WithResponseMetadata(&captured))
	if err != nil {
		t.Fatal(err)
	}
	const credential = "Bearer scripted-credential"
	err = unaryInterceptor(config)(ctx, safeUnaryMethod, nil, nil, nil,
		func(_ context.Context, _ string, _, _ any, _ *grpc.ClientConn, options ...grpc.CallOption) error {
			scriptedHeaders(options, metadata.Pairs(
				"authorization", credential,
				"set-cookie", "session=scripted-credential",
				"x-mindclade-lease-token", "lease-scripted-credential",
				"x-session-token", "scripted-credential",
				"x-custom-unlisted", "harmless",
				"x-request-id", "request-allowlist",
			))
			return nil
		},
	)
	if err != nil {
		t.Fatalf("successful call returned %v", err)
	}
	if len(captured.Metadata) != 1 || len(captured.Metadata["x-request-id"]) != 1 {
		t.Fatalf("captured metadata = %v, want only the allowlisted request id", captured.Metadata)
	}
	for key, values := range captured.Metadata {
		if credentialBearingKey(key) {
			t.Fatalf("credential-bearing key %q was surfaced", key)
		}
		for _, value := range values {
			if strings.Contains(value, "scripted-credential") {
				t.Fatalf("credential value surfaced under %q: %q", key, value)
			}
		}
	}
	for _, key := range []string{"authorization", "set-cookie", "x-mindclade-lease-token", "x-session-token", "my-api-key", "refresh_token", "client-secret", "proxy-authorization"} {
		if !credentialBearingKey(key) {
			t.Fatalf("denylist did not classify %q as credential bearing", key)
		}
	}
	if credentialBearingKey("x-request-id") || credentialBearingKey("content-type") {
		t.Fatal("denylist rejected a key that carries no credential")
	}
}

func TestResponseMetadataIsCapturedOnFailure(t *testing.T) {
	config := retryTestConfig(t, func(int64) int64 { return 0 })
	config.MaxAttempts = 1
	var captured ResponseMetadata
	ctx, _, err := withRequestOptions(context.Background(), WithResponseMetadata(&captured))
	if err != nil {
		t.Fatal(err)
	}
	const raw = "relation \"runs\" does not exist (SQLSTATE 42P01)"
	err = unaryInterceptor(config)(ctx, safeUnaryMethod, nil, nil, nil,
		func(_ context.Context, _ string, _, _ any, _ *grpc.ClientConn, options ...grpc.CallOption) error {
			scriptedTrailers(options, metadata.Pairs("x-request-id", "request-failure", "grpc-message", raw))
			return status.Error(codes.Unavailable, raw)
		},
	)
	if err == nil {
		t.Fatal("failing call returned success")
	}
	if captured.Status != CodeUnavailable || captured.RequestID != "request-failure" {
		t.Fatalf("captured failure = %+v, want unavailable/request-failure", captured)
	}
	message := captured.Metadata["grpc-message"]
	if len(message) != 1 || message[0] != safeStatusMessage(codes.Unavailable) {
		t.Fatalf("grpc-message = %v, want the sanitized SDK text %q", message, safeStatusMessage(codes.Unavailable))
	}
	if strings.Contains(fmt.Sprint(captured), "SQLSTATE") {
		t.Fatalf("raw server prose reached the caller: %+v", captured)
	}
}

func TestResponseMetadataFromContextMirrorsTheOption(t *testing.T) {
	config := retryTestConfig(t, nil)
	base := CaptureResponseMetadata(context.Background())
	if _, ok := ResponseMetadataFromContext(base); ok {
		t.Fatal("a capture context reported metadata before any call completed")
	}
	if _, ok := ResponseMetadataFromContext(context.Background()); ok {
		t.Fatal("a plain context reported captured metadata")
	}
	ctx, _, err := withRequestOptions(base, WithRequestID("request-context"))
	if err != nil {
		t.Fatal(err)
	}
	err = unaryInterceptor(config)(ctx, safeUnaryMethod, nil, nil, nil,
		func(context.Context, string, any, any, *grpc.ClientConn, ...grpc.CallOption) error { return nil },
	)
	if err != nil {
		t.Fatalf("successful call returned %v", err)
	}
	captured, ok := ResponseMetadataFromContext(base)
	if !ok || captured.Status != "ok" || captured.RequestID != "request-context" {
		t.Fatalf("context accessor returned %+v ok=%v, want the completed call's metadata", captured, ok)
	}
}

// operationPageClient scripts a multi-page ListOperations collection so page
// traversal, budget enforcement, and per-page revalidation can be observed.
type operationPageClient struct {
	internaljobv1.OperationServiceClient
	pages    map[string]*internaljobv1.ListOperationsResponse
	requests []*internaljobv1.ListOperationsRequest
}

func (client *operationPageClient) ListOperations(_ context.Context, request *internaljobv1.ListOperationsRequest, _ ...grpc.CallOption) (*internaljobv1.ListOperationsResponse, error) {
	client.requests = append(client.requests, cloneGenerated(request))
	page, ok := client.pages[request.GetPage().GetPageToken()]
	if !ok {
		return nil, status.Error(codes.NotFound, "unknown page token")
	}
	return cloneGenerated(page), nil
}

func scriptedOperation(config Config, identifier string) *jobv1.Operation {
	return &jobv1.Operation{
		OperationId: projectName(config.TenantID, config.ProjectID) + "/operations/" + identifier,
		TenantId:    config.TenantID,
		ProjectId:   config.ProjectID,
		State:       jobv1.OperationState_OPERATION_STATE_RUNNING,
	}
}

func scriptedOperationPages(config Config) map[string]*internaljobv1.ListOperationsResponse {
	return map[string]*internaljobv1.ListOperationsResponse{
		"": {
			Operations: []*jobv1.Operation{scriptedOperation(config, "op-1"), scriptedOperation(config, "op-2")},
			Page:       &commonv1.PageResponse{NextPageToken: " cursor-two== "},
		},
		" cursor-two== ": {
			Operations: []*jobv1.Operation{scriptedOperation(config, "op-3")},
			Page:       &commonv1.PageResponse{NextPageToken: "cursor-three"},
		},
		"cursor-three": {
			Operations: []*jobv1.Operation{scriptedOperation(config, "op-4")},
		},
	}
}

func operationIdentifiers(operations []*jobv1.Operation) []string {
	identifiers := make([]string, 0, len(operations))
	for _, operation := range operations {
		identifiers = append(identifiers, path.Base(operation.GetOperationId()))
	}
	return identifiers
}

func TestListPagesTraverseEveryItemAndPreserveOpaqueCursors(t *testing.T) {
	client, _, _ := testClient(t)
	transport := &operationPageClient{pages: scriptedOperationPages(client.config)}
	client.Operations.transport = transport

	first, err := client.Operations.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if !first.HasNextPage() || first.PageMetadata().GetNextPageToken() != " cursor-two== " {
		t.Fatalf("first page cursor = %q, want the opaque token verbatim", first.PageMetadata().GetNextPageToken())
	}
	if got := operationIdentifiers(first.GetOperations()); strings.Join(got, ",") != "op-1,op-2" {
		t.Fatalf("first page items = %v, want op-1,op-2", got)
	}

	seen := []string{}
	for operation, iterErr := range first.All(context.Background()) {
		if iterErr != nil {
			t.Fatalf("All: %v", iterErr)
		}
		seen = append(seen, path.Base(operation.GetOperationId()))
	}
	if got, want := strings.Join(seen, ","), "op-1,op-2,op-3,op-4"; got != want {
		t.Fatalf("All yielded %q, want %q", got, want)
	}
	if len(transport.requests) != 3 {
		t.Fatalf("All issued %d list requests, want 3 (the first page is never refetched)", len(transport.requests))
	}
	repeated := []string{}
	for operation, iterErr := range first.All(context.Background()) {
		if iterErr != nil {
			t.Fatalf("second All: %v", iterErr)
		}
		repeated = append(repeated, path.Base(operation.GetOperationId()))
	}
	if strings.Join(repeated, ",") != strings.Join(seen, ",") {
		t.Fatalf("second traversal yielded %v, want the same items as the first (%v)", repeated, seen)
	}
	if transport.requests[1].GetPage().GetPageToken() != " cursor-two== " {
		t.Fatalf("traversal normalized an opaque cursor: %q", transport.requests[1].GetPage().GetPageToken())
	}

	walked := []string{}
	for page := first; page != nil; {
		walked = append(walked, operationIdentifiers(page.GetOperations())...)
		next, nextErr := page.NextPage(context.Background())
		if nextErr != nil {
			t.Fatalf("NextPage: %v", nextErr)
		}
		page = next
	}
	if got, want := strings.Join(walked, ","), "op-1,op-2,op-3,op-4"; got != want {
		t.Fatalf("NextPage walk yielded %q, want %q", got, want)
	}
}

func TestListPageTraversalEnforcesBudgetsAndRejectsCursorLoops(t *testing.T) {
	client, _, _ := testClient(t)
	client.Operations.transport = &operationPageClient{pages: scriptedOperationPages(client.config)}

	bounded, err := client.Operations.List(context.Background(), nil, WithPaginationLimits(PaginationLimits{MaxItems: 3}))
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	count, budgetErr := 0, error(nil)
	for _, iterErr := range bounded.All(context.Background()) {
		if iterErr != nil {
			budgetErr = iterErr
			break
		}
		count++
	}
	var sdkError *Error
	if !errors.As(budgetErr, &sdkError) || sdkError.Code != CodeResourceExhausted || count != 3 {
		t.Fatalf("item budget = %d items then %#v, want 3 items then resource exhaustion", count, budgetErr)
	}

	pageBounded, err := client.Operations.List(context.Background(), nil, WithPaginationLimits(PaginationLimits{MaxPages: 2}))
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	pages := 0
	for _, iterErr := range pageBounded.All(context.Background()) {
		if iterErr != nil {
			budgetErr = iterErr
			break
		}
		pages++
	}
	if !errors.As(budgetErr, &sdkError) || sdkError.Code != CodeResourceExhausted || pages != 3 {
		t.Fatalf("page budget = %d items then %#v, want the first two pages then resource exhaustion", pages, budgetErr)
	}

	looping := scriptedOperationPages(client.config)
	looping[" cursor-two== "] = &internaljobv1.ListOperationsResponse{
		Operations: []*jobv1.Operation{scriptedOperation(client.config, "op-3")},
		Page:       &commonv1.PageResponse{NextPageToken: " cursor-two== "},
	}
	client.Operations.transport = &operationPageClient{pages: looping}
	loop, err := client.Operations.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	loopErr := error(nil)
	for _, iterErr := range loop.All(context.Background()) {
		if iterErr != nil {
			loopErr = iterErr
			break
		}
	}
	if !errors.As(loopErr, &sdkError) || sdkError.Code != CodeDataLoss {
		t.Fatalf("repeated cursor produced %#v, want a data-loss failure", loopErr)
	}
}

func TestPageRetraversalRevalidatesScope(t *testing.T) {
	client, _, _ := testClient(t)
	pages := scriptedOperationPages(client.config)
	escaped := scriptedOperation(client.config, "op-3")
	escaped.ProjectId = "project-b"
	pages[" cursor-two== "] = &internaljobv1.ListOperationsResponse{Operations: []*jobv1.Operation{escaped}}
	client.Operations.transport = &operationPageClient{pages: pages}

	first, err := client.Operations.List(context.Background(), nil)
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	yielded, traversalErr := 0, error(nil)
	for _, iterErr := range first.All(context.Background()) {
		if iterErr != nil {
			traversalErr = iterErr
			break
		}
		yielded++
	}
	var sdkError *Error
	if !errors.As(traversalErr, &sdkError) || sdkError.Code != CodeDataLoss || yielded != 2 {
		t.Fatalf("cross-project page = %d items then %#v, want the first page then a data-loss failure", yielded, traversalErr)
	}
	if _, nextErr := first.NextPage(context.Background()); !errors.As(nextErr, &sdkError) || sdkError.Code != CodeDataLoss {
		t.Fatalf("NextPage bypassed scope validation: %#v", nextErr)
	}
}

func TestTrainingPageKeepsItsLegacySurfaceAndTraverses(t *testing.T) {
	client, _, _ := testClient(t)
	run := &trainingv1.TrainingRun{Name: projectName(client.config.TenantID, client.config.ProjectID) + "/trainingRuns/run-1"}
	client.Training.transport = &trainingAliasClient{run: run}

	page, err := client.Training.List(context.Background(), 20, "")
	if err != nil {
		t.Fatalf("Training.List: %v", err)
	}
	if len(page.Runs) != 1 || page.Runs[0].GetName() != run.GetName() {
		t.Fatalf("legacy Runs field = %v, want the single scripted run", page.Runs)
	}
	if len(page.Items()) != len(page.Runs) || page.HasNextPage() || page.NextPageToken != "" {
		t.Fatalf("training page traversal surface disagrees with its legacy fields: %+v", page)
	}
	next, err := page.NextPage(context.Background())
	if next != nil || err != nil {
		t.Fatalf("NextPage at end of collection = %v, %v, want nil, nil", next, err)
	}
	items := 0
	for _, iterErr := range page.All(context.Background()) {
		if iterErr != nil {
			t.Fatalf("All: %v", iterErr)
		}
		items++
	}
	if items != 1 {
		t.Fatalf("All yielded %d items, want 1", items)
	}
}

// capturingClientStream is a scripted server stream that reports the headers
// and trailers a real transport would, so stream response capture is testable
// without a live server.
type capturingClientStream struct {
	ctx       context.Context //nolint:containedctx // The generated gRPC stream test double must return the exact interceptor context.
	headers   metadata.MD
	trailers  metadata.MD
	remaining int
	failure   error
}

func (stream *capturingClientStream) Header() (metadata.MD, error) { return stream.headers, nil }
func (stream *capturingClientStream) Trailer() metadata.MD         { return stream.trailers }
func (stream *capturingClientStream) CloseSend() error             { return nil }
func (stream *capturingClientStream) Context() context.Context     { return stream.ctx }
func (stream *capturingClientStream) SendMsg(any) error            { return nil }

func (stream *capturingClientStream) RecvMsg(any) error {
	if stream.remaining > 0 {
		stream.remaining--
		return nil
	}
	if stream.failure != nil {
		return stream.failure
	}
	return io.EOF
}

func TestStreamResponseMetadataIsCapturedWithoutCredentials(t *testing.T) {
	config := defaultConfig()
	config.DefaultRPCTimeout = time.Second
	description := &internaljobv1.OperationService_ServiceDesc.Streams[0]
	headers := metadata.Pairs(
		"x-request-id", "request-stream",
		"authorization", "Bearer scripted-credential",
		"x-custom-unlisted", "harmless",
	)

	openStream := func(ctx context.Context, failure error) (grpc.ClientStream, error) {
		return streamInterceptor(config)(ctx, description, nil, "/mindclade.internal.job.v1.OperationService/WatchOperation",
			func(callContext context.Context, _ *grpc.StreamDesc, _ *grpc.ClientConn, _ string, _ ...grpc.CallOption) (grpc.ClientStream, error) {
				return &capturingClientStream{
					ctx:       callContext,
					headers:   headers,
					trailers:  metadata.Pairs("x-trace-id", "trace-stream"),
					remaining: 1,
					failure:   failure,
				}, nil
			},
		)
	}

	var captured ResponseMetadata
	ctx, _, err := withRequestOptions(context.Background(), WithResponseMetadata(&captured))
	if err != nil {
		t.Fatal(err)
	}
	stream, err := openStream(ctx, nil)
	if err != nil {
		t.Fatalf("open stream: %v", err)
	}
	if err = stream.RecvMsg(nil); err != nil {
		t.Fatalf("first receive: %v", err)
	}
	if captured.Status != "ok" || captured.RequestID != "request-stream" {
		t.Fatalf("first message capture = %+v, want the request id published early", captured)
	}
	if err = stream.RecvMsg(nil); !errors.Is(err, io.EOF) {
		t.Fatalf("terminal receive = %v, want EOF", err)
	}
	if captured.TraceID != "trace-stream" {
		t.Fatalf("terminal capture = %+v, want the trailer trace id", captured)
	}
	if len(captured.Metadata) != 2 || len(captured.Metadata["x-request-id"]) != 1 || len(captured.Metadata["x-trace-id"]) != 1 {
		t.Fatalf("stream metadata = %v, want only the allowlisted identity keys", captured.Metadata)
	}
	if strings.Contains(fmt.Sprint(captured), "scripted-credential") {
		t.Fatalf("stream capture surfaced a credential: %+v", captured)
	}

	var failed ResponseMetadata
	failedContext, _, err := withRequestOptions(context.Background(), WithResponseMetadata(&failed))
	if err != nil {
		t.Fatal(err)
	}
	stream, err = openStream(failedContext, status.Error(codes.Unavailable, "raw provider text"))
	if err != nil {
		t.Fatalf("open stream: %v", err)
	}
	if err = stream.RecvMsg(nil); err != nil {
		t.Fatalf("first receive: %v", err)
	}
	if err = stream.RecvMsg(nil); status.Code(err) != codes.Unavailable {
		t.Fatalf("terminal receive = %v, want unavailable", err)
	}
	if failed.Status != CodeUnavailable {
		t.Fatalf("stream failure status = %q, want unavailable", failed.Status)
	}
}

// scriptedWatchAttempt is one scripted server-side connection: either a refused
// open, or a stream that yields responses and then ends with endErr.
type scriptedWatchAttempt struct {
	openErr   error
	responses []*internaljobv1.WatchOperationResponse
	endErr    error
}

// resumableOperationClient scripts a watch that is interrupted and re-opened,
// recording every request so a test can assert the resume cursor the SDK sent.
type resumableOperationClient struct {
	internaljobv1.OperationServiceClient
	mu       sync.Mutex
	attempts []scriptedWatchAttempt
	requests []*internaljobv1.WatchOperationRequest
}

func (client *resumableOperationClient) WatchOperation(_ context.Context, request *internaljobv1.WatchOperationRequest, _ ...grpc.CallOption) (grpc.ServerStreamingClient[internaljobv1.WatchOperationResponse], error) {
	client.mu.Lock()
	defer client.mu.Unlock()
	client.requests = append(client.requests, cloneGenerated(request))
	if len(client.attempts) == 0 {
		return nil, status.Error(codes.Unavailable, "no scripted connection remains")
	}
	attempt := client.attempts[0]
	client.attempts = client.attempts[1:]
	if attempt.openErr != nil {
		return nil, attempt.openErr
	}
	return &scriptedResumableStream{responses: attempt.responses, endErr: attempt.endErr}, nil
}

func (client *resumableOperationClient) recorded() []*internaljobv1.WatchOperationRequest {
	client.mu.Lock()
	defer client.mu.Unlock()
	return append([]*internaljobv1.WatchOperationRequest(nil), client.requests...)
}

type scriptedResumableStream struct {
	grpc.ClientStream
	responses []*internaljobv1.WatchOperationResponse
	endErr    error
}

func (stream *scriptedResumableStream) Recv() (*internaljobv1.WatchOperationResponse, error) {
	if len(stream.responses) == 0 {
		if stream.endErr != nil {
			return nil, stream.endErr
		}
		return nil, io.EOF
	}
	response := stream.responses[0]
	stream.responses = stream.responses[1:]
	return response, nil
}

// watchedOperation builds one scripted watch response for the operation the
// watcher tests follow.
func watchedOperation(sequence uint64, done bool) *internaljobv1.WatchOperationResponse {
	state := jobv1.OperationState_OPERATION_STATE_RUNNING
	if done {
		state = jobv1.OperationState_OPERATION_STATE_SUCCEEDED
	}
	return &internaljobv1.WatchOperationResponse{
		Sequence:  sequence,
		Operation: &jobv1.Operation{OperationId: "operations/watched-1", State: state, Done: done},
	}
}

// instantRetryClient removes backoff from a test client so watcher reconnects
// are observable without sleeping. The jitter source is injected, never faked
// out of the code path, so the production wait arithmetic still runs.
func instantRetryClient(t *testing.T) *Client {
	t.Helper()
	client, _, _ := testClient(t)
	client.config.jitter = func(int64) int64 { return 0 }
	client.Operations.client = client
	return client
}

func TestGenericWatcherResumesFromLastAcknowledgedCursor(t *testing.T) {
	client := instantRetryClient(t)
	transport := &resumableOperationClient{attempts: []scriptedWatchAttempt{
		{responses: []*internaljobv1.WatchOperationResponse{watchedOperation(1, false), watchedOperation(2, false)}, endErr: status.Error(codes.Unavailable, "stream dropped")},
		{responses: []*internaljobv1.WatchOperationResponse{watchedOperation(3, true)}},
	}}
	client.Operations.transport = transport

	watcher, err := client.Operations.Watch(context.Background(), "operations/watched-1", 0)
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	defer func() { _ = watcher.Close() }()

	observed := []uint64{}
	for {
		response, receiveErr := watcher.Recv()
		if errors.Is(receiveErr, io.EOF) {
			break
		}
		if receiveErr != nil {
			t.Fatalf("Recv: %v", receiveErr)
		}
		observed = append(observed, response.GetSequence())
	}
	if len(observed) != 3 || observed[0] != 1 || observed[1] != 2 || observed[2] != 3 {
		t.Fatalf("observed sequences = %v, want 1, 2, 3 with nothing replayed or skipped", observed)
	}
	requests := transport.recorded()
	if len(requests) != 2 {
		t.Fatalf("watch connections = %d, want exactly one reconnect", len(requests))
	}
	if requests[0].GetAfterSequence() != 0 || requests[1].GetAfterSequence() != 2 {
		t.Fatalf("resume cursors = %d then %d, want 0 then the last acknowledged 2",
			requests[0].GetAfterSequence(), requests[1].GetAfterSequence())
	}
	if watcher.Cursor() != 3 {
		t.Fatalf("watcher cursor = %d, want the last acknowledged sequence 3", watcher.Cursor())
	}
}

func TestWatcherReconnectRespectsRemainingDeadline(t *testing.T) {
	client, _, _ := testClient(t)
	client.config.RetryBaseDelay = 500 * time.Millisecond
	client.config.RetryMaxDelay = 500 * time.Millisecond
	client.config.jitter = func(bound int64) int64 { return bound }
	transport := &resumableOperationClient{attempts: []scriptedWatchAttempt{
		{responses: []*internaljobv1.WatchOperationResponse{watchedOperation(1, false)}, endErr: status.Error(codes.Unavailable, "stream dropped")},
	}}
	client.Operations.transport = transport

	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	watcher, err := client.Operations.Watch(ctx, "operations/watched-1", 0)
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	defer func() { _ = watcher.Close() }()
	if _, err = watcher.Recv(); err != nil {
		t.Fatalf("first Recv: %v", err)
	}
	started := time.Now()
	_, err = watcher.Recv()
	elapsed := time.Since(started)
	var sdkError *Error
	if !errors.As(err, &sdkError) || sdkError.Code != CodeDeadlineExceeded {
		t.Fatalf("interrupted watch error = %#v, want the caller's deadline", err)
	}
	if elapsed > 100*time.Millisecond {
		t.Fatalf("watcher slept past its remaining deadline: elapsed=%s", elapsed)
	}
	if requests := transport.recorded(); len(requests) != 1 {
		t.Fatalf("watch connections = %d, want no reconnect outside the deadline", len(requests))
	}
}

func TestWatcherNextCurrentErrMirrorRecv(t *testing.T) {
	script := func() []scriptedWatchAttempt {
		return []scriptedWatchAttempt{{responses: []*internaljobv1.WatchOperationResponse{watchedOperation(1, false), watchedOperation(2, true)}}}
	}

	receiving := instantRetryClient(t)
	receiving.Operations.transport = &resumableOperationClient{attempts: script()}
	viaRecv, err := receiving.Operations.Watch(context.Background(), "operations/watched-1", 0)
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	defer func() { _ = viaRecv.Close() }()
	recvSequences := []uint64{}
	for {
		response, receiveErr := viaRecv.Recv()
		if errors.Is(receiveErr, io.EOF) {
			break
		}
		if receiveErr != nil {
			t.Fatalf("Recv: %v", receiveErr)
		}
		recvSequences = append(recvSequences, response.GetSequence())
	}

	iterating := instantRetryClient(t)
	iterating.Operations.transport = &resumableOperationClient{attempts: script()}
	viaNext, err := iterating.Operations.Watch(context.Background(), "operations/watched-1", 0)
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	defer func() { _ = viaNext.Close() }()
	nextSequences := []uint64{}
	for viaNext.Next() {
		nextSequences = append(nextSequences, viaNext.Current().GetSequence())
	}
	if viaNext.Err() != nil {
		t.Fatalf("Err at a clean end of stream = %v, want nil", viaNext.Err())
	}
	if len(recvSequences) != len(nextSequences) {
		t.Fatalf("Recv yielded %v but Next yielded %v", recvSequences, nextSequences)
	}
	for index := range recvSequences {
		if recvSequences[index] != nextSequences[index] {
			t.Fatalf("Recv yielded %v but Next yielded %v", recvSequences, nextSequences)
		}
	}
	if viaNext.Next() {
		t.Fatal("Next advanced past the end of a completed stream")
	}
}

func TestWatcherSurfacesTerminalFailureThroughBothSurfaces(t *testing.T) {
	failed := &internaljobv1.WatchOperationResponse{
		Sequence:  1,
		Operation: &jobv1.Operation{OperationId: "operations/watched-1", State: jobv1.OperationState_OPERATION_STATE_FAILED, Done: true},
	}
	client := instantRetryClient(t)
	client.Operations.transport = &resumableOperationClient{attempts: []scriptedWatchAttempt{{responses: []*internaljobv1.WatchOperationResponse{failed}}}}
	watcher, err := client.Operations.Watch(context.Background(), "operations/watched-1", 0)
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	defer func() { _ = watcher.Close() }()
	// A terminal failure ends the iteration, so Next reports false; the failed
	// revision is still readable through Current, exactly as Recv returns the
	// message alongside the error.
	if watcher.Next() {
		t.Fatal("Next continued past a terminal failure")
	}
	if watcher.Current().GetSequence() != 1 {
		t.Fatalf("Current sequence = %d, want the terminal revision", watcher.Current().GetSequence())
	}
	var operationError *OperationError
	if !errors.As(watcher.Err(), &operationError) || operationError.Operation.GetOperationId() != "operations/watched-1" {
		t.Fatalf("Err = %#v, want OperationError carrying the generated operation", watcher.Err())
	}
}

// lroRecordingOperationClient records the request identity every long-running
// verb carried into the transport, so a test can assert one logical call shares
// one identity across polls and reconnects.
type lroRecordingOperationClient struct {
	internaljobv1.OperationServiceClient
	mu         sync.Mutex
	identities []string
	requests   []*internaljobv1.WatchOperationRequest
}

func (client *lroRecordingOperationClient) record(ctx context.Context) {
	value, _ := ctx.Value(requestContextKey{}).(requestMetadata)
	client.mu.Lock()
	defer client.mu.Unlock()
	client.identities = append(client.identities, value.requestID)
}

func (client *lroRecordingOperationClient) GetOperation(ctx context.Context, _ *internaljobv1.GetOperationRequest, _ ...grpc.CallOption) (*internaljobv1.GetOperationResponse, error) {
	client.record(ctx)
	return &internaljobv1.GetOperationResponse{Operation: watchedOperation(1, true).GetOperation()}, nil
}

func (client *lroRecordingOperationClient) CancelOperation(ctx context.Context, _ *internaljobv1.CancelOperationRequest, _ ...grpc.CallOption) (*internaljobv1.CancelOperationResponse, error) {
	client.record(ctx)
	return &internaljobv1.CancelOperationResponse{Operation: watchedOperation(1, true).GetOperation()}, nil
}

func (client *lroRecordingOperationClient) WatchOperation(ctx context.Context, request *internaljobv1.WatchOperationRequest, _ ...grpc.CallOption) (grpc.ServerStreamingClient[internaljobv1.WatchOperationResponse], error) {
	client.record(ctx)
	client.mu.Lock()
	client.requests = append(client.requests, cloneGenerated(request))
	client.mu.Unlock()
	return &scriptedResumableStream{responses: []*internaljobv1.WatchOperationResponse{watchedOperation(1, true)}}, nil
}

func TestOperationLROVerbsAreUniform(t *testing.T) {
	const name = "operations/watched-1"
	const identity = "lro-request-identity"
	client := instantRetryClient(t)
	transport := &lroRecordingOperationClient{}
	client.Operations.transport = transport

	if _, err := client.Operations.Get(context.Background(), name, WithRequestID(identity)); err != nil {
		t.Fatalf("Get: %v", err)
	}
	if _, err := client.Operations.Wait(context.Background(), name, WaitOptions{PollInterval: time.Millisecond}, WithRequestID(identity)); err != nil {
		t.Fatalf("Wait: %v", err)
	}
	watching, err := client.Operations.Watch(context.Background(), name, 0, WithRequestID(identity))
	if err != nil {
		t.Fatalf("Watch: %v", err)
	}
	_ = watching.Close()
	resuming, err := client.Operations.ResumeWatch(context.Background(), name, 7, WithRequestID(identity))
	if err != nil {
		t.Fatalf("ResumeWatch: %v", err)
	}
	_ = resuming.Close()
	if _, err := client.Operations.Cancel(context.Background(), name, "etag-1", "operator request", WithRequestID(identity)); err != nil {
		t.Fatalf("Cancel: %v", err)
	}

	transport.mu.Lock()
	identities := append([]string(nil), transport.identities...)
	requests := append([]*internaljobv1.WatchOperationRequest(nil), transport.requests...)
	transport.mu.Unlock()
	if len(identities) != 5 {
		t.Fatalf("recorded %d transport calls, want one per long-running verb", len(identities))
	}
	for index, recorded := range identities {
		if recorded != identity {
			t.Fatalf("call %d carried request id %q, want the caller's %q", index, recorded, identity)
		}
	}
	if len(requests) != 2 || requests[0].GetAfterSequence() != 0 || requests[1].GetAfterSequence() != 7 {
		t.Fatalf("watch cursors = %v, want Watch from 0 and ResumeWatch from the named 7", requests)
	}
}

func TestFromEnvironmentIsTheOnlyEnvironmentPath(t *testing.T) {
	t.Setenv("MINDCLADE_ENVIRONMENT", "staging")
	t.Setenv("MINDCLADE_ENDPOINT", "control-plane.test:443")
	t.Setenv("MINDCLADE_TENANT_ID", "tenant-env")
	t.Setenv("MINDCLADE_PROJECT_ID", "project-env")
	t.Setenv("MINDCLADE_PRINCIPAL_ID", "principal-env")
	t.Setenv("MINDCLADE_AUDIENCE", "https://control-plane.test")
	t.Setenv("MINDCLADE_LOG", "debug")
	// No credential is ever read from the environment; these exist only to prove
	// the SDK ignores them.
	t.Setenv("MINDCLADE_TOKEN", "must-never-be-read")
	t.Setenv("MINDCLADE_API_KEY", "must-never-be-read")

	provider := WithTokenProvider(staticTokenProvider{Token{AccessToken: "token", Expiry: time.Now().Add(time.Hour)}})
	if _, err := New(provider); err == nil {
		t.Fatal("the ordinary constructor silently read the process environment")
	}
	if _, err := New(FromEnvironment()); err == nil {
		t.Fatal("a credential was accepted from the environment")
	}

	client, err := New(FromEnvironment(), provider)
	if err != nil {
		t.Fatalf("New(FromEnvironment()): %v", err)
	}
	defer func() { _ = client.Close() }()
	if client.config.Environment != Staging || client.config.Endpoint != "control-plane.test:443" {
		t.Fatalf("environment = %q endpoint = %q, want the values FromEnvironment read", client.config.Environment, client.config.Endpoint)
	}
	for label, pair := range map[string][2]string{
		"tenant":    {client.config.TenantID, "tenant-env"},
		"project":   {client.config.ProjectID, "project-env"},
		"principal": {client.config.PrincipalID, "principal-env"},
		"audience":  {client.config.Audience, "https://control-plane.test"},
	} {
		if pair[0] != pair[1] {
			t.Fatalf("%s = %q, want %q", label, pair[0], pair[1])
		}
	}
	if _, ok := client.config.Observer.(slogObserver); !ok {
		t.Fatalf("MINDCLADE_LOG did not install a structured logger: %T", client.config.Observer)
	}

	explicit := WithTenantProject("tenant-explicit", "project-explicit")
	for label, options := range map[string][]Option{
		"environment first": {FromEnvironment(), explicit, provider},
		"explicit first":    {explicit, FromEnvironment(), provider},
	} {
		configured, err := New(options...)
		if err != nil {
			t.Fatalf("New(%s): %v", label, err)
		}
		if configured.config.TenantID != "tenant-explicit" || configured.config.ProjectID != "project-explicit" {
			t.Fatalf("%s: explicit configuration lost to the environment: tenant=%q project=%q",
				label, configured.config.TenantID, configured.config.ProjectID)
		}
		_ = configured.Close()
	}
}

func TestCustomMetadataDenylistRejectsCredentialKeys(t *testing.T) {
	for _, key := range []string{
		"authorization", "proxy-authorization", "cookie", "set-cookie",
		"x-api-key", "x-session-token", "my-api-key", "x-mindclade-lease-token",
		"tenant-secret", "user-password", "service-credential",
		"x-request-id", "x-trace-id", "x-mindclade-sdk", "x-mindclade-expected-tenant",
		"grpc-timeout", "trace-bin", "x-bad key", "",
	} {
		pairs := map[string][]string{key: {"value"}}
		if _, _, err := withRequestOptions(context.Background(), WithMetadata(pairs)); err == nil {
			t.Fatalf("per-request metadata accepted the rejected key %q", key)
		}
		config := defaultConfig()
		if err := WithDefaultMetadata(pairs)(&config); err == nil {
			t.Fatalf("client-wide metadata accepted the rejected key %q", key)
		}
	}
	if _, _, err := withRequestOptions(context.Background(), WithMetadata(map[string][]string{"x-custom-safe": {strings.Repeat("v", 257)}})); err == nil {
		t.Fatal("an unbounded custom metadata value was accepted")
	}

	config := retryTestConfig(t, nil)
	if err := WithDefaultMetadata(map[string][]string{"x-client-tier": {"batch"}})(&config); err != nil {
		t.Fatalf("WithDefaultMetadata: %v", err)
	}
	ctx, _, err := withRequestOptions(context.Background(), WithMetadata(map[string][]string{"x-custom-safe": {"preserved"}}))
	if err != nil {
		t.Fatalf("WithMetadata: %v", err)
	}
	values, ok := metadata.FromOutgoingContext(attachRequestMetadata(ctx, config, safeUnaryMethod))
	if !ok {
		t.Fatal("SDK metadata was not attached")
	}
	for key, want := range map[string]string{"x-custom-safe": "preserved", "x-client-tier": "batch"} {
		if got := values.Get(key); len(got) != 1 || got[0] != want {
			t.Fatalf("custom metadata %q = %v, want exactly %q", key, got, want)
		}
	}
}

func TestPlatformMetadataIsStructuredAndBounded(t *testing.T) {
	config := retryTestConfig(t, nil)
	value := platformMetadata(config)
	for _, component := range []string{
		"language=go",
		"version=" + Version,
		"os=" + runtime.GOOS,
		"arch=" + runtime.GOARCH,
		"runtime=go",
		"runtime_version=" + runtime.Version(),
	} {
		if !strings.Contains(value, component) {
			t.Fatalf("x-mindclade-sdk %q is missing the component %q", value, component)
		}
	}
	if err := validateMetadataIdentifier("x-mindclade-sdk", value); err != nil {
		t.Fatalf("structured platform metadata is not a safe metadata identifier: %v", err)
	}
	ctx, _, err := withRequestOptions(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	values, _ := metadata.FromOutgoingContext(attachRequestMetadata(ctx, config, safeUnaryMethod))
	if got := values.Get("x-mindclade-sdk"); len(got) != 1 || got[0] != value {
		t.Fatalf("x-mindclade-sdk = %v, want exactly the structured value", got)
	}

	omitted := config
	if err := WithOmitPlatformMetadata()(&omitted); err != nil {
		t.Fatal(err)
	}
	if reduced := platformMetadata(omitted); reduced != "language=go;version="+Version {
		t.Fatalf("omitted platform metadata = %q, want only language and version", reduced)
	}
	if !strings.Contains(config.UserAgent, Version) {
		t.Fatalf("user agent %q does not carry the single source version %q", config.UserAgent, Version)
	}
}

// metadataRecordingOperationServer records the metadata a real gRPC transport
// delivered, so a test can compare it with what a caller interceptor observed.
type metadataRecordingOperationServer struct {
	internaljobv1.UnimplementedOperationServiceServer
	mu       sync.Mutex
	incoming metadata.MD
}

func (server *metadataRecordingOperationServer) GetOperation(ctx context.Context, _ *internaljobv1.GetOperationRequest) (*internaljobv1.GetOperationResponse, error) {
	received, _ := metadata.FromIncomingContext(ctx)
	server.mu.Lock()
	server.incoming = received.Copy()
	server.mu.Unlock()
	return &internaljobv1.GetOperationResponse{Operation: watchedOperation(1, true).GetOperation()}, nil
}

// plaintextBearerCredentials stands in for the SDK's own per-RPC credentials
// over a loopback test transport. Real credentials require transport security;
// this exists only to prove where in the stack a credential is injected.
type plaintextBearerCredentials struct{ token string }

func (credential plaintextBearerCredentials) GetRequestMetadata(context.Context, ...string) (map[string]string, error) {
	return map[string]string{"authorization": "Bearer " + credential.token}, nil
}

func (plaintextBearerCredentials) RequireTransportSecurity() bool { return false }

func TestCallerInterceptorCannotObserveCredentials(t *testing.T) {
	const secret = "caller-interceptor-must-not-see-this"
	listener := bufconn.Listen(1 << 20)
	server := grpc.NewServer()
	recorder := &metadataRecordingOperationServer{}
	internaljobv1.RegisterOperationServiceServer(server, recorder)
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(server.Stop)

	config := retryTestConfig(t, nil)
	var observed metadata.MD
	callerInterceptor := func(ctx context.Context, method string, request, response any, connection *grpc.ClientConn, invoke grpc.UnaryInvoker, options ...grpc.CallOption) error {
		observed, _ = metadata.FromOutgoingContext(ctx)
		return invoke(ctx, method, request, response, connection, options...)
	}
	if err := WithInterceptor(callerInterceptor)(&config); err != nil {
		t.Fatal(err)
	}
	connection, err := grpc.NewClient(
		"passthrough:///bufnet",
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithPerRPCCredentials(plaintextBearerCredentials{token: secret}),
		grpc.WithChainUnaryInterceptor(append([]grpc.UnaryClientInterceptor{unaryInterceptor(config)}, config.unaryInterceptors...)...),
	)
	if err != nil {
		t.Fatalf("dial bufconn: %v", err)
	}
	t.Cleanup(func() { _ = connection.Close() })

	response, err := internaljobv1.NewOperationServiceClient(connection).GetOperation(context.Background(), &internaljobv1.GetOperationRequest{Name: "operations/watched-1"})
	if err != nil || response.GetOperation() == nil {
		t.Fatalf("GetOperation: response=%v err=%v", response, err)
	}
	if observed == nil {
		t.Fatal("the caller interceptor never ran")
	}
	if values := observed.Get("authorization"); len(values) != 0 {
		t.Fatalf("the caller interceptor observed a credential: %v", values)
	}
	for _, values := range observed {
		for _, value := range values {
			if strings.Contains(value, secret) {
				t.Fatalf("the caller interceptor observed the credential material %q", value)
			}
		}
	}
	if observed.Get("x-request-id") == nil || observed.Get("x-mindclade-sdk") == nil {
		t.Fatalf("the caller interceptor ran outside SDK policy: %v", observed)
	}
	recorder.mu.Lock()
	delivered := recorder.incoming.Get("authorization")
	recorder.mu.Unlock()
	if len(delivered) != 1 || !strings.Contains(delivered[0], secret) {
		t.Fatalf("the credential did not reach the transport: %v", delivered)
	}
}

// capturingObserver records the bounded events the observability seam emits.
type capturingObserver struct {
	mu     sync.Mutex
	events []RPCEvent
}

func (*capturingObserver) RPCStarted(string, int)                       {}
func (*capturingObserver) RPCFinished(string, int, time.Duration, Code) {}

func (observer *capturingObserver) RPCAttempt(event RPCEvent) {
	observer.mu.Lock()
	defer observer.mu.Unlock()
	observer.events = append(observer.events, event)
}

func TestObserverAndLoggerNeverEmitValues(t *testing.T) {
	const bearer = "bearer-material-must-not-be-logged"
	const lease = "lease-material-must-not-be-logged"
	responseHeaders := metadata.MD{
		"authorization":           {"Bearer " + bearer},
		"x-mindclade-lease-token": {lease},
		"x-request-id":            {"server-request-id"},
	}
	responseTrailers := metadata.MD{"retry-after-ms": {"250"}}

	observer := &capturingObserver{}
	var logged bytes.Buffer
	config := retryTestConfig(t, func(int64) int64 { return 0 })
	config.Observer = observer
	if err := WithLogger(slog.New(slog.NewTextHandler(&logged, &slog.HandlerOptions{Level: slog.LevelDebug})), slog.LevelInfo)(&config); err != nil {
		t.Fatal(err)
	}
	logging := config
	config.Observer = observer

	for _, active := range []Config{config, logging} {
		ctx, _, err := withRequestOptions(context.Background(), WithRequestID("observed-request"), WithTraceID("observed-trace"))
		if err != nil {
			t.Fatal(err)
		}
		invokeErr := unaryInterceptor(active)(ctx, safeUnaryMethod, nil, nil, nil,
			func(_ context.Context, _ string, _, _ any, _ *grpc.ClientConn, options ...grpc.CallOption) error {
				scriptedHeaders(options, responseHeaders)
				scriptedTrailers(options, responseTrailers)
				return status.Error(codes.ResourceExhausted, "throttled")
			},
		)
		if invokeErr == nil {
			t.Fatal("scripted failure was not reported")
		}
	}

	observer.mu.Lock()
	events := append([]RPCEvent(nil), observer.events...)
	observer.mu.Unlock()
	if len(events) == 0 {
		t.Fatal("the observer seam received no attempt")
	}
	for _, event := range events {
		if event.Method != safeUnaryMethod || event.Attempt < 1 || event.Elapsed < 0 {
			t.Fatalf("event is not bounded transport telemetry: %#v", event)
		}
		if event.Status != CodeResourceExhausted || event.RequestID != "observed-request" || event.TraceID != "observed-trace" {
			t.Fatalf("event lost its identity or status: %#v", event)
		}
		if event.RetryAfter != 250*time.Millisecond {
			t.Fatalf("event retry-after = %s, want the trailer hint", event.RetryAfter)
		}
		if !slices.Contains(event.MetadataKeys, "authorization") || !slices.Contains(event.MetadataKeys, "x-mindclade-lease-token") {
			t.Fatalf("event did not report metadata key names: %v", event.MetadataKeys)
		}
		for _, name := range event.MetadataKeys {
			if strings.Contains(name, bearer) || strings.Contains(name, lease) {
				t.Fatalf("a metadata VALUE reached the observer: %q", name)
			}
		}
	}

	emitted := logged.String()
	if emitted == "" {
		t.Fatal("MINDCLADE_LOG level handling emitted nothing")
	}
	for _, secret := range []string{bearer, lease} {
		if strings.Contains(emitted, secret) {
			t.Fatalf("credential material was logged: %s", emitted)
		}
	}
	for _, attribute := range []string{"method=", "attempt=", "elapsed=", "status=", "request_id=", "metadata_keys="} {
		if !strings.Contains(emitted, attribute) {
			t.Fatalf("log line is missing %q: %s", attribute, emitted)
		}
	}
}

func TestWatcherAliasesPreserveTheirCursorAndMessageTypes(t *testing.T) {
	// The four domain watchers are aliases of one generic reader, so these
	// assignments are the compile-time proof that consolidating them changed no
	// public cursor or message type. A nil watcher is safe to interrogate.
	var operations *Watcher
	var inference *InferenceWatcher
	var training *TrainingWatcher
	var workflow *WorkflowWatcher

	var operationCursor uint64 = operations.Cursor()
	var inferenceCursor *inferencev1.InferenceStreamCursor = inference.Cursor()
	var trainingCursor uint64 = training.Cursor()
	var workflowCursor uint64 = workflow.Cursor()
	if operationCursor != 0 || inferenceCursor != nil || trainingCursor != 0 || workflowCursor != 0 {
		t.Fatal("a zero watcher reported a non-zero cursor")
	}

	var operationMessage *internaljobv1.WatchOperationResponse = operations.Current()
	var inferenceMessage *inferencev1.InferenceStreamMessage = inference.Current()
	var trainingMessage *internaltrainingv1.WatchTrainingRunResponse = training.Current()
	var workflowMessage *workflowv1.WorkflowRun = workflow.Current()
	if operationMessage != nil || inferenceMessage != nil || trainingMessage != nil || workflowMessage != nil {
		t.Fatal("a zero watcher reported a message")
	}

	for _, err := range []error{operations.Err(), inference.Err(), training.Err(), workflow.Err()} {
		if err != nil {
			t.Fatalf("a zero watcher reported an error: %v", err)
		}
	}
	if _, err := operations.Recv(); !errors.Is(err, io.EOF) {
		t.Fatalf("Recv on a zero watcher = %v, want io.EOF", err)
	}
	if operations.Next() || workflow.Next() {
		t.Fatal("Next advanced a zero watcher")
	}
	if err := operations.Close(); err != nil {
		t.Fatalf("Close on a zero watcher = %v", err)
	}
}

func TestInterceptorSeamIsExplicitAndChainedInsideSDKPolicy(t *testing.T) {
	config := defaultConfig()
	if err := WithInterceptor(nil)(&config); err == nil {
		t.Fatal("a nil unary interceptor was accepted")
	}
	if err := WithStreamInterceptor(nil)(&config); err == nil {
		t.Fatal("a nil stream interceptor was accepted")
	}

	unaryCalls, streamCalls := 0, 0
	client, err := New(
		WithEnvironment(Development),
		WithEndpoint("control-plane.test:443"),
		WithTenantProject("tenant-a", "project-a"),
		WithPrincipal("principal-a"),
		WithTokenProvider(staticTokenProvider{Token{AccessToken: "token", Expiry: time.Now().Add(time.Hour)}}),
		WithInterceptor(func(ctx context.Context, method string, request, response any, connection *grpc.ClientConn, invoke grpc.UnaryInvoker, options ...grpc.CallOption) error {
			unaryCalls++
			return invoke(ctx, method, request, response, connection, options...)
		}),
		WithStreamInterceptor(func(ctx context.Context, description *grpc.StreamDesc, connection *grpc.ClientConn, method string, streamer grpc.Streamer, options ...grpc.CallOption) (grpc.ClientStream, error) {
			streamCalls++
			return streamer(ctx, description, connection, method, options...)
		}),
	)
	if err != nil {
		t.Fatalf("New with caller interceptors: %v", err)
	}
	defer func() { _ = client.Close() }()
	if len(client.config.unaryInterceptors) != 1 || len(client.config.streamInterceptors) != 1 {
		t.Fatalf("caller interceptors = %d unary and %d stream, want one of each",
			len(client.config.unaryInterceptors), len(client.config.streamInterceptors))
	}
	if unaryCalls != 0 || streamCalls != 0 {
		t.Fatal("a caller interceptor ran before any RPC was issued")
	}
}
