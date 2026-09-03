package artifacts

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

type staticIdentityResolver struct {
	identity Identity
	err      error
}

func (r staticIdentityResolver) Resolve(context.Context) (Identity, error) { return r.identity, r.err }

type fixedClock struct{ at time.Time }

func (c fixedClock) Now() time.Time { return c.at }

type fakeServiceRepository struct {
	mu           sync.Mutex
	artifact     *artifactv1.ArtifactRef
	commitCalls  int
	releaseCalls int
	lastCommit   *artifactv1.CommitArtifactCommand
	lastIdentity Identity
	lastDigest   string
}

type fakeTransferRepository struct {
	*fakeServiceRepository
	upload  *internalartifactv1.ArtifactUploadSession
	content []byte
}

func (r *fakeTransferRepository) BeginArtifactUpload(_ context.Context, identity Identity, request *internalartifactv1.BeginArtifactUploadRequest, _ string, at time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.upload == nil {
		r.upload = &internalartifactv1.ArtifactUploadSession{Name: canonicalUploadName(identity, request.GetUploadId()), Artifact: sanitizeArtifact(request.GetArtifact()), State: internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN, CreateTime: timestamppb.New(at), UpdateTime: timestamppb.New(at), ExpireTime: clone(request.GetExpireTime()), Revision: 1, Etag: "upload-etag-1"}
	}
	return clone(r.upload), false, nil
}

func (r *fakeTransferRepository) UploadArtifactChunk(_ context.Context, _ Identity, request *internalartifactv1.UploadArtifactChunkRequest, _ string, at time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.upload == nil || request.GetOffset() != int64(len(r.content)) || request.GetChunkIndex() != r.upload.GetNextChunkIndex() {
		return nil, false, ErrChunkConflict
	}
	r.content = append(r.content, request.GetData()...)
	r.upload.CommittedOffset = int64(len(r.content))
	r.upload.NextChunkIndex++
	r.upload.Revision++
	r.upload.Etag = "upload-etag-" + strconv.FormatInt(r.upload.Revision, 10)
	r.upload.UpdateTime = timestamppb.New(at)
	return clone(r.upload), false, nil
}

func (r *fakeTransferRepository) GetArtifactUpload(_ context.Context, _ Identity, _ string, _ time.Time) (*internalartifactv1.ArtifactUploadSession, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return clone(r.upload), nil
}

func (r *fakeTransferRepository) FinalizeArtifactUpload(_ context.Context, _ Identity, request *internalartifactv1.FinalizeArtifactUploadRequest, _ string, at time.Time) (*internalartifactv1.ArtifactUploadSession, *internalartifactv1.ArtifactStagingReceipt, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.upload == nil || testDigestBytes(r.content) != r.upload.GetArtifact().GetDigest() {
		return nil, nil, false, ErrIntegrityFailure
	}
	receipt := &internalartifactv1.ArtifactStagingReceipt{ReceiptDigest: "sha256:" + strings.Repeat("b", 64), Artifact: sanitizeArtifact(r.upload.GetArtifact()), VerifiedAt: timestamppb.New(at), ExpireTime: clone(request.GetReceiptExpireTime())}
	r.upload.State, r.upload.StagingReceipt = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_FINALIZED, receipt
	r.upload.Revision++
	r.upload.Etag = "upload-etag-final"
	return clone(r.upload), clone(receipt), false, nil
}

func (r *fakeTransferRepository) AbortArtifactUpload(_ context.Context, _ Identity, _ *internalartifactv1.AbortArtifactUploadRequest, _ string, _ time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.upload.State = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_ABORTED
	return clone(r.upload), false, nil
}

func (r *fakeTransferRepository) QuarantineArtifactUpload(_ context.Context, _ Identity, _ *internalartifactv1.QuarantineArtifactUploadRequest, _ string, _ time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.upload.State = internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_QUARANTINED
	return clone(r.upload), false, nil
}

func (r *fakeTransferRepository) OpenArtifact(_ context.Context, _ Identity, _ string, offset int64) (*artifactv1.ArtifactRef, io.ReadCloser, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if offset < 0 || offset > int64(len(r.content)) {
		return nil, nil, ErrInvalidArgument
	}
	return sanitizeArtifact(r.artifact), io.NopCloser(bytes.NewReader(append([]byte(nil), r.content[offset:]...))), nil
}

func testDigestBytes(value []byte) string {
	digest := sha256.Sum256(value)
	return "sha256:" + hex.EncodeToString(digest[:])
}

func (r *fakeServiceRepository) GetArtifact(_ context.Context, identity Identity, _ string) (*artifactv1.ArtifactRef, time.Time, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lastIdentity = identity
	return clone(r.artifact), time.Unix(100, 0).UTC(), nil
}

