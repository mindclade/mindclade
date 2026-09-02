package training

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	internaltrainingv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/training/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

var fixtureTime = time.Date(2026, 9, 1, 12, 0, 0, 0, time.UTC)

type fixedResolver struct {
	identity Identity
	err      error
}

func (r fixedResolver) Resolve(context.Context) (Identity, error) { return r.identity, r.err }

type fixedClock struct{ value time.Time }

func (c fixedClock) Now() time.Time { return c.value }

type fakeRepository struct {
	created    bool
	identity   Identity
	command    *trainingv1.CreateTrainingRunCommand
	digest     string
	operation  *jobv1.Operation
	revisions  []*jobv1.Operation
	historyErr error
	run        *trainingv1.TrainingRun
}

func (r *fakeRepository) CreateTrainingRun(_ context.Context, identity Identity, command *trainingv1.CreateTrainingRunCommand, digest string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.created = true
	r.identity = identity
	r.command = clone(command)
	r.digest = digest
	return clone(r.operation), false, nil
}

func (r *fakeRepository) GetTrainingRun(context.Context, Identity, string) (*trainingv1.TrainingRun, error) {
	if r.run == nil {
		return nil, ErrNotFound
	}
	return clone(r.run), nil
}

func (*fakeRepository) ListTrainingRuns(context.Context, Identity, RunPage) ([]*trainingv1.TrainingRun, string, time.Time, error) {
	return nil, "", fixtureTime, nil
}

func (*fakeRepository) StartTrainingAttempt(context.Context, Identity, *trainingv1.StartTrainingAttemptCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error) {
	return nil, false, ErrNotFound
}

func (*fakeRepository) ResumeTrainingAttempt(context.Context, Identity, *trainingv1.ResumeTrainingAttemptCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error) {
	return nil, false, ErrNotFound
}

func (*fakeRepository) CommitTrainingProgress(context.Context, Identity, *trainingv1.CommitTrainingProgressCommand, string, time.Time) (*trainingv1.TrainingProgress, *trainingv1.TrainingRun, bool, error) {
	return nil, nil, false, ErrNotFound
}

func (*fakeRepository) PrepareCheckpoint(context.Context, Identity, *trainingv1.PrepareCheckpointCommand, string, time.Time) (*trainingv1.Checkpoint, bool, error) {
	return nil, false, ErrNotFound
}

func (*fakeRepository) CommitCheckpoint(context.Context, Identity, *trainingv1.CommitCheckpointCommand, string, time.Time) (*trainingv1.Checkpoint, *trainingv1.TrainingRun, bool, error) {
	return nil, nil, false, ErrNotFound
}

func (*fakeRepository) CompleteTrainingRun(context.Context, Identity, *trainingv1.CompleteTrainingRunCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error) {
	return nil, false, ErrNotFound
}

func (*fakeRepository) CancelTrainingRun(context.Context, Identity, *trainingv1.CancelTrainingRunCommand, string, time.Time) (*trainingv1.TrainingRun, bool, error) {
	return nil, false, ErrNotFound
}

func (*fakeRepository) GetCheckpoint(context.Context, Identity, string) (*trainingv1.Checkpoint, error) {
	return nil, ErrNotFound
}

func (*fakeRepository) ListCheckpoints(context.Context, Identity, CheckpointPage) ([]*trainingv1.Checkpoint, string, time.Time, error) {
	return nil, "", fixtureTime, nil
}

func (r *fakeRepository) GetOperation(context.Context, Identity, string) (*jobv1.Operation, error) {
	if r.operation == nil {
		return nil, ErrNotFound
	}
	return clone(r.operation), nil
}

