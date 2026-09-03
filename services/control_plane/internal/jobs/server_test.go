package jobs

import (
	"context"
	"database/sql"
	"errors"
	"net"
	"os"
	"sort"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	platformdb "github.com/mindclade/mindclade/libs/go/persistence"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	featurev1 "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

type metadataWorkerResolver struct{}

func (metadataWorkerResolver) ResolveWorker(ctx context.Context) (WorkerIdentity, error) {
	values, _ := metadata.FromIncomingContext(ctx)
	return WorkerIdentity{
		TenantID: "tenant-01", ProjectID: "project-01", Principal: "worker-principal-01", WorkerID: "worker-01",
		LeaseToken: firstMetadata(values.Get(leaseTokenHeader)),
	}, nil
}

func TestBindDomainCompletionUsesGeneratedOneofAndOuterAuthority(t *testing.T) {
	t.Parallel()
	fence := &jobv1.LeaseFence{JobId: "jobs/1", RunId: "runs/1", AttemptId: "attempts/1", LeaseEpoch: 1}
	outer := &commonv1.CommandContext{TenantId: "tenant-1", ProjectId: "project-1", PrincipalId: "principal-1", RequestId: "request-1", IdempotencyKey: "key-1"}
	nested := &featurev1.CommitFeatureMaterializationCommand{
		Context: &commonv1.CommandContext{TenantId: "untrusted"}, MaterializationName: "materializations/1", Fence: proto.Clone(fence).(*jobv1.LeaseFence),
	}
	request := &internaljobv1.CommitAttemptRequest{
		Context: outer, Fence: fence,
		DomainCompletion: &internaljobv1.CommitAttemptRequest_FeatureMaterialization{FeatureMaterialization: nested},
	}
	feature, transform, err := bindDomainCompletion(request)
	if err != nil || feature == nil || transform != nil || !proto.Equal(feature.GetContext(), outer) || feature == nested {
		t.Fatalf("generated feature oneof binding: feature=%v transform=%v err=%v", feature, transform, err)
	}
	outer.RequestId = "caller-mutated"
	nested.MaterializationName = "caller-mutated"
	if feature.GetContext().GetRequestId() == "caller-mutated" || feature.GetMaterializationName() == "caller-mutated" {
		t.Fatal("domain completion binding retained mutable or nested authority aliases")
	}
	mismatched := proto.Clone(fence).(*jobv1.LeaseFence)
	mismatched.LeaseEpoch++
	request.Fence = mismatched
	if _, _, err = bindDomainCompletion(request); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("mismatched nested fence status=%v err=%v", status.Code(err), err)
	}
}

type runRepositoryFixture struct {
	token        string
	acquireCount int
	attempt      *jobv1.Attempt
	fence        *jobv1.LeaseFence
	cancel       *CancelAttemptCommand
}

func (*runRepositoryFixture) GetRunSQL(context.Context, string, string, string) (*jobv1.Run, error) {
	return nil, ErrNotFound
}

func (*runRepositoryFixture) ListRunsSQL(context.Context, string, string, string, string, int) ([]*jobv1.Run, bool, time.Time, error) {
	return nil, false, time.Time{}, nil
}

func (*runRepositoryFixture) GetAttemptSQL(context.Context, string, string, string) (*jobv1.Attempt, error) {
	return nil, ErrNotFound
}

func (*runRepositoryFixture) ListAttemptsSQL(context.Context, string, string, string, string, int) ([]*jobv1.Attempt, bool, time.Time, error) {
	return nil, false, time.Time{}, nil
}

func (r *runRepositoryFixture) AcquireLeaseSQL(_ context.Context, command AcquireLeaseCommand) (*LeaseMutationResult, error) {
	if r.attempt != nil {
		return &LeaseMutationResult{
			Attempt: cloneAttempt(r.attempt), Fence: cloneFence(r.fence), TokenKeyID: command.TokenKeyID, Replay: true,
		}, nil
	}
	r.acquireCount++
	r.token = command.Token
	digest, err := LeaseTokenDigest(command.Token)
	if err != nil {
		return nil, err
	}
	attempt := &jobv1.Attempt{
		AttemptId: command.AttemptID, RunId: command.RunID, JobId: "job-01", TenantId: command.TenantID,
		ProjectId: "project-01", WorkerId: command.WorkerID, LeaseEpoch: 1, ResourceVersion: 1,
	}
	fence := &jobv1.LeaseFence{
		AttemptId: command.AttemptID, RunId: command.RunID, JobId: "job-01", TenantId: command.TenantID,
		ProjectId: "project-01", LeaseEpoch: 1, LeaseTokenDigest: digest,
	}
	r.attempt, r.fence = cloneAttempt(attempt), cloneFence(fence)
	return &LeaseMutationResult{Attempt: attempt, Fence: fence, TokenKeyID: command.TokenKeyID}, nil
}