func (r *fakeServiceRepository) ListArtifacts(_ context.Context, identity Identity, page ArtifactPage) ([]*artifactv1.ArtifactRef, *ArtifactCursor, time.Time, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lastIdentity = identity
	cursor := &ArtifactCursor{AfterTime: time.Unix(99, 0).UTC(), AfterDigest: r.artifact.GetDigest()}
	if !page.AfterTime.IsZero() {
		cursor = nil
	}
	return []*artifactv1.ArtifactRef{clone(r.artifact)}, cursor, time.Unix(100, 0).UTC(), nil
}

func (r *fakeServiceRepository) ResolveArtifactAlias(_ context.Context, identity Identity, _ string) (*artifactv1.ArtifactRef, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lastIdentity = identity
	return clone(r.artifact), nil
}

func (r *fakeServiceRepository) CommitArtifact(_ context.Context, identity Identity, command *artifactv1.CommitArtifactCommand, digest string, _ time.Time) (*artifactv1.ArtifactRef, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.commitCalls++
	r.lastIdentity = identity
	r.lastCommit = clone(command)
	r.lastDigest = digest
	return clone(r.artifact), false, nil
}

func (r *fakeServiceRepository) QuarantineArtifact(_ context.Context, identity Identity, request *internalartifactv1.QuarantineArtifactRequest, _ string, at time.Time) (*operationv1.Operation, bool, error) {
	return completedQuarantineOperation(identity, operationID(identity, request.GetContext().GetIdempotencyKey()), request.GetArtifact(), at), false, nil
}

func (r *fakeServiceRepository) AcquireArtifactLease(_ context.Context, identity Identity, _ *internalartifactv1.AcquireArtifactLeaseRequest, _ string, _ time.Time) (*commonv1.ResourceRef, bool, error) {
	return leaseResource(identity, "lease-a", 1, "etag-a"), false, nil
}

func (r *fakeServiceRepository) ReleaseArtifactLease(_ context.Context, identity Identity, _ *internalartifactv1.ReleaseArtifactLeaseRequest, _ string, _ time.Time) (bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lastIdentity = identity
	r.releaseCalls++
	return false, nil
}

func testArtifact() *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/octet-stream", SizeBytes: 7, ArtifactKind: "model", IntegrityDigest: "sha256:" + strings.Repeat("a", 64)}
}

func testCommandContext(identity Identity, key string) *commonv1.CommandContext {
	return &commonv1.CommandContext{RequestId: "request-" + key, IdempotencyKey: key, TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal, TraceId: "trace-a"}
}

func newTestServer(t *testing.T) (*Server, *fakeServiceRepository, Identity) {
	t.Helper()
	identity := Identity{TenantID: "tenant-a", ProjectID: "project-a", Principal: "principal-a"}
	repository := &fakeServiceRepository{artifact: testArtifact()}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("artifact-page-key-", 3)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, staticIdentityResolver{identity: identity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	server.withClock(fixedClock{at: time.Unix(200, 0).UTC()})
	return server, repository, identity
}

func TestArtifactServiceUsesTrustedIdentityAndRejectsProviderLocator(t *testing.T) {
	t.Parallel()
	server, repository, identity := newTestServer(t)
	command := &artifactv1.CommitArtifactCommand{Context: testCommandContext(identity, "commit-a"), Artifact: testArtifact(), StagingReceiptDigest: "sha256:" + strings.Repeat("b", 64)}
	command.Context.TenantId = "attacker-tenant"
	if _, err := server.CommitArtifact(context.Background(), &internalartifactv1.CommitArtifactRequest{Command: command}); status.Code(err) != codes.PermissionDenied {
		t.Fatalf("untrusted tenant context was accepted: %v", err)
	}
	command.Context.TenantId = identity.TenantID
	command.Artifact.Uri = "gs://private-bucket/provider-object"
	if _, err := server.CommitArtifact(context.Background(), &internalartifactv1.CommitArtifactRequest{Command: command}); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("provider URI was accepted: %v", err)
	}
	command.Artifact.Uri = ""
	response, err := server.CommitArtifact(context.Background(), &internalartifactv1.CommitArtifactRequest{Command: command})
	if err != nil {
		t.Fatalf("commit: %v", err)
	}
	if response.GetArtifact().GetUri() != "" || repository.commitCalls != 1 || repository.lastIdentity != identity || !validDigest(repository.lastDigest) || repository.lastCommit.GetContext().GetCanonicalRequestDigest() != repository.lastDigest {
		t.Fatalf("trusted commit boundary failed: response=%v calls=%d identity=%+v digest=%q", response, repository.commitCalls, repository.lastIdentity, repository.lastDigest)
	}
	command.Artifact.ArtifactKind = "mutated-after-call"
	if repository.lastCommit.GetArtifact().GetArtifactKind() == command.Artifact.GetArtifactKind() {
		t.Fatal("repository retained caller protobuf alias")
	}
}

