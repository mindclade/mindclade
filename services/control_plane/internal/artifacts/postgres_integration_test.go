package artifacts

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	objectstorage "github.com/mindclade/mindclade/libs/go/storage"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
)

type fixtureObjectStore struct {
	mu      sync.Mutex
	tenant  string
	digest  string
	content []byte
	opens   int
	chunks  map[string]map[int64][]byte
}

func (s *fixtureObjectStore) Put(context.Context, string, string, int64, io.Reader) (objectstorage.Object, error) {
	return objectstorage.Object{}, errors.New("fixture object store is read-only")
}

func (s *fixtureObjectStore) Open(_ context.Context, tenant, digest string) (io.ReadCloser, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if tenant != s.tenant || digest != s.digest {
		return nil, objectstorage.ErrObjectNotFound
	}
	s.opens++
	return io.NopCloser(bytes.NewReader(append([]byte(nil), s.content...))), nil
}

func (s *fixtureObjectStore) Verify(ctx context.Context, object objectstorage.Object) error {
	reader, err := s.Open(ctx, object.TenantID, object.Digest)
	if err != nil {
		return err
	}
	defer func() { _ = reader.Close() }()
	content, err := io.ReadAll(reader)
	if err != nil || int64(len(content)) != object.Size || object.Generation != 7 {
		return objectstorage.ErrGenerationMismatch
	}
	return nil
}

func (s *fixtureObjectStore) PutChunk(_ context.Context, tenant, session string, chunk objectstorage.UploadChunk, data []byte) (objectstorage.UploadChunk, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if tenant == "" || session == "" || chunk.Size != int64(len(data)) || testBytesDigest(data) != chunk.Digest {
		return objectstorage.UploadChunk{}, objectstorage.ErrDigestMismatch
	}
	if s.chunks == nil {
		s.chunks = make(map[string]map[int64][]byte)
	}
	if s.chunks[session] == nil {
		s.chunks[session] = make(map[int64][]byte)
	}
	if existing, ok := s.chunks[session][chunk.Index]; ok && !bytes.Equal(existing, data) {
		return objectstorage.UploadChunk{}, objectstorage.ErrDigestMismatch
	}
	s.chunks[session][chunk.Index] = append([]byte(nil), data...)
	chunk.Generation = chunk.Index + 11
	return chunk, nil
}

func (s *fixtureObjectStore) Finalize(_ context.Context, tenant, session string, chunks []objectstorage.UploadChunk, digest string, size int64) (objectstorage.Object, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	content := make([]byte, 0, size)
	for index, chunk := range chunks {
		value := s.chunks[session][int64(index)]
		if chunk.Index != int64(index) || chunk.Offset != int64(len(content)) || int64(len(value)) != chunk.Size || testBytesDigest(value) != chunk.Digest || chunk.Generation != chunk.Index+11 {
			return objectstorage.Object{}, objectstorage.ErrGenerationMismatch
		}
		content = append(content, value...)
	}
	if int64(len(content)) != size || testBytesDigest(content) != digest {
		return objectstorage.Object{}, objectstorage.ErrDigestMismatch
	}
	s.tenant, s.digest, s.content = tenant, digest, append([]byte(nil), content...)
	return objectstorage.Object{TenantID: tenant, Digest: digest, Size: size, Generation: 7}, nil
}

func (s *fixtureObjectStore) OpenPinned(_ context.Context, object objectstorage.Object, offset int64) (io.ReadCloser, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if object.TenantID != s.tenant || object.Digest != s.digest || object.Size != int64(len(s.content)) || object.Generation != 7 || offset < 0 || offset > int64(len(s.content)) {
		return nil, objectstorage.ErrGenerationMismatch
	}
	s.opens++
	return io.NopCloser(bytes.NewReader(append([]byte(nil), s.content[offset:]...))), nil
}

func (s *fixtureObjectStore) DeleteChunks(_ context.Context, tenant, session string, _ []objectstorage.UploadChunk) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if tenant != s.tenant && s.tenant != "" {
		return objectstorage.ErrObjectNotFound
	}
	delete(s.chunks, session)
	return nil
}

func testBytesDigest(value []byte) string {
	digest := sha256.Sum256(value)
	return "sha256:" + hex.EncodeToString(digest[:])
}

func (s *fixtureObjectStore) Opens() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.opens
}

func artifactIntegrationDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("MINDCLADE_TEST_POSTGRES_DSN")
	if dsn == "" {
		if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
			t.Fatal("MINDCLADE_TEST_POSTGRES_DSN is required")
		}
		t.Skip("PostgreSQL integration DSN is not configured")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
	return db
}

