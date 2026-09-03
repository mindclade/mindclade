package mindclade

import (
	"context"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

type artifactGapClient struct {
	internalartifactv1.ArtifactServiceClient
	calls     []string
	requests  []proto.Message
	metadata  []requestMetadata
	artifact  *artifactv1.ArtifactRef
	lease     *commonv1.ResourceRef
	operation *jobv1.Operation
	returned  *artifactv1.ArtifactRef
}

func (client *artifactGapClient) record(ctx context.Context, method string, request proto.Message) {
	client.calls = append(client.calls, method)
	client.requests = append(client.requests, proto.Clone(request))
	metadata, _ := ctx.Value(requestContextKey{}).(requestMetadata)
	client.metadata = append(client.metadata, metadata)
}

func (client *artifactGapClient) GetArtifact(ctx context.Context, request *internalartifactv1.GetArtifactRequest, _ ...grpc.CallOption) (*internalartifactv1.GetArtifactResponse, error) {
	client.record(ctx, "GetArtifact", request)
	client.returned = cloneGenerated(client.artifact)
	return &internalartifactv1.GetArtifactResponse{Artifact: client.returned}, nil
}

func (client *artifactGapClient) ListArtifacts(ctx context.Context, request *internalartifactv1.ListArtifactsRequest, _ ...grpc.CallOption) (*internalartifactv1.ListArtifactsResponse, error) {
	client.record(ctx, "ListArtifacts", request)
	return &internalartifactv1.ListArtifactsResponse{Artifacts: []*artifactv1.ArtifactRef{cloneGenerated(client.artifact)}, Page: &commonv1.PageResponse{NextPageToken: "artifact-next"}}, nil
}

func (client *artifactGapClient) QuarantineArtifact(ctx context.Context, request *internalartifactv1.QuarantineArtifactRequest, _ ...grpc.CallOption) (*internalartifactv1.QuarantineArtifactResponse, error) {
	client.record(ctx, "QuarantineArtifact", request)
	return &internalartifactv1.QuarantineArtifactResponse{Operation: cloneGenerated(client.operation)}, nil
}

func (client *artifactGapClient) AcquireArtifactLease(ctx context.Context, request *internalartifactv1.AcquireArtifactLeaseRequest, _ ...grpc.CallOption) (*internalartifactv1.AcquireArtifactLeaseResponse, error) {
	client.record(ctx, "AcquireArtifactLease", request)
	return &internalartifactv1.AcquireArtifactLeaseResponse{Lease: cloneGenerated(client.lease)}, nil
}

func (client *artifactGapClient) ReleaseArtifactLease(ctx context.Context, request *internalartifactv1.ReleaseArtifactLeaseRequest, _ ...grpc.CallOption) (*internalartifactv1.ReleaseArtifactLeaseResponse, error) {
	client.record(ctx, "ReleaseArtifactLease", request)
	return &internalartifactv1.ReleaseArtifactLeaseResponse{}, nil
}

type operationGapClient struct {
	internaljobv1.OperationServiceClient
	calls          []string
	listRequests   []*internaljobv1.ListOperationsRequest
	cancelRequests []*internaljobv1.CancelOperationRequest
	operation      *jobv1.Operation
	returned       *jobv1.Operation
}

func (client *operationGapClient) GetOperation(_ context.Context, _ *internaljobv1.GetOperationRequest, _ ...grpc.CallOption) (*internaljobv1.GetOperationResponse, error) {
	client.calls = append(client.calls, "GetOperation")
	client.returned = cloneGenerated(client.operation)
	return &internaljobv1.GetOperationResponse{Operation: client.returned}, nil
}

func (client *operationGapClient) ListOperations(_ context.Context, request *internaljobv1.ListOperationsRequest, _ ...grpc.CallOption) (*internaljobv1.ListOperationsResponse, error) {
	client.calls = append(client.calls, "ListOperations")
	client.listRequests = append(client.listRequests, cloneGenerated(request))
	return &internaljobv1.ListOperationsResponse{Operations: []*jobv1.Operation{cloneGenerated(client.operation)}, Page: &commonv1.PageResponse{NextPageToken: "operation-next"}}, nil
}

func (client *operationGapClient) CancelOperation(_ context.Context, request *internaljobv1.CancelOperationRequest, _ ...grpc.CallOption) (*internaljobv1.CancelOperationResponse, error) {
	client.calls = append(client.calls, "CancelOperation")
	client.cancelRequests = append(client.cancelRequests, cloneGenerated(request))
	client.returned = cloneGenerated(client.operation)
	return &internaljobv1.CancelOperationResponse{Operation: client.returned}, nil
}

func TestArtifactLifecycleAndOperationListUseExactGeneratedRequests(t *testing.T) {
	client, _, _ := testClient(t)
	parent := projectName(client.config.TenantID, client.config.ProjectID)
	artifact := fixtureArtifact()
	operation := &jobv1.Operation{OperationId: parent + "/operations/op-1", TenantId: "tenant-a", ProjectId: "project-a", State: jobv1.OperationState_OPERATION_STATE_RUNNING}
	lease := &commonv1.ResourceRef{ResourceType: "artifact_lease", ResourceId: "lease-1", TenantId: "tenant-a", ProjectId: "project-a", ResourceVersion: 1, Name: parent + "/artifactLeases/lease-1", Etag: "lease-etag-1"}
	artifacts := &artifactGapClient{artifact: artifact, lease: lease, operation: operation}
	operations := &operationGapClient{operation: operation}
	client.Artifacts.transport = artifacts
	client.Operations.transport = operations

	got, err := client.Artifacts.Get(context.Background(), &internalartifactv1.GetArtifactRequest{Digest: artifact.GetDigest()})
	if err != nil || !proto.Equal(got, artifact) {
		t.Fatalf("GetArtifact: got=%v err=%v", got, err)
	}
	got.MediaType = "application/mutated"
	if artifacts.returned.GetMediaType() == got.GetMediaType() {
		t.Fatal("GetArtifact exposed transport-owned generated message memory")
	}
	listRequest := &internalartifactv1.ListArtifactsRequest{Page: &commonv1.PageRequest{PageSize: 25, PageToken: "artifact-page"}}
	list, err := client.Artifacts.List(context.Background(), listRequest)
	if err != nil || list.GetPage().GetNextPageToken() != "artifact-next" || listRequest.GetParent() != "" {
		t.Fatalf("ListArtifacts: response=%v input=%v err=%v", list, listRequest, err)
	}
	quarantine := &internalartifactv1.QuarantineArtifactRequest{Context: &commonv1.CommandContext{TenantId: "forged"}, Artifact: cloneGenerated(artifact), ReasonCode: "INTEGRITY_FAILURE", Evidence: []*artifactv1.EvidenceRef{{Digest: "sha256:" + strings.Repeat("b", 64), SubjectDigest: artifact.GetDigest(), EvidenceKind: "integrity-check"}}}
	if _, err = client.Artifacts.Quarantine(context.Background(), quarantine, WithIdempotencyKey("quarantine-1")); err != nil || quarantine.GetContext().GetTenantId() != "forged" {
		t.Fatalf("QuarantineArtifact: input=%v err=%v", quarantine, err)
	}
	acquire := &internalartifactv1.AcquireArtifactLeaseRequest{Artifact: cloneGenerated(artifact), ExpireTime: timestamppb.New(time.Now().Add(time.Hour))}
	if _, err = client.Artifacts.AcquireLease(context.Background(), acquire, WithIdempotencyKey("acquire-1")); err != nil {
		t.Fatalf("AcquireArtifactLease: %v", err)
	}
	release := &internalartifactv1.ReleaseArtifactLeaseRequest{Lease: cloneGenerated(lease), Etag: lease.GetEtag()}
	if err = client.Artifacts.ReleaseLease(context.Background(), release, WithIdempotencyKey("release-1")); err != nil {
		t.Fatalf("ReleaseArtifactLease: %v", err)
	}
	operationRequest := &internaljobv1.ListOperationsRequest{Page: &commonv1.PageRequest{PageSize: 50, PageToken: "operation-page"}}
	operationPage, err := client.Operations.List(context.Background(), operationRequest)
	if err != nil || operationPage.GetPage().GetNextPageToken() != "operation-next" || operationRequest.GetParent() != "" {
		t.Fatalf("ListOperations: response=%v input=%v err=%v", operationPage, operationRequest, err)
	}
	read, err := client.Operations.Get(context.Background(), operation.GetOperationId())
	if err != nil {
		t.Fatalf("GetOperation: %v", err)
	}
	read.Etag = "caller-mutated"
	if operations.returned.GetEtag() == read.GetEtag() {
		t.Fatal("GetOperation exposed transport-owned generated message memory")
	}
	if cancelled, cancelErr := client.Operations.Cancel(context.Background(), operation.GetOperationId(), "operation-etag-1", "operator request"); cancelErr != nil || cancelled.GetOperationId() != operation.GetOperationId() {
		t.Fatalf("CancelOperation: response=%v err=%v", cancelled, cancelErr)
	} else {
		cancelled.Etag = "caller-mutated-again"
		if operations.returned.GetEtag() == cancelled.GetEtag() {
			t.Fatal("CancelOperation exposed transport-owned generated message memory")
		}
	}

	if got, want := strings.Join(artifacts.calls, ","), "GetArtifact,ListArtifacts,QuarantineArtifact,AcquireArtifactLease,ReleaseArtifactLease"; got != want {
		t.Fatalf("artifact RPCs = %q, want %q", got, want)
	}
	if len(operations.listRequests) != 1 || operations.listRequests[0].GetParent() != parent || operations.listRequests[0].GetPage().GetPageToken() != "operation-page" {
		t.Fatalf("operation list request was not scoped/preserved: %v", operations.listRequests)
	}
	if len(operations.cancelRequests) != 1 || operations.cancelRequests[0].GetName() != operation.GetOperationId() || operations.cancelRequests[0].GetContext().GetTenantId() != "tenant-a" || operations.cancelRequests[0].GetContext().GetCanonicalRequestDigest() == "" {
		t.Fatalf("operation cancellation was not authoritatively bound: %v", operations.cancelRequests)
	}
	if listCall := artifacts.requests[1].(*internalartifactv1.ListArtifactsRequest); listCall.GetParent() != parent || listCall.GetPage().GetPageToken() != "artifact-page" {
		t.Fatalf("artifact list request was not scoped/preserved: %v", listCall)
	}
	for index, request := range artifacts.requests[2:] {
		field := request.ProtoReflect().Descriptor().Fields().ByName("context")
		contextValue := request.ProtoReflect().Get(field).Message().Interface().(*commonv1.CommandContext)
		clone := proto.Clone(request)
		clone.ProtoReflect().Clear(field)
		digest, digestErr := deterministicDigest(clone)
		if digestErr != nil || contextValue.GetCanonicalRequestDigest() != digest || contextValue.GetTenantId() != "tenant-a" || contextValue.GetProjectId() != "project-a" || contextValue.GetPrincipalId() != "principal-a" || artifacts.metadata[index+2].idempotencyKey == "" {
			t.Fatalf("mutation request %d was not authoritatively bound: context=%v digest=%q err=%v", index, contextValue, digest, digestErr)
		}
	}
}
