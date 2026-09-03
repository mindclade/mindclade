package mindclade

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

// #nosec G101 -- deterministic non-secret capability fixture used only by an in-memory transport.
const jobRunLeaseToken = "opaque-worker-lease-capability-0123456789abcdef"

type jobRunFacadeClient struct {
	internaljobv1.JobServiceClient
	internaljobv1.RunServiceClient
	mu           sync.Mutex
	calls        []string
	leaseHeaders []string
}

func (client *jobRunFacadeClient) record(ctx context.Context, method string, commandContext *commonv1.CommandContext, message proto.Message, fenced bool) {
	client.mu.Lock()
	defer client.mu.Unlock()
	client.calls = append(client.calls, method)
	if commandContext != nil {
		if commandContext.GetTenantId() != "tenant-a" || commandContext.GetProjectId() != "project-a" || commandContext.GetPrincipalId() != "principal-a" || commandContext.GetCanonicalRequestDigest() == "" {
			panic("mutation command context was not bound to trusted client scope")
		}
		clone := proto.Clone(message)
		reflection := clone.ProtoReflect()
		reflection.Clear(reflection.Descriptor().Fields().ByName("context"))
		digest, err := deterministicDigest(clone)
		if err != nil || digest != commandContext.GetCanonicalRequestDigest() {
			panic("mutation command context did not carry the canonical request digest")
		}
	}
	requestValue, _ := ctx.Value(requestContextKey{}).(requestMetadata)
	if fenced {
		if requestValue.leaseToken != jobRunLeaseToken {
			panic("fenced mutation omitted its confidential transport credential")
		}
		client.leaseHeaders = append(client.leaseHeaders, requestValue.leaseToken)
	} else if requestValue.leaseToken != "" {
		panic("unfenced call leaked lease credential metadata")
	}
}

func (*jobRunFacadeClient) job() *jobv1.Job {
	return &jobv1.Job{JobId: "jobs/job-1", OperationId: "operations/op-1", TenantId: "tenant-a", ProjectId: "project-a", ResourceVersion: 1, State: jobv1.JobState_JOB_STATE_ACCEPTED}
}

func (*jobRunFacadeClient) operation() *operationv1.Operation {
	return &operationv1.Operation{OperationId: "operations/op-1", JobId: "jobs/job-1", TenantId: "tenant-a", ProjectId: "project-a", ResourceVersion: 1, State: operationv1.OperationState_OPERATION_STATE_PENDING}
}

func (*jobRunFacadeClient) run() *jobv1.Run {
	return &jobv1.Run{RunId: "runs/run-1", JobId: "jobs/job-1", TenantId: "tenant-a", ProjectId: "project-a", ResourceVersion: 1, LeaseEpoch: 1, State: jobv1.RunState_RUN_STATE_EXECUTING}
}

func (*jobRunFacadeClient) attempt(state jobv1.AttemptState) *jobv1.Attempt {
	return &jobv1.Attempt{AttemptId: "attempts/attempt-1", RunId: "runs/run-1", JobId: "jobs/job-1", TenantId: "tenant-a", ProjectId: "project-a", ResourceVersion: 1, LeaseEpoch: 1, State: state}
}

func (*jobRunFacadeClient) fence() *jobv1.LeaseFence {
	sum := sha256.Sum256([]byte(jobRunLeaseToken))
	return &jobv1.LeaseFence{AttemptId: "attempts/attempt-1", RunId: "runs/run-1", JobId: "jobs/job-1", TenantId: "tenant-a", ProjectId: "project-a", LeaseEpoch: 1, Deadline: timestamppb.New(time.Now().Add(5 * time.Minute)), LeaseTokenDigest: "sha256:" + hex.EncodeToString(sum[:])}
}

func (client *jobRunFacadeClient) RequestJob(ctx context.Context, request *internaljobv1.RequestJobRequest, _ ...grpc.CallOption) (*internaljobv1.RequestJobResponse, error) {
	client.record(ctx, "RequestJob", request.GetCommand().GetContext(), request.GetCommand(), false)
	return &internaljobv1.RequestJobResponse{Job: client.job(), Operation: client.operation()}, nil
}

func (client *jobRunFacadeClient) GetJob(ctx context.Context, request *internaljobv1.GetJobRequest, _ ...grpc.CallOption) (*internaljobv1.GetJobResponse, error) {
	client.record(ctx, "GetJob", nil, request, false)
	return &internaljobv1.GetJobResponse{Job: client.job()}, nil
}

func (client *jobRunFacadeClient) ListJobs(ctx context.Context, request *internaljobv1.ListJobsRequest, _ ...grpc.CallOption) (*internaljobv1.ListJobsResponse, error) {
	client.record(ctx, "ListJobs", nil, request, false)
	if request.GetParent() != "tenants/tenant-a/projects/project-a" {
		panic("ListJobs did not bind configured project scope")
	}
	return &internaljobv1.ListJobsResponse{Jobs: []*jobv1.Job{client.job()}, Page: &commonv1.PageResponse{NextPageToken: "jobs-next"}}, nil
}