func (r *fakeRepository) ReadOperationRevisions(_ context.Context, _ Identity, _ string, after uint64, limit int) ([]*jobv1.Operation, bool, error) {
	if r.historyErr != nil {
		return nil, false, r.historyErr
	}
	values := r.revisions
	if len(values) == 0 && r.operation != nil {
		values = []*jobv1.Operation{r.operation}
	}
	result := make([]*jobv1.Operation, 0, limit)
	terminal := false
	for _, value := range values {
		if uint64(value.GetResourceVersion()) <= after { //nolint:gosec // Deterministic test fixture values are nonnegative and bounded before conversion.
			if uint64(value.GetResourceVersion()) == after && value.GetDone() { //nolint:gosec // Deterministic test fixture values are nonnegative and bounded before conversion.
				terminal = true
			}
			continue
		}
		if len(result) == limit {
			break
		}
		result = append(result, clone(value))
		terminal = value.GetDone()
	}
	return result, terminal, nil
}

func (*fakeRepository) ListOperations(context.Context, Identity, OperationPage) ([]*jobv1.Operation, string, time.Time, error) {
	return nil, "", fixtureTime, nil
}

func (*fakeRepository) CancelOperation(context.Context, Identity, *internaljobv1.CancelOperationRequest, string, time.Time) (*jobv1.Operation, bool, error) {
	return nil, false, ErrNotFound
}

func testIdentity() Identity {
	return Identity{TenantID: "tenant-01", ProjectID: "project-01", Principal: "principal-01", WorkerID: "worker-01", LeaseToken: "lease-token-value"} //nolint:gosec // This is a protocol header or deterministic test fixture, not a credential.
}

func commandContext(message proto.Message, identity Identity) *commonv1.CommandContext {
	digest, err := canonicalCommandDigest(message)
	if err != nil {
		panic(err)
	}
	return &commonv1.CommandContext{RequestId: "request-01", IdempotencyKey: "idempotency-01", PrincipalId: identity.Principal, TraceId: "trace-01", Deadline: timestamppb.New(fixtureTime.Add(time.Minute)), CanonicalRequestDigest: digest, TenantId: identity.TenantID, ProjectId: identity.ProjectID, CorrelationId: "correlation-01"}
}

func fixtureArtifact(character string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat(character, 64), MediaType: "application/vnd.mindclade.test+json", SizeBytes: 42}
}

func fixtureResource(kind, id string) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: kind, ResourceId: id, TenantId: "tenant-01", ProjectId: "project-01", Name: kind + "s/" + id}
}

type captureStream[T any] struct {
	ctx  context.Context //nolint:containedctx // The generated gRPC stream test double must implement Context without a method parameter.
	sent []*T
}

func (s *captureStream[T]) Send(value *T) error {
	s.sent = append(s.sent, value)
	return nil
}
func (*captureStream[T]) SetHeader(metadata.MD) error  { return nil }
func (*captureStream[T]) SendHeader(metadata.MD) error { return nil }
func (*captureStream[T]) SetTrailer(metadata.MD)       {}
func (s *captureStream[T]) Context() context.Context   { return s.ctx }
func (*captureStream[T]) SendMsg(any) error            { return nil }
func (*captureStream[T]) RecvMsg(any) error            { return nil }

func TestServerUsesAuthenticatedIdentityAndGeneratedCommand(t *testing.T) {
	identity := testIdentity()
	operation := &jobv1.Operation{OperationId: "operations/01", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Etag: "etag-01"}
	repository := &fakeRepository{operation: operation}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, fixedResolver{identity: identity}, codec, 10*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	server.withClock(fixedClock{value: fixtureTime})
	command := &trainingv1.CreateTrainingRunCommand{Project: fixtureResource("project", identity.ProjectID), TrainingRunId: "run-01", TrainingRecipe: fixtureArtifact("a"), DatasetRelease: fixtureResource("dataset_release", "data-01"), ModelRelease: fixtureResource("model_release", "model-01")}
	command.Context = commandContext(command, identity)
	response, err := server.CreateTrainingRun(context.Background(), &internaltrainingv1.CreateTrainingRunRequest{Command: command})
	if err != nil {
		t.Fatal(err)
	}
	if !repository.created || repository.identity != identity {
		t.Fatalf("repository did not receive authenticated identity: %#v", repository.identity)
	}
	if !proto.Equal(repository.command, command) {
		t.Fatal("repository did not receive generated command clone")
	}
	if repository.digest != command.GetContext().GetCanonicalRequestDigest() {
		t.Fatalf("digest=%s", repository.digest)
	}
	response.Operation.Etag = "mutated"
	if operation.GetEtag() != "etag-01" {
		t.Fatal("response aliases repository protobuf")
	}
}

