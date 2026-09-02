package workflows

import (
	"context"
	"net"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"
	"google.golang.org/protobuf/proto"

	internalworkflowv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/workflow/v1"
	workflowv1 "github.com/mindclade/mindclade/protocols/generated/go/workflow/v1"
)

type workflowTestClock struct{ at time.Time }

func (clock workflowTestClock) Now() time.Time { return clock.at }

type workflowTestIdentities struct {
	identity Identity
	err      error
}

func (resolver workflowTestIdentities) Resolve(context.Context) (Identity, error) {
	return resolver.identity, resolver.err
}

type workflowTestRepository struct {
	Repository
	approval func(context.Context, Identity, *workflowv1.ApprovalRequest, string, time.Time) (*workflowv1.ApprovalRequest, bool, error)
	getRun   func(context.Context, Identity, string) (*workflowv1.WorkflowRun, error)
}

func (repository workflowTestRepository) RequestApproval(ctx context.Context, identity Identity, value *workflowv1.ApprovalRequest, digest string, at time.Time) (*workflowv1.ApprovalRequest, bool, error) {
	return repository.approval(ctx, identity, value, digest, at)
}

func (repository workflowTestRepository) GetRun(ctx context.Context, identity Identity, name string) (*workflowv1.WorkflowRun, error) {
	return repository.getRun(ctx, identity, name)
}

func TestApprovalServerDerivesScopeAndCanonicalDigestFromTransportIdentity(t *testing.T) {
	at := time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)
	identity := Identity{TenantID: "tenant", ProjectID: "project", Principal: "requester", Roles: map[string]struct{}{"automation-operator": {}}}
	value := approvalFixture(t, identity, workflowv1.ApprovalReusePolicy_APPROVAL_REUSE_POLICY_SINGLE_USE, "request", "key", at)
	value.Context.TenantId, value.Context.ProjectId, value.Context.PrincipalId, value.Context.CanonicalRequestDigest = "", "", "", ""
	var captured *workflowv1.ApprovalRequest
	repository := workflowTestRepository{approval: func(_ context.Context, got Identity, approval *workflowv1.ApprovalRequest, digest string, gotAt time.Time) (*workflowv1.ApprovalRequest, bool, error) {
		if got.TenantID != identity.TenantID || got.ProjectID != identity.ProjectID || got.Principal != identity.Principal || gotAt != at || !validSHA256(digest) {
			t.Fatalf("identity=%v at=%v digest=%q", got, gotAt, digest)
		}
		captured = clone(approval)
		return clone(approval), false, nil
	}}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("workflow-server-test-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	_, server, err := NewServer(repository, workflowTestIdentities{identity: identity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	server.clock = workflowTestClock{at: at}
	response, err := server.RequestApproval(context.Background(), &internalworkflowv1.RequestApprovalRequest{ApprovalRequest: value})
	if err != nil {
		t.Fatal(err)
	}
	if captured == nil || captured.GetContext().GetTenantId() != identity.TenantID || captured.GetContext().GetProjectId() != identity.ProjectID || captured.GetContext().GetPrincipalId() != identity.Principal || !validSHA256(captured.GetContext().GetCanonicalRequestDigest()) || !proto.Equal(response.GetApprovalRequest(), captured) {
		t.Fatalf("captured=%v response=%v", captured, response)
	}
	if value.GetContext().GetTenantId() != "" || value.GetContext().GetCanonicalRequestDigest() != "" {
		t.Fatal("server mutated caller-owned request")
	}
}

func TestRegisteredWorkflowGRPCServiceUsesGeneratedNetworkContract(t *testing.T) {
	identity := Identity{TenantID: "tenant", ProjectID: "project", Principal: "reader", Roles: map[string]struct{}{"automation-viewer": {}}}
	name := projectParent(identity) + "/workflowRuns/run"
	want := &workflowv1.WorkflowRun{Name: name, Uid: "run-uid", Revision: 3, Etag: resourceETag(name, 3), TenantId: identity.TenantID, ProjectId: identity.ProjectID, State: workflowv1.WorkflowRunState_WORKFLOW_RUN_STATE_RUNNING, TransitionSequence: 2}
	repository := workflowTestRepository{getRun: func(_ context.Context, got Identity, gotName string) (*workflowv1.WorkflowRun, error) {
		if got.TenantID != identity.TenantID || gotName != name {
			t.Fatalf("identity=%v name=%q", got, gotName)
		}
		return clone(want), nil
	}}
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("workflow-grpc-test-key-", 2)))
	if err != nil {
		t.Fatal(err)
	}
	workflowServer, approvalServer, err := NewServer(repository, workflowTestIdentities{identity: identity}, codec)
	if err != nil {
		t.Fatal(err)
	}
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	if err = Register(grpcServer, workflowServer, approvalServer); err != nil {
		t.Fatal(err)
	}
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(func() {
		grpcServer.Stop()
		_ = listener.Close()
	})
	dialer := func(context.Context, string) (net.Conn, error) { return listener.Dial() }
	connection, err := grpc.NewClient("passthrough:///workflow", grpc.WithContextDialer(dialer), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internalworkflowv1.NewWorkflowServiceClient(connection)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	response, err := client.GetWorkflowRun(ctx, &internalworkflowv1.GetWorkflowRunRequest{Name: name})
	if err != nil {
		t.Fatal(err)
	}
	if !proto.Equal(response.GetWorkflowRun(), want) {
		t.Fatalf("got=%v want=%v", response.GetWorkflowRun(), want)
	}
}
