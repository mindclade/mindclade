package policies

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
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

var fixtureTime = time.Date(2026, 9, 2, 12, 0, 0, 0, time.UTC)

type fixedResolver struct{ identity Identity }

func (r fixedResolver) Resolve(context.Context) (Identity, error) { return r.identity, nil }

type fixedClock struct{ at time.Time }

func (c fixedClock) Now() time.Time { return c.at }

type fakeRepository struct {
	operation *jobv1.Operation
	policy    *policyv1.UsePolicy
	decision  *policyv1.AuthorizationDecision
	snapshot  *policyv1.PolicyReference
	request   proto.Message
}

func (r *fakeRepository) EvaluateAuthorization(_ context.Context, _ Identity, request *internalpolicyv1.EvaluateAuthorizationRequest, _ string, _ time.Time) (*policyv1.AuthorizationDecision, bool, error) {
	r.request = clone(request)
	return clone(r.decision), false, nil
}

func (r *fakeRepository) CreateUsePolicy(_ context.Context, _ Identity, request *internalpolicyv1.CreateUsePolicyRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) UpdateUsePolicy(_ context.Context, _ Identity, request *internalpolicyv1.UpdateUsePolicyRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) GetUsePolicy(context.Context, Identity, string) (*policyv1.UsePolicy, error) {
	return clone(r.policy), nil
}

func (r *fakeRepository) ListUsePolicies(context.Context, Identity, PolicyPage) ([]*policyv1.UsePolicy, string, time.Time, error) {
	return []*policyv1.UsePolicy{clone(r.policy)}, "", fixtureTime, nil
}

func (r *fakeRepository) ActivateUsePolicy(_ context.Context, _ Identity, request *internalpolicyv1.ActivateUsePolicyRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) RevokeUsePolicy(_ context.Context, _ Identity, request *internalpolicyv1.RevokeUsePolicyRequest, _ string, _ time.Time) (*jobv1.Operation, bool, error) {
	r.request = clone(request)
	return clone(r.operation), false, nil
}

func (r *fakeRepository) ResolvePolicySnapshot(context.Context, Identity, string, time.Time) (*policyv1.PolicyReference, error) {
	return clone(r.snapshot), nil
}

func identityFixture() Identity {
	return Identity{TenantID: "tenant-1", ProjectID: "project-1", Principal: "principal-1"}
}

func commandContext(message proto.Message) *commonv1.CommandContext {
	digest, err := canonicalCommandDigest(message)
	if err != nil {
		panic(err)
	}
	return &commonv1.CommandContext{RequestId: "request-1", IdempotencyKey: "key-1", TenantId: "tenant-1", ProjectId: "project-1", PrincipalId: "principal-1", TraceId: "trace-1", Deadline: timestamppb.New(fixtureTime.Add(time.Minute)), CanonicalRequestDigest: digest}
}

func artifactFixture(character string) *artifactv1.ArtifactRef {
	return &artifactv1.ArtifactRef{Digest: "sha256:" + strings.Repeat(character, 64), MediaType: "application/json", SizeBytes: 42}
}

func TestDeniedSecuritySubjectBindsCommandIdentity(t *testing.T) {
	t.Parallel()
	identity := identityFixture()
	subject := &commonv1.ResourceRef{
		ResourceType: "model", ResourceId: "model-1", TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		ResourceVersion: 7, Name: projectParent(identity) + "/models/model-1",
	}
	digest := "sha256:" + strings.Repeat("a", 64)
	firstCommand := &commonv1.CommandContext{
		RequestId: "request-1", IdempotencyKey: "deny-1", TenantId: identity.TenantID,
		ProjectId: identity.ProjectID, PrincipalId: identity.Principal,
	}
	first, err := deniedSecuritySubject(identity, subject, "DEFAULT_DENY", digest, firstCommand)
	if err != nil {
		t.Fatal(err)
	}
	replayed, err := deniedSecuritySubject(identity, proto.Clone(subject).(*commonv1.ResourceRef), "DEFAULT_DENY", digest, proto.Clone(firstCommand).(*commonv1.CommandContext))
	if err != nil {
		t.Fatal(err)
	}
	if !proto.Equal(first, replayed) {
		t.Fatalf("exact idempotent replay changed security subject: first=%v replay=%v", first, replayed)
	}
	secondCommand := proto.Clone(firstCommand).(*commonv1.CommandContext)
	secondCommand.RequestId = "request-2"
	secondCommand.IdempotencyKey = "deny-2"
	second, err := deniedSecuritySubject(identity, subject, "DEFAULT_DENY", digest, secondCommand)
	if err != nil {
		t.Fatal(err)
	}
	if first.GetResourceId() == second.GetResourceId() || first.GetName() == second.GetName() {
		t.Fatalf("distinct denied commands collided: first=%v second=%v", first, second)
	}
}