func TestServerRejectsCommandIdentitySpoofBeforeRepository(t *testing.T) {
	identity := testIdentity()
	repository := &fakeRepository{operation: &jobv1.Operation{OperationId: "operations/01"}}
	codec, _ := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	server, _ := NewServer(repository, fixedResolver{identity: identity}, codec, 10*time.Millisecond)
	server.withClock(fixedClock{value: fixtureTime})
	command := &trainingv1.CreateTrainingRunCommand{Project: fixtureResource("project", identity.ProjectID), TrainingRunId: "run-01", TrainingRecipe: fixtureArtifact("a"), DatasetRelease: fixtureResource("dataset_release", "data-01"), ModelRelease: fixtureResource("model_release", "model-01")}
	command.Context = commandContext(command, identity)
	command.Context.PrincipalId = "attacker"
	_, err := server.CreateTrainingRun(context.Background(), &internaltrainingv1.CreateTrainingRunRequest{Command: command})
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("status=%v err=%v", status.Code(err), err)
	}
	if repository.created {
		t.Fatal("repository invoked for spoofed identity")
	}
}

func TestServerRejectsExpiredCommandBeforeRepository(t *testing.T) {
	identity := testIdentity()
	repository := &fakeRepository{operation: &jobv1.Operation{OperationId: "operations/01"}}
	codec, _ := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	server, _ := NewServer(repository, fixedResolver{identity: identity}, codec, 10*time.Millisecond)
	server.withClock(fixedClock{value: fixtureTime})
	command := &trainingv1.CreateTrainingRunCommand{Project: fixtureResource("project", identity.ProjectID), TrainingRunId: "run-01", TrainingRecipe: fixtureArtifact("a"), DatasetRelease: fixtureResource("dataset_release", "data-01"), ModelRelease: fixtureResource("model_release", "model-01")}
	command.Context = commandContext(command, identity)
	command.Context.Deadline = timestamppb.New(fixtureTime.Add(-time.Second))
	_, err := server.CreateTrainingRun(context.Background(), &internaltrainingv1.CreateTrainingRunRequest{Command: command})
	if status.Code(err) != codes.DeadlineExceeded {
		t.Fatalf("status=%v err=%v", status.Code(err), err)
	}
	if repository.created {
		t.Fatal("repository invoked after command deadline")
	}
}

func TestWorkerStartRequiresExplicitDeadlineAndScopedCapability(t *testing.T) {
	identity := testIdentity()
	codec, _ := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	server, _ := NewServer(&fakeRepository{}, fixedResolver{identity: identity}, codec, 10*time.Millisecond)
	server.withClock(fixedClock{value: fixtureTime})
	tokenDigest := sha256.Sum256([]byte(identity.LeaseToken))
	command := &trainingv1.StartTrainingAttemptCommand{
		TrainingRun: fixtureResource("training_run", "run-01"),
		Fence: &jobv1.LeaseFence{
			JobId: "jobs/01", RunId: "runs/01", AttemptId: "attempts/01", LeaseEpoch: 1,
			TenantId: identity.TenantID, ProjectId: identity.ProjectID,
			Deadline: timestamppb.New(fixtureTime.Add(time.Minute)), LeaseTokenDigest: "sha256:" + hex.EncodeToString(tokenDigest[:]),
		},
		DelegatedCapability: fixtureResource("delegated_capability", "capability-01"),
	}
	command.Context = commandContext(command, identity)
	_, err := server.StartTrainingAttempt(context.Background(), &internaltrainingv1.StartTrainingAttemptRequest{Command: command})
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("missing explicit deadline status=%v err=%v", status.Code(err), err)
	}
	command.Deadline = timestamppb.New(fixtureTime.Add(time.Minute))
	command.DelegatedCapability.TenantId = "other-tenant"
	command.Context = commandContext(command, identity)
	_, err = server.StartTrainingAttempt(context.Background(), &internaltrainingv1.StartTrainingAttemptRequest{Command: command})
	if status.Code(err) != codes.PermissionDenied {
		t.Fatalf("cross-tenant capability status=%v err=%v", status.Code(err), err)
	}
}