func TestPostgresArtifactCommitReplayLeaseQuarantineAndRLS(t *testing.T) {
	db := artifactIntegrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "tenant-artifact-" + suffix, ProjectID: "project-a", Principal: "principal-a"}
	t.Cleanup(func() {
		cleanupTx, cleanupErr := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
		if cleanupErr != nil {
			t.Errorf("begin artifact cleanup: %v", cleanupErr)
			return
		}
		defer func() { _ = cleanupTx.Rollback() }()
		for _, table := range []string{"artifact_command_receipts", "artifact_operations", "artifact_leases", "artifact_quarantine_evidence", "artifact_aliases", "outbox_messages", "artifact_catalog_entries", "artifact_staging_receipts"} {
			if _, cleanupErr = cleanupTx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", identity.TenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("cleanup %s: %v", table, cleanupErr)
			}
		}
		if cleanupErr = cleanupTx.Commit(); cleanupErr != nil {
			t.Errorf("commit artifact cleanup: %v", cleanupErr)
		}
	})
	artifact := testArtifact()
	artifact.SchemaId, artifact.SchemaVersion = "model_manifest", "1.0.0"
	objectStore := &fixtureObjectStore{tenant: identity.TenantID, digest: artifact.GetDigest(), content: make([]byte, artifact.GetSizeBytes())}
	receipts := SQLGCSStagingReceiptStore{DB: db, Objects: objectStore}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("artifact-integration-page-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	at := time.Now().UTC().Truncate(time.Microsecond)
	receipts.Now = func() time.Time { return at }
	if _, err = receipts.RecordVerifiedObject(ctx, identity, objectstorage.Object{TenantID: identity.TenantID, Digest: artifact.GetDigest(), Size: artifact.GetSizeBytes(), Generation: 8}, at.Add(-time.Minute), at.Add(time.Hour)); !errors.Is(err, ErrStagingUnverified) {
		t.Fatalf("unverified provider generation produced a receipt: %v", err)
	}
	receipt, err := receipts.RecordVerifiedObject(ctx, identity, objectstorage.Object{TenantID: identity.TenantID, Digest: artifact.GetDigest(), Size: artifact.GetSizeBytes(), Generation: 7}, at.Add(-time.Minute), at.Add(time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	staging, err := NewStagingVerifier(receipts)
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Staging: staging, Events: GeneratedEventFactory{}}
	server, err := NewServer(repository, staticIdentityResolver{identity: identity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	server.withClock(fixedClock{at: at})

	commitRequest := &internalartifactv1.CommitArtifactRequest{Command: &artifactv1.CommitArtifactCommand{Context: testCommandContext(identity, "commit-"+suffix), Artifact: artifact, StagingReceiptDigest: receipt}}
	committed, err := server.CommitArtifact(ctx, commitRequest)
	if err != nil || committed.GetArtifact().GetUri() != "" || objectStore.Opens() != 3 {
		t.Fatalf("commit response=%v object_opens=%d err=%v", committed, objectStore.Opens(), err)
	}
	replayed, err := server.CommitArtifact(ctx, commitRequest)
	if err != nil || objectStore.Opens() != 3 || !proto.Equal(committed, replayed) {
		t.Fatalf("replay response=%v object_opens=%d err=%v", replayed, objectStore.Opens(), err)
	}
	if err = receipts.QuarantineReceipt(ctx, identity, receipt, "INTEGRITY_FAILURE", at); !errors.Is(err, ErrInvalidTransition) {
		t.Fatalf("receipt backing a committed artifact was quarantined: %v", err)
	}
	conflict := clone(commitRequest)
	conflict.Command.Artifact.ArtifactKind = "different-kind"
	if _, err = server.CommitArtifact(ctx, conflict); status.Code(err) != codes.Aborted {
		t.Fatalf("idempotency conflict was accepted: %v", err)
	}

	list, err := server.ListArtifacts(ctx, &internalartifactv1.ListArtifactsRequest{Parent: canonicalParent(identity), Page: &commonv1.PageRequest{PageSize: 1}, Filter: `state = "COMMITTED"`})
	if err != nil || len(list.GetArtifacts()) != 1 || list.GetArtifacts()[0].GetUri() != "" || list.GetPage().GetNextPageToken() != "" {
		t.Fatalf("list response=%v err=%v", list, err)
	}

	leaseRequest := &internalartifactv1.AcquireArtifactLeaseRequest{Context: testCommandContext(identity, "acquire-"+suffix), Artifact: artifact, ExpireTime: timestamppb.New(at.Add(time.Hour))}
	leaseResponse, err := server.AcquireArtifactLease(ctx, leaseRequest)
	if err != nil || leaseResponse.GetLease().GetEtag() == "" {
		t.Fatalf("acquire lease response=%v err=%v", leaseResponse, err)
	}
	leaseReplay, err := server.AcquireArtifactLease(ctx, leaseRequest)
	if err != nil || !proto.Equal(leaseResponse, leaseReplay) {
		t.Fatalf("lease replay response=%v err=%v", leaseReplay, err)
	}
	shortLeaseRequest := clone(leaseRequest)
	shortLeaseRequest.Context = testCommandContext(identity, "acquire-short-"+suffix)
	shortLeaseRequest.ExpireTime = timestamppb.New(at.Add(30 * time.Minute))
	shortLeaseResponse, err := server.AcquireArtifactLease(ctx, shortLeaseRequest)
	if err != nil || shortLeaseResponse.GetLease().GetEtag() != leaseResponse.GetLease().GetEtag() {
		t.Fatalf("lease acquisition shortened an active lease: response=%v err=%v", shortLeaseResponse, err)
	}
	longLeaseRequest := clone(leaseRequest)
	longLeaseRequest.Context = testCommandContext(identity, "acquire-long-"+suffix)
	longLeaseRequest.ExpireTime = timestamppb.New(at.Add(2 * time.Hour))
	longLeaseResponse, err := server.AcquireArtifactLease(ctx, longLeaseRequest)
	if err != nil || longLeaseResponse.GetLease().GetEtag() == leaseResponse.GetLease().GetEtag() {
		t.Fatalf("lease extension did not advance revision: response=%v err=%v", longLeaseResponse, err)
	}
	releaseRequest := &internalartifactv1.ReleaseArtifactLeaseRequest{Context: testCommandContext(identity, "release-"+suffix), Lease: clone(longLeaseResponse.GetLease()), Etag: longLeaseResponse.GetLease().GetEtag()}
	if _, err = server.ReleaseArtifactLease(ctx, releaseRequest); err != nil {
		t.Fatalf("release lease: %v", err)
	}
	if _, err = server.ReleaseArtifactLease(ctx, releaseRequest); err != nil {
		t.Fatalf("release replay: %v", err)
	}

	evidence := &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat("c", 64), SubjectDigest: artifact.GetDigest(), EvidenceKind: "integrity_check", PolicyDigest: "sha256:" + strings.Repeat("d", 64)}
	quarantineRequest := &internalartifactv1.QuarantineArtifactRequest{Context: testCommandContext(identity, "quarantine-"+suffix), Artifact: artifact, ReasonCode: "INTEGRITY_FAILURE", Evidence: []*artifactv1.EvidenceRef{evidence}}
	quarantined, err := server.QuarantineArtifact(ctx, quarantineRequest)
	if err != nil || !quarantined.GetOperation().GetDone() || quarantined.GetOperation().GetState().String() != "OPERATION_STATE_SUCCEEDED" || quarantined.GetOperation().GetTarget().GetResourceVersion() != 2 {
		t.Fatalf("quarantine response=%v err=%v", quarantined, err)
	}
	quarantineReplay, err := server.QuarantineArtifact(ctx, quarantineRequest)
	if err != nil || !proto.Equal(quarantined, quarantineReplay) {
		t.Fatalf("quarantine replay response=%v err=%v", quarantineReplay, err)
	}

	readTx, err := platformdb.BeginTenantTx(ctx, db, identity.TenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	rows, err := readTx.QueryContext(ctx, `SELECT envelope_bytes FROM outbox_messages WHERE tenant_id=$1 AND aggregate_id=$2 ORDER BY aggregate_sequence`, identity.TenantID, canonicalArtifactName(identity, artifact.GetDigest()))
	if err != nil {
		_ = readTx.Rollback()
		t.Fatal(err)
	}
	var payloadTypes []string
	for rows.Next() {
		var encoded []byte
		if err = rows.Scan(&encoded); err != nil {
			t.Fatal(err)
		}
		envelope, decodeErr := pubsubx.UnmarshalEnvelope(encoded)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
		if decodeErr != nil {
			t.Fatal(decodeErr)
		}
		payloadTypes = append(payloadTypes, string(payload.ProtoReflect().Descriptor().FullName()))
	}
	if err = rows.Err(); err != nil {
		t.Fatal(err)
	}
	_ = platformdb.CloseRows(rows)
	if err = readTx.Commit(); err != nil {
		t.Fatal(err)
	}
	if len(payloadTypes) != 2 || payloadTypes[0] != "mindclade.events.artifact.v1.ArtifactCommitted" || payloadTypes[1] != "mindclade.events.artifact.v1.ArtifactQuarantined" {
		t.Fatalf("typed artifact event sequence=%v", payloadTypes)
	}

	assertArtifactRLS(t, ctx, db, suffix, identity.TenantID)
}

func TestPostgresArtifactTransferResumeReplayFinalizeCommitDownloadAndExpiry(t *testing.T) {
	db := artifactIntegrationDB(t)
	ctx := context.Background()
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	identity := Identity{TenantID: "tenant-transfer-" + suffix, ProjectID: "project-a", Principal: "principal-a"}
	t.Cleanup(func() {
		cleanupTx, cleanupErr := platformdb.BeginTenantTx(ctx, db, identity.TenantID, nil)
		if cleanupErr != nil {
			t.Errorf("begin transfer cleanup: %v", cleanupErr)
			return
		}
		defer func() { _ = cleanupTx.Rollback() }()
		for _, table := range []string{"artifact_command_receipts", "artifact_operations", "artifact_leases", "artifact_quarantine_evidence", "artifact_aliases", "artifact_catalog_entries", "artifact_upload_chunks", "artifact_upload_sessions", "artifact_staging_receipts", "outbox_messages"} {
			if _, cleanupErr = cleanupTx.ExecContext(ctx, "DELETE FROM "+table+" WHERE tenant_id=$1", identity.TenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("cleanup %s: %v", table, cleanupErr)
			}
		}
		if cleanupErr = cleanupTx.Commit(); cleanupErr != nil {
			t.Errorf("commit transfer cleanup: %v", cleanupErr)
		}
	})
	content := []byte("resumable authoritative artifact transfer")
	artifact := &artifactv1.ArtifactRef{Digest: testBytesDigest(content), MediaType: "application/octet-stream", SizeBytes: int64(len(content)), ArtifactKind: "dataset", IntegrityDigest: testBytesDigest(content)}
	objects := &fixtureObjectStore{}
	staging, err := NewStagingVerifier(SQLGCSStagingReceiptStore{DB: db, Objects: objects})
	if err != nil {
		t.Fatal(err)
	}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("artifact-transfer-page-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	repository := SQLRepository{DB: db, Staging: staging, Events: GeneratedEventFactory{}, Objects: objects}
	server, err := NewServer(repository, staticIdentityResolver{identity: identity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Now().UTC().Truncate(time.Microsecond)
	server.withClock(fixedClock{at: at})
	beginRequest := &internalartifactv1.BeginArtifactUploadRequest{Context: testCommandContext(identity, "begin-"+suffix), Parent: canonicalParent(identity), Artifact: artifact, UploadId: "upload-shared", ExpireTime: timestamppb.New(at.Add(time.Hour))}
	begun, err := server.BeginArtifactUpload(ctx, beginRequest)
	if err != nil || begun.GetUpload().GetState() != internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_OPEN || begun.GetUpload().GetEtag() == "" {
		t.Fatalf("begin=%v err=%v", begun, err)
	}
	replayedBegin, err := server.BeginArtifactUpload(ctx, beginRequest)
	if err != nil || !proto.Equal(begun, replayedBegin) {
		t.Fatalf("begin replay=%v err=%v", replayedBegin, err)
	}
	parts := [][]byte{content[:17], content[17:]}
	current := begun.GetUpload()
	var offset int64
	for index, part := range parts {
		request := &internalartifactv1.UploadArtifactChunkRequest{Context: testCommandContext(identity, "chunk-"+strconv.Itoa(index)+"-"+suffix), Name: current.GetName(), ChunkIndex: int64(index), Offset: offset, Data: part, ChunkDigest: testBytesDigest(part), Etag: current.GetEtag()}
		response, uploadErr := server.UploadArtifactChunk(ctx, request)
		if uploadErr != nil || response.GetUpload().GetCommittedOffset() != offset+int64(len(part)) || response.GetUpload().GetNextChunkIndex() != int64(index+1) {
			t.Fatalf("chunk %d response=%v err=%v", index, response, uploadErr)
		}
		replay, replayErr := server.UploadArtifactChunk(ctx, request)
		if replayErr != nil || !proto.Equal(response, replay) {
			t.Fatalf("chunk %d replay=%v err=%v", index, replay, replayErr)
		}
		if index == 0 {
			stale := clone(request)
			stale.Context = testCommandContext(identity, "stale-"+suffix)
			stale.ChunkIndex, stale.Offset, stale.Data, stale.ChunkDigest = 1, int64(len(part)), parts[1], testBytesDigest(parts[1])
			stale.Etag = begun.GetUpload().GetEtag()
			if _, staleErr := server.UploadArtifactChunk(ctx, stale); status.Code(staleErr) != codes.Aborted {
				t.Fatalf("stale etag accepted: %v", staleErr)
			}
		}
		current = response.GetUpload()
		offset += int64(len(part))
	}
	corrupt := &internalartifactv1.UploadArtifactChunkRequest{Context: testCommandContext(identity, "corrupt-"+suffix), Name: current.GetName(), ChunkIndex: current.GetNextChunkIndex(), Offset: current.GetCommittedOffset(), Data: []byte("corrupt"), ChunkDigest: testBytesDigest([]byte("different")), Etag: current.GetEtag()}
	if _, err = server.UploadArtifactChunk(ctx, corrupt); status.Code(err) != codes.DataLoss {
		t.Fatalf("corrupt chunk accepted: %v", err)
	}
	finalizeRequest := &internalartifactv1.FinalizeArtifactUploadRequest{Context: testCommandContext(identity, "finalize-"+suffix), Name: current.GetName(), Etag: current.GetEtag(), ReceiptExpireTime: timestamppb.New(at.Add(2 * time.Hour))}
	finalized, err := server.FinalizeArtifactUpload(ctx, finalizeRequest)
	if err != nil || finalized.GetUpload().GetState() != internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_FINALIZED || !validDigest(finalized.GetStagingReceipt().GetReceiptDigest()) || finalized.GetStagingReceipt().GetArtifact().GetUri() != "" {
		t.Fatalf("finalized=%v err=%v", finalized, err)
	}
	finalizedReplay, err := server.FinalizeArtifactUpload(ctx, finalizeRequest)
	if err != nil || !proto.Equal(finalized, finalizedReplay) {
		t.Fatalf("finalize replay=%v err=%v", finalizedReplay, err)
	}
	commit := &internalartifactv1.CommitArtifactRequest{Command: &artifactv1.CommitArtifactCommand{Context: testCommandContext(identity, "commit-transfer-"+suffix), Artifact: artifact, StagingReceiptDigest: finalized.GetStagingReceipt().GetReceiptDigest()}}
	if _, err = server.CommitArtifact(ctx, commit); err != nil {
		t.Fatalf("commit finalized artifact: %v", err)
	}
	resolved, reader, err := repository.OpenArtifact(ctx, identity, artifact.GetDigest(), 7)
	if err != nil {
		t.Fatalf("open pinned resume: %v", err)
	}
	got, readErr := io.ReadAll(reader)
	closeErr := reader.Close()
	if readErr != nil || closeErr != nil || !proto.Equal(resolved, artifact) || !bytes.Equal(got, content[7:]) {
		t.Fatalf("resume content=%q artifact=%v read=%v close=%v", got, resolved, readErr, closeErr)
	}

	otherIdentity := Identity{TenantID: identity.TenantID, ProjectID: "project-b", Principal: identity.Principal}
	otherServer, err := NewServer(repository, staticIdentityResolver{identity: otherIdentity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	otherServer.withClock(fixedClock{at: at})
	otherBegin := clone(beginRequest)
	otherBegin.Context = testCommandContext(otherIdentity, "begin-other-"+suffix)
	otherBegin.Parent = canonicalParent(otherIdentity)
	if _, err = otherServer.BeginArtifactUpload(ctx, otherBegin); err != nil {
		t.Fatalf("same upload leaf in another project collided: %v", err)
	}
	if _, err = otherServer.GetArtifactUpload(ctx, &internalartifactv1.GetArtifactUploadRequest{Name: begun.GetUpload().GetName()}); status.Code(err) != codes.PermissionDenied {
		t.Fatalf("cross-project upload read accepted: %v", err)
	}

	expiring := clone(beginRequest)
	expiring.Context = testCommandContext(identity, "begin-expiring-"+suffix)
	expiring.UploadId = "upload-expiring"
	expiring.ExpireTime = timestamppb.New(at.Add(time.Minute))
	expiringResponse, err := server.BeginArtifactUpload(ctx, expiring)
	if err != nil {
		t.Fatal(err)
	}
	server.withClock(fixedClock{at: at.Add(2 * time.Minute)})
	expired, err := server.GetArtifactUpload(ctx, &internalartifactv1.GetArtifactUploadRequest{Name: expiringResponse.GetUpload().GetName()})
	if err != nil || expired.GetUpload().GetState() != internalartifactv1.ArtifactUploadState_ARTIFACT_UPLOAD_STATE_EXPIRED {
		t.Fatalf("expired upload=%v err=%v", expired, err)
	}
}

func assertArtifactRLS(t *testing.T, ctx context.Context, db *sql.DB, suffix, protectedTenant string) {
	t.Helper()
	var superuser, bypassRLS, createRole bool
	if err := db.QueryRowContext(ctx, `SELECT rolsuper,rolbypassrls,rolcreaterole FROM pg_roles WHERE rolname=current_user`).Scan(&superuser, &bypassRLS, &createRole); err != nil {
		t.Fatal(err)
	}
	var tx *sql.Tx
	var err error
	if superuser || bypassRLS {
		if !superuser && !createRole {
			t.Fatal("PostgreSQL integration identity bypasses RLS and cannot create a non-bypass qualification role")
		}
		// suffix is generated exclusively from decimal timestamp digits above and
		// therefore remains a safe, bounded SQL identifier.
		role := "artifact_rls_" + suffix
		if _, err = db.ExecContext(ctx, `CREATE ROLE `+role+` NOSUPERUSER NOBYPASSRLS NOLOGIN`); err != nil {
			t.Fatal(err)
		}
		cleanupContext := context.WithoutCancel(ctx)
		t.Cleanup(func() {
			_, _ = db.ExecContext(cleanupContext, `DROP OWNED BY `+role)
			_, _ = db.ExecContext(cleanupContext, `DROP ROLE IF EXISTS `+role)
		})
		if _, err = db.ExecContext(ctx, `GRANT USAGE ON SCHEMA public TO `+role); err != nil {
			t.Fatal(err)
		}
		if _, err = db.ExecContext(ctx, `GRANT SELECT ON artifact_catalog_entries TO `+role); err != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
			t.Fatal(err)
		}
		if tx, err = db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true}); err != nil {
			t.Fatal(err)
		}
		if _, err = tx.ExecContext(ctx, `SET LOCAL ROLE `+role); err != nil {
			_ = tx.Rollback()
			t.Fatal(err)
		}
		if _, err = tx.ExecContext(ctx, `SELECT set_config('app.tenant_id', $1, true), set_config('row_security', 'on', true)`, "different-tenant"); err != nil {
			_ = tx.Rollback()
			t.Fatal(err)
		}
	} else {
		tx, err = platformdb.BeginTenantTx(ctx, db, "different-tenant", &sql.TxOptions{ReadOnly: true})
		if err != nil {
			t.Fatal(err)
		}
	}
	defer func() { _ = tx.Rollback() }()
	var visible int
	if err = tx.QueryRowContext(ctx, `SELECT count(*) FROM artifact_catalog_entries WHERE tenant_id=$1`, protectedTenant).Scan(&visible); err != nil {
		t.Fatal(err)
	}
	if err = tx.Commit(); err != nil {
		t.Fatal(err)
	}
	if visible != 0 {
		t.Fatalf("RLS exposed %d artifact rows across tenants", visible)
	}
}

func TestStagingVerifierFailsClosed(t *testing.T) {
	identity := Identity{TenantID: "tenant-a", ProjectID: "project-a", Principal: "principal-a"}
	verifier, err := NewStagingVerifier(stagingReceiptStoreFunc(func(context.Context, Identity, string, *artifactv1.ArtifactRef) error {
		return errors.New("missing immutable receipt")
	}))
	if err != nil {
		t.Fatal(err)
	}
	if err = verifier.Verify(context.Background(), identity, "sha256:"+strings.Repeat("b", 64), testArtifact()); !errors.Is(err, ErrStagingUnverified) {
		t.Fatalf("unverified staging receipt passed: %v", err)
	}
}

type stagingReceiptStoreFunc func(context.Context, Identity, string, *artifactv1.ArtifactRef) error

func (f stagingReceiptStoreFunc) VerifyReceipt(ctx context.Context, identity Identity, receipt string, artifact *artifactv1.ArtifactRef) error {
	return f(ctx, identity, receipt, artifact)
}