func (r *runRepositoryFixture) RenewLeaseSQL(_ context.Context, command RenewLeaseCommand) (*LeaseMutationResult, error) {
	if command.Credentials.Token != r.token {
		return nil, ErrInvalidLeaseToken
	}
	attempt := &jobv1.Attempt{
		AttemptId: command.Credentials.AttemptID, RunId: "run-01", JobId: "job-01", TenantId: command.Credentials.TenantID,
		ProjectId: "project-01", WorkerId: command.Credentials.WorkerID, LeaseEpoch: 1, ResourceVersion: 2,
	}
	fence := &jobv1.LeaseFence{
		AttemptId: command.Credentials.AttemptID, RunId: "run-01", JobId: "job-01", TenantId: command.Credentials.TenantID,
		ProjectId: "project-01", LeaseEpoch: 1,
	}
	return &LeaseMutationResult{Attempt: attempt, Fence: fence}, nil
}

func (r *runRepositoryFixture) HeartbeatLeaseSQL(ctx context.Context, command RenewLeaseCommand) (*LeaseMutationResult, error) {
	return r.RenewLeaseSQL(ctx, command)
}

func (r *runRepositoryFixture) CancelAttemptSQL(_ context.Context, command CancelAttemptCommand) (*AttemptMutationResult, error) {
	copy := command
	r.cancel = &copy
	attempt := &jobv1.Attempt{
		AttemptId: command.Credentials.AttemptID, RunId: "run-01", JobId: "job-01", TenantId: command.Credentials.TenantID,
		ProjectId: command.Credentials.ProjectID, WorkerId: command.Credentials.WorkerID, LeaseEpoch: command.Credentials.Epoch,
		State: jobv1.AttemptState_ATTEMPT_STATE_CANCELLED, ResourceVersion: command.ExpectedResourceVersion + 1,
	}
	run := &jobv1.Run{
		RunId: "run-01", JobId: "job-01", TenantId: command.Credentials.TenantID, ProjectId: command.Credentials.ProjectID,
		LeaseEpoch: command.Credentials.Epoch, State: jobv1.RunState_RUN_STATE_CANCELLED, ResourceVersion: 3,
	}
	return &AttemptMutationResult{Attempt: attempt, Run: run}, nil
}

func (*runRepositoryFixture) ExpireLeasesSQL(context.Context, ExpireLeasesCommand) (*ExpireLeasesResult, error) {
	return nil, errors.New("not called")
}

func (*runRepositoryFixture) CompleteAttemptSQL(context.Context, CompleteAttemptCommand) (*AttemptMutationResult, error) {
	return nil, errors.New("not called")
}