func TestCanonicalDigestOmitsContextAndDetectsContentChange(t *testing.T) {
	command := &trainingv1.CancelTrainingRunCommand{TrainingRunName: "trainingRuns/01", Etag: "etag-1", Reason: "stop"}
	first, err := canonicalCommandDigest(command)
	if err != nil {
		t.Fatal(err)
	}
	command.Context = &commonv1.CommandContext{RequestId: "different"}
	second, _ := canonicalCommandDigest(command)
	if first != second {
		t.Fatal("context changed canonical digest")
	}
	command.Reason = "different"
	third, _ := canonicalCommandDigest(command)
	if first == third {
		t.Fatal("content change did not change canonical digest")
	}
}

func TestPageTokensAreSignedAndQueryBound(t *testing.T) {
	codec, _ := NewPageTokenCodec([]byte(strings.Repeat("k", 32)))
	encoded, err := codec.encode(pageToken{Kind: "training-runs", Tenant: "tenant-01", Project: "project-01", Filter: "state=RUNNING", Order: "create_time desc,name desc", AfterTime: fixtureTime.Format(time.RFC3339Nano), AfterName: "trainingRuns/01"})
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := codec.decode(encoded, pageToken{Kind: "training-runs", Tenant: "tenant-01", Project: "project-01", Filter: "state=RUNNING", Order: "create_time desc,name desc"})
	if err != nil || decoded.AfterName != "trainingRuns/01" {
		t.Fatalf("decoded=%#v err=%v", decoded, err)
	}
	tampered := encoded[:len(encoded)-1] + "A"
	if _, err = codec.decode(tampered, pageToken{Kind: "training-runs", Tenant: "tenant-01", Project: "project-01", Filter: "state=RUNNING", Order: "create_time desc,name desc"}); err == nil {
		t.Fatal("tampered token accepted")
	}
	if _, err = codec.decode(encoded, pageToken{Kind: "training-runs", Tenant: "tenant-02", Project: "project-01", Filter: "state=RUNNING", Order: "create_time desc,name desc"}); err == nil {
		t.Fatal("cross-tenant token accepted")
	}
}

func TestProgressMustAdvanceEveryMonotonicFrontier(t *testing.T) {
	previous := &trainingv1.TrainingProgress{TrainingRunName: "trainingRuns/01", ProgressRevision: 3, CommittedUpdateCount: 10, CommittedSampleCount: 100, CommittedTokenCount: 1000, EffectiveWorkUnits: 9, LatestCommittedUpdate: &trainingv1.UpdateId{Value: "u10", Sequence: 10}, CommittedAt: timestamppb.New(fixtureTime)}
	next := clone(previous)
	next.ProgressRevision++
	next.CommittedUpdateCount++
	next.CommittedSampleCount++
	next.CommittedTokenCount++
	next.EffectiveWorkUnits++
	next.LatestCommittedUpdate.Sequence++
	next.CommittedAt = timestamppb.New(fixtureTime.Add(time.Second))
	if err := monotonicProgress(previous, next); err != nil {
		t.Fatal(err)
	}
	next.CommittedSampleCount = 99
	if err := monotonicProgress(previous, next); !errors.Is(err, ErrNonMonotonicProgress) {
		t.Fatalf("err=%v", err)
	}
}