func TestArtifactServicePaginationIsScopedSignedAndStable(t *testing.T) {
	t.Parallel()
	server, _, identity := newTestServer(t)
	parent := canonicalParent(identity)
	first, err := server.ListArtifacts(context.Background(), &internalartifactv1.ListArtifactsRequest{Parent: parent, Page: &commonv1.PageRequest{PageSize: 1}})
	if err != nil || first.GetPage().GetNextPageToken() == "" {
		t.Fatalf("first page response=%v err=%v", first, err)
	}
	second, err := server.ListArtifacts(context.Background(), &internalartifactv1.ListArtifactsRequest{Parent: parent, Page: &commonv1.PageRequest{PageSize: 1, PageToken: first.GetPage().GetNextPageToken()}})
	if err != nil || second.GetPage().GetNextPageToken() != "" {
		t.Fatalf("second page response=%v err=%v", second, err)
	}
	tampered := first.GetPage().GetNextPageToken() + "x"
	if _, err = server.ListArtifacts(context.Background(), &internalartifactv1.ListArtifactsRequest{Parent: parent, Page: &commonv1.PageRequest{PageSize: 1, PageToken: tampered}}); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("tampered token accepted: %v", err)
	}
	if _, err = server.ListArtifacts(context.Background(), &internalartifactv1.ListArtifactsRequest{Parent: "tenants/other/projects/other"}); status.Code(err) != codes.PermissionDenied {
		t.Fatalf("cross-scope parent accepted: %v", err)
	}
}

func TestArtifactServiceLeaseAndQuarantineValidation(t *testing.T) {
	t.Parallel()
	server, repository, identity := newTestServer(t)
	contextValue := testCommandContext(identity, "lease-a")
	if _, err := server.AcquireArtifactLease(context.Background(), &internalartifactv1.AcquireArtifactLeaseRequest{Context: contextValue, Artifact: testArtifact(), ExpireTime: timestamppb.New(time.Unix(200, 0).Add(maxLeaseDuration + time.Second))}); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("unbounded lease accepted: %v", err)
	}
	leaseResponse, err := server.AcquireArtifactLease(context.Background(), &internalartifactv1.AcquireArtifactLeaseRequest{Context: contextValue, Artifact: testArtifact(), ExpireTime: timestamppb.New(time.Unix(200, 0).Add(time.Hour))})
	if err != nil {
		t.Fatalf("acquire lease: %v", err)
	}
	lease := leaseResponse.GetLease()
	_, err = server.ReleaseArtifactLease(context.Background(), &internalartifactv1.ReleaseArtifactLeaseRequest{Context: testCommandContext(identity, "release-a"), Lease: lease, Etag: lease.GetEtag()})
	if err != nil || repository.releaseCalls != 1 {
		t.Fatalf("release lease calls=%d err=%v", repository.releaseCalls, err)
	}
	badEvidence := &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat("c", 64), SubjectDigest: "sha256:" + strings.Repeat("d", 64), EvidenceKind: "verification"}
	_, err = server.QuarantineArtifact(context.Background(), &internalartifactv1.QuarantineArtifactRequest{Context: testCommandContext(identity, "quarantine-a"), Artifact: testArtifact(), ReasonCode: "DIGEST_MISMATCH", Evidence: []*artifactv1.EvidenceRef{badEvidence}})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("mismatched evidence subject accepted: %v", err)
	}
}