func policyFixture() *policyv1.UsePolicy {
	identity := identityFixture()
	name := projectParent(identity) + "/usePolicies/safe"
	return &policyv1.UsePolicy{Name: name, Uid: "policy-uid", Revision: 1, Etag: resourceETag(name, 1), TenantId: identity.TenantID, ProjectId: identity.ProjectID, DisplayName: "Safe use", State: policyv1.UsePolicyState_USE_POLICY_STATE_DRAFT, PolicyDocument: artifactFixture("a"), PermittedPurposes: []string{"research"}, CreateTime: timestamppb.New(fixtureTime), UpdateTime: timestamppb.New(fixtureTime)}
}

// createPolicyFixture is policyFixture with the server-assigned fields cleared.
// Sending them on a create is now rejected by the generated cross-field rule.
func createPolicyFixture() *policyv1.UsePolicy {
	policy := policyFixture()
	policy.Name = ""
	policy.Uid = ""
	policy.Revision = 0
	policy.Etag = ""
	policy.TenantId = ""
	policy.ProjectId = ""
	policy.CreateTime = nil
	policy.UpdateTime = nil
	policy.DeleteTime = nil
	return policy
}

func serverFixture(t *testing.T, repository Repository) *Server {
	t.Helper()
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("p", 32)))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(repository, fixedResolver{identity: identityFixture()}, codec)
	if err != nil {
		t.Fatal(err)
	}
	return server.withClock(fixedClock{at: fixtureTime})
}