func TestRunServerIssuesAndAuthenticatesOpaqueLeaseToken(t *testing.T) {
	t.Parallel()
	repository := &runRepositoryFixture{}
	pages, err := NewRunPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatalf("page codec: %v", err)
	}
	issuer, err := NewHMACLeaseTokenIssuer("test-key", map[string][]byte{
		"test-key": []byte("0123456789abcdef0123456789abcdef"),
	})
	if err != nil {
		t.Fatalf("token issuer: %v", err)
	}
	server, err := NewRunServer(repository, metadataWorkerResolver{}, pages, issuer)
	if err != nil {
		t.Fatalf("run server: %v", err)
	}
	grpcServer := grpc.NewServer()
	internaljobv1.RegisterRunServiceServer(grpcServer, server)
	listener := bufconn.Listen(1 << 20)
	served := make(chan error, 1)
	go func() { served <- grpcServer.Serve(listener) }()
	t.Cleanup(func() {
		grpcServer.Stop()
		_ = listener.Close()
		if serveErr := <-served; serveErr != nil && !errors.Is(serveErr, grpc.ErrServerStopped) {
			t.Errorf("serve: %v", serveErr)
		}
	})
	connection, err := grpc.NewClient(
		"passthrough:///run-service-test",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatalf("client connection: %v", err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internaljobv1.NewRunServiceClient(connection)
	commandContext := &commonv1.CommandContext{
		TenantId: "tenant-01", ProjectId: "project-01", PrincipalId: "worker-principal-01",
		RequestId: "request-acquire-01", IdempotencyKey: "lease-01", Deadline: timestamppb.New(time.Now().Add(time.Minute)),
	}
	var headers metadata.MD
	acquired, err := client.AcquireAttemptLease(context.Background(), &internaljobv1.AcquireAttemptLeaseRequest{
		Context: commandContext, RunName: "runs/run-01", AttemptId: "attempt-01", LeaseDuration: durationpb.New(time.Minute),
	}, grpc.Header(&headers))
	if err != nil {
		t.Fatalf("acquire lease: %v", err)
	}
	token := firstMetadata(headers.Get(leaseTokenHeader))
	if len(token) < 32 || token != repository.token {
		t.Fatalf("response metadata did not carry the server-generated lease credential")
	}
	if acquired.GetFence().GetLeaseTokenDigest() == "" || acquired.GetFence().GetLeaseTokenDigest() == token {
		t.Fatalf("protobuf fence did not contain only the token digest: %v", acquired.GetFence())
	}
	var replayHeaders metadata.MD
	replayed, err := client.AcquireAttemptLease(context.Background(), &internaljobv1.AcquireAttemptLeaseRequest{
		Context: protoCloneCommandContext(commandContext), RunName: "runs/run-01", AttemptId: "attempt-01", LeaseDuration: durationpb.New(time.Minute),
	}, grpc.Header(&replayHeaders))
	if err != nil {
		t.Fatalf("replay acquire lease: %v", err)
	}
	if replayToken := firstMetadata(replayHeaders.Get(leaseTokenHeader)); replayToken != token || repository.acquireCount != 1 || !proto.Equal(acquired, replayed) {
		t.Fatalf("acquire retry mutated or changed credential: tokenEqual=%v mutations=%d equal=%v", replayToken == token, repository.acquireCount, proto.Equal(acquired, replayed))
	}
	renewContext := metadata.AppendToOutgoingContext(context.Background(), leaseTokenHeader, token)
	renewed, err := client.RenewAttemptLease(renewContext, &internaljobv1.RenewAttemptLeaseRequest{
		Context: &commonv1.CommandContext{
			TenantId: "tenant-01", ProjectId: "project-01", PrincipalId: "worker-principal-01",
			RequestId: "request-renew-01", IdempotencyKey: "renew-01", Deadline: timestamppb.New(time.Now().Add(time.Minute)),
		},
		Fence: acquired.GetFence(), LeaseDuration: durationpb.New(time.Minute), ExpectedResourceVersion: 1,
	})
	if err != nil {
		t.Fatalf("renew lease with opaque credential: %v", err)
	}
	if renewed.GetAttempt().GetResourceVersion() != 2 {
		t.Fatalf("renewed attempt = %v", renewed.GetAttempt())
	}
	cancelReason := "operator requested bounded shutdown"
	cancelled, err := client.CancelAttempt(renewContext, &internaljobv1.CancelAttemptRequest{
		Context: &commonv1.CommandContext{
			TenantId: "tenant-01", ProjectId: "project-01", PrincipalId: "worker-principal-01",
			RequestId: "request-cancel-01", IdempotencyKey: "cancel-01", Deadline: timestamppb.New(time.Now().Add(time.Minute)),
		},
		Fence: acquired.GetFence(), ExpectedResourceVersion: renewed.GetAttempt().GetResourceVersion(), Reason: cancelReason,
	})
	if err != nil {
		t.Fatalf("cancel attempt with reason: %v", err)
	}
	if cancelled.GetAttempt().GetState() != jobv1.AttemptState_ATTEMPT_STATE_CANCELLED || repository.cancel == nil || repository.cancel.Reason != cancelReason {
		t.Fatalf("cancellation reason was not preserved at the repository boundary: response=%v command=%v", cancelled, repository.cancel)
	}
}

type fixedJobIdentityResolver struct{ identity JobIdentity }

func (r fixedJobIdentityResolver) ResolveJob(context.Context) (JobIdentity, error) {
	return r.identity, nil
}

type fixedRunClock struct{ now time.Time }

func (c fixedRunClock) Now() time.Time { return c.now }

type jobReceipt struct {
	digest    string
	job       *jobv1.Job
	operation *operationv1.Operation
}

type jobRepositoryFixture struct {
	jobs     map[string]*jobv1.Job
	receipts map[string]jobReceipt
}

func newJobRepositoryFixture() *jobRepositoryFixture {
	return &jobRepositoryFixture{jobs: make(map[string]*jobv1.Job), receipts: make(map[string]jobReceipt)}
}

func (r *jobRepositoryFixture) RequestJobSQL(_ context.Context, job *jobv1.Job, operation *operationv1.Operation, command JobCommandMetadata) (*JobMutationResult, error) {
	if receipt, ok := r.receipts[command.IdempotencyKey]; ok {
		if receipt.digest != command.RequestDigest {
			return nil, ErrIdempotencyConflict
		}
		return &JobMutationResult{Job: cloneJob(receipt.job), Operation: proto.Clone(receipt.operation).(*operationv1.Operation), Replay: true}, nil
	}
	if _, ok := r.jobs[job.GetJobId()]; ok {
		return nil, ErrAlreadyExists
	}
	persisted := cloneJob(job)
	persisted.State = jobv1.JobState_JOB_STATE_QUEUED
	persisted.ResourceVersion = 2
	persisted.Etag = resourceETag(job.GetTenantId(), job.GetProjectId(), job.GetJobId(), 2)
	r.jobs[persisted.GetJobId()] = cloneJob(persisted)
	receipt := jobReceipt{digest: command.RequestDigest, job: cloneJob(persisted), operation: proto.Clone(operation).(*operationv1.Operation)}
	r.receipts[command.IdempotencyKey] = receipt
	return &JobMutationResult{Job: cloneJob(persisted), Operation: proto.Clone(operation).(*operationv1.Operation)}, nil
}

func (r *jobRepositoryFixture) GetJobSQL(_ context.Context, tenantID, projectID, jobID string) (*jobv1.Job, error) {
	job, ok := r.jobs[jobID]
	if !ok || job.GetTenantId() != tenantID || job.GetProjectId() != projectID {
		return nil, ErrNotFound
	}
	return cloneJob(job), nil
}

func (r *jobRepositoryFixture) ListJobsSQL(_ context.Context, tenantID, projectID, after string, limit int) ([]*jobv1.Job, bool, time.Time, error) {
	ids := make([]string, 0, len(r.jobs))
	for id, job := range r.jobs {
		if id > after && job.GetTenantId() == tenantID && job.GetProjectId() == projectID {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	more := len(ids) > limit
	if more {
		ids = ids[:limit]
	}
	values := make([]*jobv1.Job, 0, len(ids))
	for _, id := range ids {
		values = append(values, cloneJob(r.jobs[id]))
	}
	return values, more, time.Date(2026, time.September, 1, 12, 0, 0, 0, time.UTC), nil
}

func (r *jobRepositoryFixture) CancelJobSQL(_ context.Context, jobID, expectedETag, _ string, command JobCommandMetadata) (*JobMutationResult, error) {
	if receipt, ok := r.receipts[command.IdempotencyKey]; ok {
		if receipt.digest != command.RequestDigest {
			return nil, ErrIdempotencyConflict
		}
		return &JobMutationResult{Job: cloneJob(receipt.job), Operation: proto.Clone(receipt.operation).(*operationv1.Operation), Replay: true}, nil
	}
	job, ok := r.jobs[jobID]
	if !ok || job.GetTenantId() != command.TenantID || job.GetProjectId() != command.ProjectID {
		return nil, ErrNotFound
	}
	if job.GetEtag() != expectedETag {
		return nil, ErrVersionConflict
	}
	if job.GetState() != jobv1.JobState_JOB_STATE_QUEUED {
		return nil, ErrTerminalMutation
	}
	job = cloneJob(job)
	job.State = jobv1.JobState_JOB_STATE_CANCELLING
	job.ResourceVersion++
	job.Etag = resourceETag(job.GetTenantId(), job.GetProjectId(), job.GetJobId(), job.GetResourceVersion())
	r.jobs[jobID] = cloneJob(job)
	operation := &operationv1.Operation{
		OperationId: job.GetOperationId(), JobId: jobID, TenantId: job.GetTenantId(), ProjectId: job.GetProjectId(),
		State: operationv1.OperationState_OPERATION_STATE_CANCELLING, ResourceVersion: 2,
		Etag: resourceETag(job.GetTenantId(), job.GetProjectId(), job.GetOperationId(), 2),
	}
	r.receipts[command.IdempotencyKey] = jobReceipt{digest: command.RequestDigest, job: cloneJob(job), operation: proto.Clone(operation).(*operationv1.Operation)}
	return &JobMutationResult{Job: cloneJob(job), Operation: operation}, nil
}

func TestJobServiceNetworkLifecycleIdempotencyAndPagination(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, time.September, 1, 12, 0, 0, 0, time.UTC)
	identity := JobIdentity{TenantID: "tenant-01", ProjectID: "project-01", Principal: "principal-01"}
	repository := newJobRepositoryFixture()
	pages, err := NewRunPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatalf("page codec: %v", err)
	}
	server, err := NewJobServer(repository, fixedJobIdentityResolver{identity: identity}, pages)
	if err != nil {
		t.Fatalf("job server: %v", err)
	}
	server.clock = fixedRunClock{now: now}
	grpcServer := grpc.NewServer()
	internaljobv1.RegisterJobServiceServer(grpcServer, server)
	listener := bufconn.Listen(1 << 20)
	served := make(chan error, 1)
	go func() { served <- grpcServer.Serve(listener) }()
	t.Cleanup(func() {
		grpcServer.Stop()
		_ = listener.Close()
		if serveErr := <-served; serveErr != nil && !errors.Is(serveErr, grpc.ErrServerStopped) {
			t.Errorf("serve: %v", serveErr)
		}
	})
	connection, err := grpc.NewClient("passthrough:///job-service-test",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("client connection: %v", err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internaljobv1.NewJobServiceClient(connection)
	newCommand := func(id, key, kind string) *jobv1.RequestJobCommand {
		return &jobv1.RequestJobCommand{
			Context: &commonv1.CommandContext{
				TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal,
				RequestId: "request-" + key, IdempotencyKey: key, Deadline: timestamppb.New(now.Add(time.Minute)),
			},
			RequestedJobId: id, JobKind: kind,
			Configuration: &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/json"},
		}
	}
	created, err := client.RequestJob(context.Background(), &internaljobv1.RequestJobRequest{Command: newCommand("alpha", "create-alpha", "training")})
	if err != nil {
		t.Fatalf("request job: %v", err)
	}
	if created.GetJob().GetJobId() != "jobs/alpha" || created.GetJob().GetState() != jobv1.JobState_JOB_STATE_QUEUED || created.GetOperation().GetJobId() != "jobs/alpha" {
		t.Fatalf("unexpected accepted job: %v operation=%v", created.GetJob(), created.GetOperation())
	}
	replayCommand := newCommand("alpha", "create-alpha", "training")
	replayCommand.Context.RequestId = "transport-retry"
	replayCommand.Context.Deadline = timestamppb.New(now.Add(2 * time.Minute))
	replayed, err := client.RequestJob(context.Background(), &internaljobv1.RequestJobRequest{Command: replayCommand})
	if err != nil || !proto.Equal(created, replayed) {
		t.Fatalf("idempotent replay changed response: replay=%v err=%v", replayed, err)
	}
	if _, err = client.RequestJob(context.Background(), &internaljobv1.RequestJobRequest{Command: newCommand("alpha", "create-alpha", "evaluation")}); status.Code(err) != codes.AlreadyExists {
		t.Fatalf("changed command reused key: code=%v err=%v", status.Code(err), err)
	}
	created.Job.JobKind = "caller-mutated"
	loaded, err := client.GetJob(context.Background(), &internaljobv1.GetJobRequest{Name: "tenants/tenant-01/projects/project-01/jobs/alpha"})
	if err != nil || loaded.GetJob().GetJobKind() != "training" {
		t.Fatalf("clone-safe get: job=%v err=%v", loaded.GetJob(), err)
	}
	if _, err = client.RequestJob(context.Background(), &internaljobv1.RequestJobRequest{Command: newCommand("beta", "create-beta", "training")}); err != nil {
		t.Fatalf("request second job: %v", err)
	}
	firstPage, err := client.ListJobs(context.Background(), &internaljobv1.ListJobsRequest{
		Parent: "tenants/tenant-01/projects/project-01", Page: &commonv1.PageRequest{PageSize: 1}, OrderBy: "job_id",
	})
	if err != nil || len(firstPage.GetJobs()) != 1 || firstPage.GetPage().GetNextPageToken() == "" {
		t.Fatalf("first job page: response=%v err=%v", firstPage, err)
	}
	secondPage, err := client.ListJobs(context.Background(), &internaljobv1.ListJobsRequest{
		Parent: "tenants/tenant-01/projects/project-01", Page: &commonv1.PageRequest{PageSize: 1, PageToken: firstPage.GetPage().GetNextPageToken()}, OrderBy: "job_id",
	})
	if err != nil || len(secondPage.GetJobs()) != 1 || secondPage.GetJobs()[0].GetJobId() == firstPage.GetJobs()[0].GetJobId() {
		t.Fatalf("second job page: response=%v err=%v", secondPage, err)
	}
	if _, err = client.ListJobs(context.Background(), &internaljobv1.ListJobsRequest{
		Parent: "tenants/tenant-01/projects/project-01", Page: &commonv1.PageRequest{PageToken: firstPage.GetPage().GetNextPageToken() + "x"},
	}); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("tampered cursor code=%v err=%v", status.Code(err), err)
	}
	cancel := &internaljobv1.CancelJobRequest{
		Context: &commonv1.CommandContext{
			TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal,
			RequestId: "request-cancel", IdempotencyKey: "cancel-alpha", Deadline: timestamppb.New(now.Add(time.Minute)),
		},
		Name: "jobs/alpha", Etag: "stale", Reason: "operator request",
	}
	if _, err = client.CancelJob(context.Background(), cancel); status.Code(err) != codes.Aborted {
		t.Fatalf("stale etag code=%v err=%v", status.Code(err), err)
	}
	cancel.Etag = loaded.GetJob().GetEtag()
	cancelled, err := client.CancelJob(context.Background(), cancel)
	if err != nil || cancelled.GetOperation().GetState() != operationv1.OperationState_OPERATION_STATE_CANCELLING {
		t.Fatalf("cancel job: response=%v err=%v", cancelled, err)
	}
	cancelReplay := proto.Clone(cancel).(*internaljobv1.CancelJobRequest)
	cancelReplay.Context.RequestId = "request-cancel-retry"
	cancelReplay.Context.Deadline = timestamppb.New(now.Add(2 * time.Minute))
	replayedCancel, err := client.CancelJob(context.Background(), cancelReplay)
	if err != nil || !proto.Equal(cancelled, replayedCancel) {
		t.Fatalf("cancel replay changed result: response=%v err=%v", replayedCancel, err)
	}
}

func TestJobServicePostgresNetworkAtomicLifecycle(t *testing.T) {
	dsn := os.Getenv("MINDCLADE_TEST_POSTGRES_DSN")
	if dsn == "" {
		if os.Getenv("MINDCLADE_REQUIRE_POSTGRES_INTEGRATION") == "1" {
			t.Fatal("MINDCLADE_TEST_POSTGRES_DSN is required")
		}
		t.Skip("PostgreSQL integration DSN is not configured")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("open PostgreSQL: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		t.Fatalf("ping PostgreSQL: %v", err)
	}
	suffix := strings.ReplaceAll(time.Now().UTC().Format("20060102150405.000000000"), ".", "")
	tenantID := "tenant-job-service-" + suffix
	identity := JobIdentity{TenantID: tenantID, ProjectID: "project-a", Principal: "principal-a"}
	t.Cleanup(func() {
		cleanupContext, cleanupCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cleanupCancel()
		tx, cleanupErr := platformdb.BeginTenantTx(cleanupContext, db, tenantID, nil)
		if cleanupErr != nil {
			t.Errorf("begin cleanup: %v", cleanupErr)
			return
		}
		defer func() { _ = tx.Rollback() }()
		for _, table := range []string{"outbox_messages", "audit_events", "idempotency_records", "operation_revisions", "operations", "jobs", "artifact_references"} {
			if _, cleanupErr = tx.ExecContext(cleanupContext, "DELETE FROM "+table+" WHERE tenant_id=$1", tenantID); cleanupErr != nil { //nolint:gosec // SQL structure is selected from closed validated identifiers; values remain bound parameters.
				t.Errorf("cleanup %s: %v", table, cleanupErr)
				return
			}
		}
		if cleanupErr = tx.Commit(); cleanupErr != nil {
			t.Errorf("commit cleanup: %v", cleanupErr)
		}
	})
	pages, err := NewRunPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatalf("page codec: %v", err)
	}
	postgresRepository := SQLRepository{DB: db}
	server, err := NewJobServer(postgresRepository, fixedJobIdentityResolver{identity: identity}, pages)
	if err != nil {
		t.Fatalf("job server: %v", err)
	}
	grpcServer := grpc.NewServer()
	internaljobv1.RegisterJobServiceServer(grpcServer, server)
	listener := bufconn.Listen(1 << 20)
	served := make(chan error, 1)
	go func() { served <- grpcServer.Serve(listener) }()
	t.Cleanup(func() {
		grpcServer.Stop()
		_ = listener.Close()
		if serveErr := <-served; serveErr != nil && !errors.Is(serveErr, grpc.ErrServerStopped) {
			t.Errorf("serve: %v", serveErr)
		}
	})
	connection, err := grpc.NewClient("passthrough:///postgres-job-service-test",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("client connection: %v", err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internaljobv1.NewJobServiceClient(connection)
	command := func(projectID, key string) *jobv1.RequestJobCommand {
		return &jobv1.RequestJobCommand{
			Context: &commonv1.CommandContext{
				TenantId: tenantID, ProjectId: projectID, PrincipalId: "principal-a", RequestId: "request-" + key,
				IdempotencyKey: key, Deadline: timestamppb.New(time.Now().UTC().Add(time.Minute)),
			},
			RequestedJobId: "shared", JobKind: "training",
			Configuration: &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("c", 64), MediaType: "application/vnd.mindclade.training+json"},
		}
	}
	created, err := client.RequestJob(ctx, &internaljobv1.RequestJobRequest{Command: command("project-a", "shared-key")})
	if err != nil {
		t.Fatalf("request PostgreSQL job: %v", err)
	}
	if created.GetJob().GetState() != jobv1.JobState_JOB_STATE_QUEUED || created.GetJob().GetResourceVersion() != 2 {
		t.Fatalf("persisted job did not reach queued revision: %v", created.GetJob())
	}
	replayed, err := client.RequestJob(ctx, &internaljobv1.RequestJobRequest{Command: command("project-a", "shared-key")})
	if err != nil || !proto.Equal(created, replayed) {
		t.Fatalf("PostgreSQL replay changed response: response=%v err=%v", replayed, err)
	}
	conflict := command("project-a", "shared-key")
	conflict.JobKind = "evaluation"
	if _, err = client.RequestJob(ctx, &internaljobv1.RequestJobRequest{Command: conflict}); status.Code(err) != codes.AlreadyExists {
		t.Fatalf("PostgreSQL digest conflict code=%v err=%v", status.Code(err), err)
	}
	loaded, err := client.GetJob(ctx, &internaljobv1.GetJobRequest{Name: "tenants/" + tenantID + "/projects/project-a/jobs/shared"})
	if err != nil || loaded.GetJob().GetJobId() != "jobs/shared" {
		t.Fatalf("get PostgreSQL job: response=%v err=%v", loaded, err)
	}
	cancelRequest := &internaljobv1.CancelJobRequest{
		Context: &commonv1.CommandContext{
			TenantId: tenantID, ProjectId: "project-a", PrincipalId: "principal-a", RequestId: "request-cancel",
			IdempotencyKey: "cancel-shared", Deadline: timestamppb.New(time.Now().UTC().Add(time.Minute)),
		},
		Name: "jobs/shared", Etag: loaded.GetJob().GetEtag(), Reason: "qualification",
	}
	cancelled, err := client.CancelJob(ctx, cancelRequest)
	if err != nil || cancelled.GetOperation().GetState() != operationv1.OperationState_OPERATION_STATE_CANCELLING || cancelled.GetOperation().GetResourceVersion() != 2 {
		t.Fatalf("cancel PostgreSQL job: response=%v err=%v", cancelled, err)
	}
	replayedCancel, err := client.CancelJob(ctx, proto.Clone(cancelRequest).(*internaljobv1.CancelJobRequest))
	if err != nil || !proto.Equal(cancelled, replayedCancel) {
		t.Fatalf("PostgreSQL cancel replay changed response: response=%v err=%v", replayedCancel, err)
	}
	otherIdentity := JobIdentity{TenantID: tenantID, ProjectID: "project-b", Principal: "principal-a"}
	otherServer, err := NewJobServer(SQLRepository{DB: db}, fixedJobIdentityResolver{identity: otherIdentity}, pages)
	if err != nil {
		t.Fatal(err)
	}
	other, err := otherServer.RequestJob(ctx, &internaljobv1.RequestJobRequest{Command: command("project-b", "shared-key")})
	if err != nil || other.GetJob().GetJobId() != "jobs/shared" || other.GetJob().GetProjectId() != "project-b" {
		t.Fatalf("same leaf/key in another project collided: response=%v err=%v", other, err)
	}
	tx, err := platformdb.BeginTenantTx(ctx, db, tenantID, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatalf("begin evidence read: %v", err)
	}
	defer func() { _ = tx.Rollback() }()
	for table, want := range map[string]int{
		"jobs": 2, "operations": 2, "operation_revisions": 3, "idempotency_records": 3, "audit_events": 3, "outbox_messages": 3,
	} {
		var got int
		if err = tx.QueryRowContext(ctx, "SELECT count(*) FROM "+table+" WHERE tenant_id=$1", tenantID).Scan(&got); err != nil || got != want {
			t.Fatalf("%s evidence count=%d want=%d err=%v", table, got, want, err)
		}
	}
	if err = tx.Commit(); err != nil {
		t.Fatalf("commit evidence read: %v", err)
	}
}

func TestRunCommandMetadataRequiresDeadlineAndCanonicalDigest(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, time.September, 1, 12, 0, 0, 0, time.UTC)
	identity := WorkerIdentity{TenantID: "tenant-01", ProjectID: "project-01", Principal: "principal-01", WorkerID: "worker-01"}
	request := &internaljobv1.ExpireAttemptLeasesRequest{
		Context: &commonv1.CommandContext{
			TenantId: identity.TenantID, ProjectId: identity.ProjectID, PrincipalId: identity.Principal,
			RequestId: "request-01", IdempotencyKey: "command-01", Deadline: timestamppb.New(now.Add(time.Minute)),
		},
		Parent: "tenants/tenant-01/projects/project-01", Limit: 10,
	}
	first, err := runCommandMetadata(identity, actionExpireLeases, request, request.GetContext(), now)
	if err != nil {
		t.Fatalf("canonical metadata: %v", err)
	}
	request.Context.RequestId = "request-02"
	request.Context.Deadline = timestamppb.New(now.Add(2 * time.Minute))
	second, err := runCommandMetadata(identity, actionExpireLeases, request, request.GetContext(), now)
	if err != nil || first.RequestDigest != second.RequestDigest {
		t.Fatalf("transport metadata changed canonical digest: first=%q second=%q err=%v", first.RequestDigest, second.RequestDigest, err)
	}
	request.Context.CanonicalRequestDigest = "sha256:" + strings.Repeat("f", 64)
	if _, err = runCommandMetadata(identity, actionExpireLeases, request, request.GetContext(), now); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("mismatched canonical digest status=%v err=%v", status.Code(err), err)
	}
	request.Context.CanonicalRequestDigest = ""
	request.Context.Deadline = timestamppb.New(now)
	if _, err = runCommandMetadata(identity, actionExpireLeases, request, request.GetContext(), now); status.Code(err) != codes.DeadlineExceeded {
		t.Fatalf("elapsed command deadline status=%v err=%v", status.Code(err), err)
	}
}

func TestAttemptCompletionFieldMaskPreservesOmittedFields(t *testing.T) {
	t.Parallel()
	oldOutput := &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/json"}
	newOutput := &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("b", 64), MediaType: "application/json"}
	oldError := &commonv1.ErrorDetail{Code: commonv1.ErrorCode_ERROR_CODE_ABORTED, Message: "preserve me"}
	stored := &jobv1.Attempt{
		AttemptId: "attempt-01", RunId: "run-01", JobId: "job-01", TenantId: "tenant-01", ProjectId: "project-01",
		WorkerId: "worker-01", LeaseEpoch: 3, ResourceVersion: 7, State: jobv1.AttemptState_ATTEMPT_STATE_RUNNING,
		Outputs: []*artifactv1.ArtifactRef{oldOutput}, Error: oldError,
	}
	requested := proto.Clone(stored).(*jobv1.Attempt)
	requested.State = jobv1.AttemptState_ATTEMPT_STATE_CANCELLED
	requested.Outputs = []*artifactv1.ArtifactRef{newOutput}
	requested.Error = nil
	masked, err := applyAttemptCompletionMask(stored, requested, []string{"state"}, 7)
	if err != nil {
		t.Fatalf("apply state-only mask: %v", err)
	}
	if masked.GetState() != jobv1.AttemptState_ATTEMPT_STATE_CANCELLED || !proto.Equal(masked.GetOutputs()[0], oldOutput) || !proto.Equal(masked.GetError(), oldError) {
		t.Fatalf("state-only mask changed omitted fields: %v", masked)
	}
	masked, err = applyAttemptCompletionMask(stored, requested, []string{"state", "outputs"}, 7)
	if err != nil || !proto.Equal(masked.GetOutputs()[0], newOutput) || !proto.Equal(masked.GetError(), oldError) {
		t.Fatalf("outputs mask failed or changed omitted error: value=%v err=%v", masked, err)
	}
	if _, err = applyAttemptCompletionMask(stored, requested, []string{"state", "state"}, 7); !errors.Is(err, ErrInvalidOutcome) {
		t.Fatalf("duplicate field mask err=%v", err)
	}
}