func TestProgressCannotRegressCommittedDataRange(t *testing.T) {
	previous := &trainingv1.TrainingProgress{
		TrainingRunName: "trainingRuns/01", ProgressRevision: 1, CommittedAt: timestamppb.New(fixtureTime),
		LatestDataRange: &trainingv1.DataProgressRange{DatasetRelease: fixtureResource("dataset_release", "data-01"), SplitName: "train", PartitionId: "part-01", StartOrdinal: 10, EndOrdinalExclusive: 20, BatchReceipt: fixtureArtifact("a")},
	}
	next := clone(previous)
	next.ProgressRevision = 2
	next.CommittedAt = timestamppb.New(fixtureTime.Add(time.Second))
	next.LatestDataRange.EndOrdinalExclusive = 19
	if err := monotonicProgress(previous, next); !errors.Is(err, ErrNonMonotonicProgress) {
		t.Fatalf("err=%v", err)
	}
}

func TestCheckpointEvidenceMustBindManifest(t *testing.T) {
	manifest := fixtureArtifact("a")
	evidence := &artifactv1.EvidenceRef{Digest: "sha256:" + strings.Repeat("b", 64), SubjectDigest: manifest.GetDigest(), EvidenceKind: "checkpoint-verification", PolicyDigest: "sha256:" + strings.Repeat("c", 64)}
	if err := validateVerificationEvidence(evidence, manifest.GetDigest()); err != nil {
		t.Fatal(err)
	}
	evidence.SubjectDigest = "sha256:" + strings.Repeat("d", 64)
	if err := validateVerificationEvidence(evidence, manifest.GetDigest()); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("err=%v", err)
	}
}

func TestTerminalResultInvariants(t *testing.T) {
	command := &trainingv1.CompleteTrainingRunCommand{Classification: trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED}
	if err := validateTerminalCommand(command); !errors.Is(err, ErrInvalidArgument) {
		t.Fatalf("success without artifacts err=%v", err)
	}
	command.ResultManifest = fixtureArtifact("a")
	command.FinalCheckpoint = fixtureResource("checkpoint", "checkpoint-01")
	if err := validateTerminalCommand(command); err != nil {
		t.Fatal(err)
	}
}