func TestPolicyServerClonesAndBindsAuthenticatedCommand(t *testing.T) {
	operation := &jobv1.Operation{OperationId: "operations/1", TenantId: "tenant-1", ProjectId: "project-1", State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, Done: true}
	repository := &fakeRepository{operation: operation}
	server := serverFixture(t, repository)
	request := &internalpolicyv1.CreateUsePolicyRequest{Parent: projectParent(identityFixture()), UsePolicyId: "safe", UsePolicy: createPolicyFixture()}
	request.Context = commandContext(request)
	response, err := server.CreateUsePolicy(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	request.UsePolicy.DisplayName = "mutated"
	stored := repository.request.(*internalpolicyv1.CreateUsePolicyRequest)
	if stored.GetUsePolicy().GetDisplayName() != "Safe use" || response.GetOperation() == operation {
		t.Fatal("generated request or response alias escaped the policy transport")
	}
}

func TestGeneratedPolicyEventsAreRegisteredAndDecodable(t *testing.T) {
	identity := identityFixture()
	context := &commonv1.CommandContext{RequestId: "request-1", TraceId: "trace-1"}
	value := policyFixture()
	operation := &jobv1.Operation{OperationId: "operations/1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Etag: "etag"}
	events := GeneratedEventFactory{}
	created, err := events.PolicyCreated(identity, value, operation, context, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := queue.UnmarshalRegisteredPayload(created)
	if err != nil {
		t.Fatal(err)
	}
	if typed, ok := payload.(*policyv1.UsePolicyCreated); !ok || typed.GetUsePolicy().GetName() != value.GetName() {
		t.Fatalf("payload=%T %v", payload, payload)
	}
	decision := &policyv1.AuthorizationDecision{Name: projectParent(identity) + "/authorizationDecisions/1", Uid: "1", TenantId: identity.TenantID, ProjectId: identity.ProjectID, DecisionDigest: "sha256:" + strings.Repeat("b", 64)}
	recorded, err := events.DecisionRecorded(identity, decision, context, fixtureTime)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = queue.UnmarshalRegisteredPayload(recorded); err != nil {
		t.Fatal(err)
	}
}

func TestPolicyPageTokenIsTamperEvidentAndScoped(t *testing.T) {
	codec, err := NewPageTokenCodec([]byte(strings.Repeat("k", 32)))
	if err != nil {
		t.Fatal(err)
	}
	expected := pageToken{Kind: "use-policies", Tenant: "t", Project: "p", Order: "create_time desc,name desc"}
	encoded, err := codec.encode(pageToken{Kind: expected.Kind, Tenant: expected.Tenant, Project: expected.Project, Order: expected.Order, AfterTime: fixtureTime.Format(time.RFC3339Nano), AfterName: "last"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = codec.decode(encoded, expected); err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(encoded, ".")
	if _, err = codec.decode("A"+parts[0][1:]+"."+parts[1], expected); err == nil {
		t.Fatal("tampered policy page token accepted")
	}
	expected.Tenant = "other"
	if _, err = codec.decode(encoded, expected); err == nil {
		t.Fatal("cross-tenant policy page token accepted")
	}
}

func TestPolicyGeneratedNetworkGRPCService(t *testing.T) {
	policy := policyFixture()
	snapshot := &policyv1.PolicyReference{Name: policy.GetName() + "/snapshots/2", Uid: "snapshot", PolicyType: "use-policy", Version: "2", Digest: policy.GetPolicyDocument().GetDigest(), Document: clone(policy.GetPolicyDocument()), ResourceRevision: 2, EffectiveTime: timestamppb.New(fixtureTime)}
	decision := &policyv1.AuthorizationDecision{Name: projectParent(identityFixture()) + "/authorizationDecisions/1", Uid: "decision", TenantId: "tenant-1", ProjectId: "project-1", Outcome: policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_DENY}
	operation := &jobv1.Operation{OperationId: "operations/1", TenantId: "tenant-1", ProjectId: "project-1", State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, Done: true}
	server := serverFixture(t, &fakeRepository{policy: policy, snapshot: snapshot, decision: decision, operation: operation})
	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	Register(grpcServer, server)
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(grpcServer.Stop)
	connection, err := grpc.NewClient("passthrough:///policy-test", grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	client := internalpolicyv1.NewPolicyServiceClient(connection)
	if _, err = client.GetUsePolicy(context.Background(), &internalpolicyv1.GetUsePolicyRequest{Name: policy.GetName()}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.ListUsePolicies(context.Background(), &internalpolicyv1.ListUsePoliciesRequest{Parent: projectParent(identityFixture()), Page: &commonv1.PageRequest{PageSize: 10}}); err != nil {
		t.Fatal(err)
	}
	if _, err = client.ResolvePolicySnapshot(context.Background(), &internalpolicyv1.ResolvePolicySnapshotRequest{Name: policy.GetName(), EffectiveTime: timestamppb.New(fixtureTime)}); err != nil {
		t.Fatal(err)
	}
	// A create carries no server-assigned identity; the update below still does.
	create := &internalpolicyv1.CreateUsePolicyRequest{Parent: projectParent(identityFixture()), UsePolicyId: "safe", UsePolicy: createPolicyFixture()}
	create.Context = commandContext(create)
	if _, err = client.CreateUsePolicy(context.Background(), create); err != nil {
		t.Fatal(err)
	}
	update := &internalpolicyv1.UpdateUsePolicyRequest{UsePolicy: policy, UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"display_name"}}, Etag: policy.GetEtag()}
	update.Context = commandContext(update)
	if _, err = client.UpdateUsePolicy(context.Background(), update); err != nil {
		t.Fatal(err)
	}
	activate := &internalpolicyv1.ActivateUsePolicyRequest{Name: policy.GetName(), Etag: policy.GetEtag()}
	activate.Context = commandContext(activate)
	if _, err = client.ActivateUsePolicy(context.Background(), activate); err != nil {
		t.Fatal(err)
	}
	revoke := &internalpolicyv1.RevokeUsePolicyRequest{Name: policy.GetName(), Etag: policy.GetEtag(), ReasonCode: "REVOKED_BY_ADMIN"}
	revoke.Context = commandContext(revoke)
	if _, err = client.RevokeUsePolicy(context.Background(), revoke); err != nil {
		t.Fatal(err)
	}
	evaluate := &internalpolicyv1.EvaluateAuthorizationRequest{TenantId: "tenant-1", ProjectId: "project-1", PrincipalRef: "principal-1", Action: "models.read", Resource: &commonv1.ResourceRef{ResourceType: "model", ResourceId: "m", TenantId: "tenant-1", ProjectId: "project-1", ResourceVersion: 1, Name: projectParent(identityFixture()) + "/models/m"}, IntentDigest: "sha256:" + strings.Repeat("c", 64)}
	evaluate.Context = commandContext(evaluate)
	if _, err = client.EvaluateAuthorization(context.Background(), evaluate); err != nil {
		t.Fatal(err)
	}
}