func (client *jobRunFacadeClient) CancelJob(ctx context.Context, request *internaljobv1.CancelJobRequest, _ ...grpc.CallOption) (*internaljobv1.CancelJobResponse, error) {
	client.record(ctx, "CancelJob", request.GetContext(), request, false)
	return &internaljobv1.CancelJobResponse{Operation: client.operation()}, nil
}

func (client *jobRunFacadeClient) GetRun(ctx context.Context, request *internaljobv1.GetRunRequest, _ ...grpc.CallOption) (*internaljobv1.GetRunResponse, error) {
	client.record(ctx, "GetRun", nil, request, false)
	return &internaljobv1.GetRunResponse{Run: client.run()}, nil
}

func (client *jobRunFacadeClient) ListRuns(ctx context.Context, request *internaljobv1.ListRunsRequest, _ ...grpc.CallOption) (*internaljobv1.ListRunsResponse, error) {
	client.record(ctx, "ListRuns", nil, request, false)
	return &internaljobv1.ListRunsResponse{Runs: []*jobv1.Run{client.run()}, Page: &commonv1.PageResponse{NextPageToken: "runs-next"}}, nil
}

func (client *jobRunFacadeClient) GetAttempt(ctx context.Context, request *internaljobv1.GetAttemptRequest, _ ...grpc.CallOption) (*internaljobv1.GetAttemptResponse, error) {
	client.record(ctx, "GetAttempt", nil, request, false)
	return &internaljobv1.GetAttemptResponse{Attempt: client.attempt(jobv1.AttemptState_ATTEMPT_STATE_LEASED)}, nil
}

func (client *jobRunFacadeClient) ListAttempts(ctx context.Context, request *internaljobv1.ListAttemptsRequest, _ ...grpc.CallOption) (*internaljobv1.ListAttemptsResponse, error) {
	client.record(ctx, "ListAttempts", nil, request, false)
	return &internaljobv1.ListAttemptsResponse{Attempts: []*jobv1.Attempt{client.attempt(jobv1.AttemptState_ATTEMPT_STATE_LEASED)}, Page: &commonv1.PageResponse{NextPageToken: "attempts-next"}}, nil
}

func (client *jobRunFacadeClient) AcquireAttemptLease(ctx context.Context, request *internaljobv1.AcquireAttemptLeaseRequest, options ...grpc.CallOption) (*internaljobv1.AcquireAttemptLeaseResponse, error) {
	client.record(ctx, "AcquireAttemptLease", request.GetContext(), request, false)
	for _, option := range options {
		if header, ok := option.(grpc.HeaderCallOption); ok {
			*header.HeaderAddr = metadata.Pairs(leaseTokenHeaderSDK, jobRunLeaseToken)
		}
	}
	return &internaljobv1.AcquireAttemptLeaseResponse{Attempt: client.attempt(jobv1.AttemptState_ATTEMPT_STATE_LEASED), Fence: client.fence()}, nil
}

func (client *jobRunFacadeClient) RenewAttemptLease(ctx context.Context, request *internaljobv1.RenewAttemptLeaseRequest, _ ...grpc.CallOption) (*internaljobv1.RenewAttemptLeaseResponse, error) {
	client.record(ctx, "RenewAttemptLease", request.GetContext(), request, true)
	return &internaljobv1.RenewAttemptLeaseResponse{Attempt: client.attempt(jobv1.AttemptState_ATTEMPT_STATE_LEASED), Fence: client.fence()}, nil
}

func (client *jobRunFacadeClient) HeartbeatAttempt(ctx context.Context, request *internaljobv1.HeartbeatAttemptRequest, _ ...grpc.CallOption) (*internaljobv1.HeartbeatAttemptResponse, error) {
	client.record(ctx, "HeartbeatAttempt", request.GetContext(), request, true)
	return &internaljobv1.HeartbeatAttemptResponse{Attempt: client.attempt(jobv1.AttemptState_ATTEMPT_STATE_LEASED), Fence: client.fence(), ObservedAt: timestamppb.Now()}, nil
}

func (client *jobRunFacadeClient) CancelAttempt(ctx context.Context, request *internaljobv1.CancelAttemptRequest, _ ...grpc.CallOption) (*internaljobv1.CancelAttemptResponse, error) {
	client.record(ctx, "CancelAttempt", request.GetContext(), request, true)
	return &internaljobv1.CancelAttemptResponse{Attempt: client.attempt(jobv1.AttemptState_ATTEMPT_STATE_CANCELLED), Run: client.run()}, nil
}

func (client *jobRunFacadeClient) CommitAttempt(ctx context.Context, request *internaljobv1.CommitAttemptRequest, _ ...grpc.CallOption) (*internaljobv1.CommitAttemptResponse, error) {
	client.record(ctx, "CommitAttempt", request.GetContext(), request, true)
	return &internaljobv1.CommitAttemptResponse{Attempt: client.attempt(jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED), Run: client.run()}, nil
}