func TestGeneratedTrainingEventsAreRegisteredAndPayloadSafe(t *testing.T) {
	identity := testIdentity()
	fenceDigest := sha256.Sum256([]byte(identity.LeaseToken))
	fence := &jobv1.LeaseFence{JobId: "jobs/01", RunId: "runs/01", AttemptId: "attempts/01", LeaseEpoch: 1, Deadline: timestamppb.New(fixtureTime.Add(time.Minute)), TenantId: identity.TenantID, ProjectId: identity.ProjectID, LeaseTokenDigest: "sha256:" + hex.EncodeToString(fenceDigest[:])}
	progress := &trainingv1.TrainingProgress{TrainingRunName: "trainingRuns/01", ProgressRevision: 1, CommittedAt: timestamppb.New(fixtureTime)}
	run := &trainingv1.TrainingRun{Name: "trainingRuns/01", Uid: "uid-01", Revision: 4, Etag: "etag-4", TenantName: "tenants/tenant-01", ProjectName: "tenants/tenant-01/projects/project-01", State: trainingv1.TrainingRunState_TRAINING_RUN_STATE_RUNNING, TrainingRecipe: fixtureArtifact("a"), DatasetRelease: fixtureResource("dataset_release", "data-01"), ModelRelease: fixtureResource("model_release", "model-01"), ActiveFence: fence, CommittedProgress: progress, CreateTime: timestamppb.New(fixtureTime), CompleteTime: timestamppb.New(fixtureTime)}
	operation := &jobv1.Operation{OperationId: "operations/01", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 4, Etag: "op-etag"}
	checkpoint := &trainingv1.Checkpoint{Name: "trainingRuns/01/checkpoints/1", Revision: 2, SnapshotEpoch: 1, CheckpointManifest: fixtureArtifact("b"), CommittedProgress: progress, CommitTime: timestamppb.New(fixtureTime)}
	context := &commonv1.CommandContext{RequestId: "request-01", TraceId: "trace-01", CorrelationId: "correlation-01"}
	factory := GeneratedEventFactory{}
	events := []struct {
		name  string
		build func() (*commonv1.EventEnvelope, error)
	}{{"created", func() (*commonv1.EventEnvelope, error) {
		return factory.Created(identity, run, operation, context, fixtureTime)
	}}, {"started", func() (*commonv1.EventEnvelope, error) {
		return factory.Started(identity, run, fence, context, fixtureTime)
	}}, {"progress", func() (*commonv1.EventEnvelope, error) {
		return factory.Progress(identity, run, progress, fence, context, fixtureTime)
	}}, {"checkpoint", func() (*commonv1.EventEnvelope, error) {
		return factory.Checkpoint(identity, run, checkpoint, fence, context, fixtureTime)
	}}, {"completed", func() (*commonv1.EventEnvelope, error) {
		return factory.Completed(identity, run, fence, context, fixtureTime)
	}}, {"cancel", func() (*commonv1.EventEnvelope, error) {
		return factory.CancellationRequested(identity, run, operation, "requested", context, fixtureTime)
	}}}
	for _, test := range events {
		t.Run(test.name, func(t *testing.T) {
			envelope, err := test.build()
			if err != nil {
				t.Fatal(err)
			}
			if err = queue.ValidateEnvelope(envelope); err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(envelope.GetPayload()), identity.LeaseToken) {
				t.Fatal("raw lease token leaked into event")
			}
		})
	}
	if got := operationResource(operation).GetResourceId(); got != "01" {
		t.Fatalf("operation resource id=%q", got)
	}
}

func TestRegisterInstallsGeneratedTrainingAndOperationServices(t *testing.T) {
	identity := testIdentity()
	codec, _ := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	server, _ := NewServer(&fakeRepository{}, fixedResolver{identity: identity}, codec, 10*time.Millisecond)
	registrar := grpc.NewServer()
	Register(registrar, server)
	services := registrar.GetServiceInfo()
	for _, name := range []string{"mindclade.internal.training.v1.TrainingService", "mindclade.internal.job.v1.OperationService"} {
		if _, ok := services[name]; !ok {
			t.Fatalf("service %s was not registered", name)
		}
	}
}

func TestWatchTrainingRunResumesAndTerminatesWithoutPolling(t *testing.T) {
	identity := testIdentity()
	run := &trainingv1.TrainingRun{Name: "trainingRuns/01", Revision: 4, State: trainingv1.TrainingRunState_TRAINING_RUN_STATE_COMPLETED, Etag: "etag-4"}
	codec, _ := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	server, _ := NewServer(&fakeRepository{run: run}, fixedResolver{identity: identity}, codec, 10*time.Millisecond)
	server.withClock(fixedClock{value: fixtureTime})
	stream := &captureStream[internaltrainingv1.WatchTrainingRunResponse]{ctx: context.Background()}
	if err := server.WatchTrainingRun(&internaltrainingv1.WatchTrainingRunRequest{Name: run.GetName(), AfterSequence: 3}, stream); err != nil {
		t.Fatal(err)
	}
	if len(stream.sent) != 1 || stream.sent[0].GetSequence() != 4 || !proto.Equal(stream.sent[0].GetTrainingRun(), run) {
		t.Fatalf("stream responses=%v", stream.sent)
	}
	stream.sent = nil
	if err := server.WatchTrainingRun(&internaltrainingv1.WatchTrainingRunRequest{Name: run.GetName(), AfterSequence: 4}, stream); err != nil {
		t.Fatal(err)
	}
	if len(stream.sent) != 0 {
		t.Fatalf("terminal acknowledged sequence emitted %d responses", len(stream.sent))
	}
	err := server.WatchTrainingRun(&internaltrainingv1.WatchTrainingRunRequest{Name: run.GetName(), AfterSequence: 5}, stream)
	if status.Code(err) != codes.FailedPrecondition {
		t.Fatalf("future cursor status=%v err=%v", status.Code(err), err)
	}
}