func TestAttemptCompletionRequiresStructuredFailure(t *testing.T) {
	t.Parallel()
	stored := &jobv1.Attempt{
		AttemptId: "attempt-01", RunId: "run-01", JobId: "job-01", TenantId: "tenant-01", ProjectId: "project-01",
		WorkerId: "worker-01", LeaseEpoch: 3, ResourceVersion: 7, State: jobv1.AttemptState_ATTEMPT_STATE_RUNNING,
	}
	for _, terminalState := range []jobv1.AttemptState{
		jobv1.AttemptState_ATTEMPT_STATE_FAILED,
		jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT,
		jobv1.AttemptState_ATTEMPT_STATE_CANCELLED,
	} {
		terminalState := terminalState
		t.Run(terminalState.String(), func(t *testing.T) {
			t.Parallel()
			requested := proto.Clone(stored).(*jobv1.Attempt)
			requested.State = terminalState
			if _, err := applyAttemptCompletionMask(stored, requested, []string{"state"}, 7); !errors.Is(err, ErrInvalidOutcome) {
				t.Fatalf("completion without an error detail err=%v", err)
			}
		})
	}

	requested := proto.Clone(stored).(*jobv1.Attempt)
	requested.State = jobv1.AttemptState_ATTEMPT_STATE_FAILED
	requested.Error = &commonv1.ErrorDetail{}
	if _, err := applyAttemptCompletionMask(stored, requested, []string{"state", "error"}, 7); !errors.Is(err, ErrInvalidOutcome) {
		t.Fatalf("completion with an unspecified error code err=%v", err)
	}

	requested.Error = &commonv1.ErrorDetail{
		Code:    commonv1.ErrorCode_ERROR_CODE_FAILED_PRECONDITION,
		Message: "structured failure",
	}
	masked, err := applyAttemptCompletionMask(stored, requested, []string{"state", "error"}, 7)
	if err != nil || !proto.Equal(masked.GetError(), requested.GetError()) {
		t.Fatalf("completion with a structured error: value=%v err=%v", masked, err)
	}
}