func TestJobRunFacadesCoverAllErgonomicRPCsAndHideLeaseCredentials(t *testing.T) {
	client, _, _ := testClient(t)
	transport := &jobRunFacadeClient{}
	client.Jobs.transport, client.Runs.transport = transport, transport
	ctx := context.Background()
	mutation := []RequestOption{WithIdempotencyKey("job-run-idempotency")}
	command := &jobv1.RequestJobCommand{Context: &commonv1.CommandContext{TenantId: "forged"}, JobKind: "training", Configuration: &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat("a", 64), MediaType: "application/json", SizeBytes: 42}, RequestedJobId: "job-1"}
	job, operation, err := client.Jobs.Request(ctx, command, mutation...)
	if err != nil || job.GetOperationId() != operation.GetOperationId() || command.GetContext().GetTenantId() != "forged" {
		t.Fatalf("RequestJob: job=%v operation=%v command=%v err=%v", job, operation, command, err)
	}
	if _, err = client.Jobs.Get(ctx, "job-1", ""); err != nil {
		t.Fatalf("GetJob: %v", err)
	}
	if _, err = client.Jobs.List(ctx, &internaljobv1.ListJobsRequest{Page: &commonv1.PageRequest{PageSize: 25}}); err != nil {
		t.Fatalf("ListJobs: %v", err)
	}
	if _, err = client.Jobs.Cancel(ctx, &internaljobv1.CancelJobRequest{Name: "job-1", Etag: "etag-1", Reason: "test"}, mutation...); err != nil {
		t.Fatalf("CancelJob: %v", err)
	}
	if _, err = client.Runs.GetRun(ctx, "run-1"); err != nil {
		t.Fatalf("GetRun: %v", err)
	}
	if _, err = client.Runs.ListRuns(ctx, &internaljobv1.ListRunsRequest{Parent: "job-1"}); err != nil {
		t.Fatalf("ListRuns: %v", err)
	}
	if _, err = client.Runs.GetAttempt(ctx, "attempt-1"); err != nil {
		t.Fatalf("GetAttempt: %v", err)
	}
	if _, err = client.Runs.ListAttempts(ctx, &internaljobv1.ListAttemptsRequest{Parent: "run-1"}); err != nil {
		t.Fatalf("ListAttempts: %v", err)
	}
	grant, err := client.Runs.AcquireAttemptLease(ctx, &internaljobv1.AcquireAttemptLeaseRequest{RunName: "run-1", AttemptId: "attempt-1", LeaseDuration: durationpb.New(2 * time.Minute)}, mutation...)
	if err != nil || grant.Credential().String() != "LeaseCredential(<redacted>)" {
		t.Fatalf("AcquireAttemptLease: grant=%v err=%v", grant, err)
	}
	detached := grant.Attempt()
	detached.AttemptId = "attempts/tampered"
	if grant.Attempt().GetAttemptId() != "attempts/attempt-1" {
		t.Fatal("LeaseGrant retained a caller-mutable attempt alias")
	}
	fence, credential := grant.Fence(), grant.Credential()
	if _, err = client.Runs.RenewAttemptLease(ctx, &internaljobv1.RenewAttemptLeaseRequest{Fence: cloneGenerated(fence), LeaseDuration: durationpb.New(2 * time.Minute), ExpectedResourceVersion: 1}, credential, mutation...); err != nil {
		t.Fatalf("RenewAttemptLease: %v", err)
	}
	if _, err = client.Runs.HeartbeatAttempt(ctx, &internaljobv1.HeartbeatAttemptRequest{Fence: cloneGenerated(fence), LeaseDuration: durationpb.New(2 * time.Minute), ExpectedResourceVersion: 1}, credential, mutation...); err != nil {
		t.Fatalf("HeartbeatAttempt: %v", err)
	}
	if _, err = client.Runs.CancelAttempt(ctx, &internaljobv1.CancelAttemptRequest{Fence: cloneGenerated(fence), ExpectedResourceVersion: 1, Reason: "worker shutdown"}, credential, mutation...); err != nil {
		t.Fatalf("CancelAttempt: %v", err)
	}
	if _, err = client.Runs.CommitAttempt(ctx, &internaljobv1.CommitAttemptRequest{Attempt: transport.attempt(jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED), Fence: cloneGenerated(fence), UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"state"}}, ExpectedResourceVersion: 1}, credential, mutation...); err != nil {
		t.Fatalf("CommitAttempt: %v", err)
	}
	want := []string{"RequestJob", "GetJob", "ListJobs", "CancelJob", "GetRun", "ListRuns", "GetAttempt", "ListAttempts", "AcquireAttemptLease", "RenewAttemptLease", "HeartbeatAttempt", "CancelAttempt", "CommitAttempt"}
	transport.mu.Lock()
	defer transport.mu.Unlock()
	if !reflect.DeepEqual(transport.calls, want) {
		t.Fatalf("calls=%v want=%v", transport.calls, want)
	}
	if !reflect.DeepEqual(transport.leaseHeaders, []string{jobRunLeaseToken, jobRunLeaseToken, jobRunLeaseToken, jobRunLeaseToken}) {
		t.Fatalf("lease headers were not isolated to fenced calls: %v", transport.leaseHeaders)
	}
}