func TestWatchOperationStreamsEveryDurableRevisionInOrder(t *testing.T) {
	identity := testIdentity()
	revisions := []*jobv1.Operation{
		{OperationId: "operations/01", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 2, State: jobv1.OperationState_OPERATION_STATE_RUNNING},
		{OperationId: "operations/01", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 3, State: jobv1.OperationState_OPERATION_STATE_CANCELLING},
		{OperationId: "operations/01", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 4, State: jobv1.OperationState_OPERATION_STATE_CANCELLED, Done: true},
	}
	codec, _ := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	server, err := NewServer(&fakeRepository{revisions: revisions}, fixedResolver{identity: identity}, codec, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	server.withClock(fixedClock{value: fixtureTime})
	stream := &captureStream[internaljobv1.WatchOperationResponse]{ctx: context.Background()}
	if err := server.WatchOperation(&internaljobv1.WatchOperationRequest{Name: "operations/01", AfterSequence: 1}, stream); err != nil {
		t.Fatal(err)
	}
	if len(stream.sent) != 3 {
		t.Fatalf("operation watch emitted %d revisions, want 3", len(stream.sent))
	}
	for index, response := range stream.sent {
		want := uint64(index + 2)
		if response.GetSequence() != want || uint64(response.GetOperation().GetResourceVersion()) != want { //nolint:gosec // Deterministic test fixture values are nonnegative and bounded before conversion.
			t.Fatalf("response %d = %v", index, response)
		}
	}
}

func TestWatchOperationMapsResumeFailuresDistinctly(t *testing.T) {
	identity := testIdentity()
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name string
		err  error
		code codes.Code
	}{
		{name: "ahead", err: ErrCursorAhead, code: codes.FailedPrecondition},
		{name: "expired", err: ErrCursorExpired, code: codes.OutOfRange},
		{name: "history gap", err: ErrOperationHistoryGap, code: codes.DataLoss},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server, serverErr := NewServer(&fakeRepository{historyErr: test.err}, fixedResolver{identity: identity}, codec, time.Second)
			if serverErr != nil {
				t.Fatal(serverErr)
			}
			stream := &captureStream[internaljobv1.WatchOperationResponse]{ctx: context.Background()}
			watchErr := server.WatchOperation(&internaljobv1.WatchOperationRequest{Name: "operations/01", AfterSequence: 1}, stream)
			if got := status.Code(watchErr); got != test.code {
				t.Fatalf("status=%s want=%s err=%v", got, test.code, watchErr)
			}
		})
	}
}

func TestOperationCursorIsSignedAndResourceBound(t *testing.T) {
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("c", 32)))
	if err != nil {
		t.Fatal(err)
	}
	name := "tenants/t-1/projects/p-1/operations/op-1"
	cursor, err := codec.EncodeOperationCursor(name, 7)
	if err != nil {
		t.Fatal(err)
	}
	if revision, decodeErr := codec.DecodeOperationCursor(cursor, name); decodeErr != nil || revision != 7 {
		t.Fatalf("decode revision=%d err=%v", revision, decodeErr)
	}
	if _, decodeErr := codec.DecodeOperationCursor(cursor, "tenants/t-1/projects/p-1/operations/op-2"); !errors.Is(decodeErr, ErrCursorResource) {
		t.Fatalf("cross-resource cursor err=%v", decodeErr)
	}
	tampered := cursor[:len(cursor)-1] + "A"
	if _, decodeErr := codec.DecodeOperationCursor(tampered, name); !errors.Is(decodeErr, ErrCursorMalformed) {
		t.Fatalf("tampered cursor err=%v", decodeErr)
	}
}