func TestArtifactServiceGeneratedGRPCRegistration(t *testing.T) {
	t.Parallel()
	server, _, identity := newTestServer(t)
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	internalartifactv1.RegisterArtifactServiceServer(grpcServer, server)
	serveDone := make(chan error, 1)
	go func() { serveDone <- grpcServer.Serve(listener) }()
	t.Cleanup(func() {
		grpcServer.Stop()
		_ = listener.Close()
		<-serveDone
	})
	connection, err := grpc.NewClient("passthrough:///bufnet", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internalartifactv1.NewArtifactServiceClient(connection)
	response, err := client.GetArtifact(context.Background(), &internalartifactv1.GetArtifactRequest{Name: canonicalArtifactName(identity, testArtifact().GetDigest())})
	if err != nil || !proto.Equal(response.GetArtifact(), testArtifact()) {
		t.Fatalf("networked generated client response=%v err=%v", response, err)
	}
}

func TestArtifactTransferGeneratedGRPCUploadFinalizeDownloadAndCancellation(t *testing.T) {
	t.Parallel()
	identity := Identity{TenantID: "tenant-a", ProjectID: "project-a", Principal: "principal-a"}
	content := []byte("generated transport content")
	artifact := &artifactv1.ArtifactRef{Digest: testDigestBytes(content), MediaType: "application/octet-stream", SizeBytes: int64(len(content)), ArtifactKind: "dataset", IntegrityDigest: testDigestBytes(content)}
	repository := &fakeTransferRepository{fakeServiceRepository: &fakeServiceRepository{artifact: artifact}}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("artifact-page-key-", 3)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, staticIdentityResolver{identity: identity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Unix(200, 0).UTC()
	server.withClock(fixedClock{at: at})
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	internalartifactv1.RegisterArtifactServiceServer(grpcServer, server)
	serveDone := make(chan error, 1)
	go func() { serveDone <- grpcServer.Serve(listener) }()
	t.Cleanup(func() {
		grpcServer.Stop()
		_ = listener.Close()
		<-serveDone
	})
	connection, err := grpc.NewClient("passthrough:///bufnet", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internalartifactv1.NewArtifactServiceClient(connection)
	begun, err := client.BeginArtifactUpload(context.Background(), &internalartifactv1.BeginArtifactUploadRequest{Context: testCommandContext(identity, "begin-network"), Parent: canonicalParent(identity), Artifact: artifact, UploadId: "network-a", ExpireTime: timestamppb.New(at.Add(time.Hour))})
	if err != nil {
		t.Fatal(err)
	}
	uploaded, err := client.UploadArtifactChunk(context.Background(), &internalartifactv1.UploadArtifactChunkRequest{Context: testCommandContext(identity, "chunk-network"), Name: begun.GetUpload().GetName(), ChunkIndex: 0, Data: content, ChunkDigest: testDigestBytes(content), Etag: begun.GetUpload().GetEtag()})
	if err != nil {
		t.Fatal(err)
	}
	finalized, err := client.FinalizeArtifactUpload(context.Background(), &internalartifactv1.FinalizeArtifactUploadRequest{Context: testCommandContext(identity, "finalize-network"), Name: uploaded.GetUpload().GetName(), Etag: uploaded.GetUpload().GetEtag(), ReceiptExpireTime: timestamppb.New(at.Add(time.Hour))})
	if err != nil || finalized.GetStagingReceipt().GetReceiptDigest() == "" {
		t.Fatalf("finalize=%v err=%v", finalized, err)
	}
	stream, err := client.DownloadArtifact(context.Background(), &internalartifactv1.DownloadArtifactRequest{Digest: artifact.GetDigest(), MaxChunkBytes: 5})
	if err != nil {
		t.Fatal(err)
	}
	var downloaded []byte
	for {
		response, receiveErr := stream.Recv()
		if errors.Is(receiveErr, io.EOF) {
			break
		}
		if receiveErr != nil {
			t.Fatal(receiveErr)
		}
		if response.GetData() != nil && testDigestBytes(response.GetData()) != response.GetChunkDigest() {
			t.Fatal("download chunk digest mismatch")
		}
		downloaded = append(downloaded, response.GetData()...)
	}
	if !bytes.Equal(downloaded, content) {
		t.Fatalf("download=%q", downloaded)
	}
	cancelContext, cancel := context.WithCancel(context.Background())
	cancel()
	stream, err = client.DownloadArtifact(cancelContext, &internalartifactv1.DownloadArtifactRequest{Digest: artifact.GetDigest()})
	if err == nil {
		_, err = stream.Recv()
	}
	if status.Code(err) != codes.Canceled {
		t.Fatalf("cancelled download was not cancelled: %v", err)
	}
}

func TestArtifactServiceFailsClosedWithoutAuthenticatedIdentity(t *testing.T) {
	t.Parallel()
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("artifact-page-key-", 3)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(&fakeServiceRepository{artifact: testArtifact()}, staticIdentityResolver{err: ErrUnauthenticated}, codec)
	if err != nil {
		t.Fatal(err)
	}
	_, err = server.GetArtifact(context.Background(), &internalartifactv1.GetArtifactRequest{Digest: testArtifact().GetDigest()})
	if status.Code(err) != codes.Unauthenticated || !errors.Is(rpcError(ErrUnauthenticated), status.Error(codes.Unauthenticated, "authenticated identity is required")) && status.Code(rpcError(ErrUnauthenticated)) != codes.Unauthenticated {
		t.Fatalf("unauthenticated request was not rejected: %v", err)
	}
}