func TestRenewedLeaseDeadlineNeverShortens(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, time.September, 1, 12, 0, 0, 0, time.UTC)
	current := now.Add(10 * time.Minute)
	if got := renewedLeaseDeadline(now, MinimumLeaseDuration, current); !got.Equal(current) {
		t.Fatalf("renewal shortened current deadline: got=%v want=%v", got, current)
	}
	want := now.Add(12 * time.Minute)
	if got := renewedLeaseDeadline(now, 12*time.Minute, current); !got.Equal(want) {
		t.Fatalf("renewal did not extend deadline: got=%v want=%v", got, want)
	}
}

func protoCloneCommandContext(value *commonv1.CommandContext) *commonv1.CommandContext {
	return proto.Clone(value).(*commonv1.CommandContext)
}

func TestRunPageTokenIsScopedAndTamperEvident(t *testing.T) {
	t.Parallel()
	codec, err := NewRunPageTokenCodec([]byte("0123456789abcdef0123456789abcdef"))
	if err != nil {
		t.Fatalf("page codec: %v", err)
	}
	identity := WorkerIdentity{TenantID: "tenant-01", ProjectID: "project-01"}
	token, err := codec.Encode("runs", identity, "job-01", "run-01")
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	if after, decodeErr := codec.Decode(token, "runs", identity, "job-01"); decodeErr != nil || after != "run-01" {
		t.Fatalf("decode after=%q err=%v", after, decodeErr)
	}
	if _, decodeErr := codec.Decode(token+"x", "runs", identity, "job-01"); decodeErr == nil {
		t.Fatal("tampered page token was accepted")
	}
	other := identity
	other.ProjectID = "project-02"
	if _, decodeErr := codec.Decode(token, "runs", other, "job-01"); decodeErr == nil {
		t.Fatal("page token crossed project scope")
	}
}

func firstMetadata(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return values[0]
}
