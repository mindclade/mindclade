package jobs

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	featurev1 "github.com/mindclade/mindclade/protocols/generated/go/feature/v1"
	internaljobv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/job/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	transformv1 "github.com/mindclade/mindclade/protocols/generated/go/transform/v1"
)

const leaseTokenHeader = "x-mindclade-lease-token" //nolint:gosec // This is a protocol header or deterministic test fixture, not a credential.

// WorkerIdentity is transport-authenticated behavior state, not a wire model.
// Request messages cannot select their tenant, project, principal, or worker.
type WorkerIdentity struct {
	TenantID   string
	ProjectID  string
	Principal  string
	WorkerID   string
	LeaseToken string
}

type WorkerIdentityResolver interface {
	ResolveWorker(context.Context) (WorkerIdentity, error)
}

// JobIdentity is the verifier-owned principal scope used by JobService.
// Worker identity and lease credentials are deliberately absent: clients may
// request and cancel durable work without acquiring execution authority.
type JobIdentity struct {
	TenantID  string
	ProjectID string
	Principal string
}

type JobIdentityResolver interface {
	ResolveJob(context.Context) (JobIdentity, error)
}

// JobRepository is the normalized durable boundary for the generated
// JobService. Implementations return fresh protobuf values and make Job,
// Operation, audit, idempotency, history, and outbox mutations atomic.
type JobRepository interface {
	RequestJobSQL(context.Context, *jobv1.Job, *operationv1.Operation, JobCommandMetadata) (*JobMutationResult, error)
	GetJobSQL(context.Context, string, string, string) (*jobv1.Job, error)
	ListJobsSQL(context.Context, string, string, string, int) ([]*jobv1.Job, bool, time.Time, error)
	CancelJobSQL(context.Context, string, string, string, JobCommandMetadata) (*JobMutationResult, error)
}

// RunRepository is the normalized persistence boundary used by the generated
// RunService. Implementations must return fresh generated protobuf values.
type RunRepository interface {
	GetRunSQL(context.Context, string, string, string) (*jobv1.Run, error)
	ListRunsSQL(context.Context, string, string, string, string, int) ([]*jobv1.Run, bool, time.Time, error)
	GetAttemptSQL(context.Context, string, string, string) (*jobv1.Attempt, error)
	ListAttemptsSQL(context.Context, string, string, string, string, int) ([]*jobv1.Attempt, bool, time.Time, error)
	AcquireLeaseSQL(context.Context, AcquireLeaseCommand) (*LeaseMutationResult, error)
	RenewLeaseSQL(context.Context, RenewLeaseCommand) (*LeaseMutationResult, error)
	HeartbeatLeaseSQL(context.Context, RenewLeaseCommand) (*LeaseMutationResult, error)
	CancelAttemptSQL(context.Context, CancelAttemptCommand) (*AttemptMutationResult, error)
	ExpireLeasesSQL(context.Context, ExpireLeasesCommand) (*ExpireLeasesResult, error)
	CompleteAttemptSQL(context.Context, CompleteAttemptCommand) (*AttemptMutationResult, error)
}

type LeaseTokenMaterial struct {
	TenantID, ProjectID, WorkerID, RunID, AttemptID, IdempotencyKey, RequestDigest string
}

type LeaseTokenIssuer interface {
	Issue(string, LeaseTokenMaterial) (token string, keyID string, err error)
}

type HMACLeaseTokenIssuer struct {
	active string
	keys   map[string][]byte
}

func NewHMACLeaseTokenIssuer(active string, keys map[string][]byte) (*HMACLeaseTokenIssuer, error) {
	if active == "" || len(keys) == 0 {
		return nil, errors.New("lease token issuer requires an active key")
	}
	copyKeys := make(map[string][]byte, len(keys))
	for id, key := range keys {
		if !boundedIdentity(id) || len(key) < 32 {
			return nil, errors.New("lease token issuer keys require bounded ids and at least 32 bytes")
		}
		copyKeys[id] = append([]byte(nil), key...)
	}
	if _, ok := copyKeys[active]; !ok {
		return nil, errors.New("active lease token key is absent")
	}
	return &HMACLeaseTokenIssuer{active: active, keys: copyKeys}, nil
}

func (i *HMACLeaseTokenIssuer) Issue(keyID string, material LeaseTokenMaterial) (string, string, error) {
	if i == nil {
		return "", "", errors.New("lease token issuer is nil")
	}
	if keyID == "" {
		keyID = i.active
	}
	key, ok := i.keys[keyID]
	if !ok {
		return "", "", errors.New("lease token recovery key is unavailable")
	}
	parts := []string{"mindclade.run-lease.v1", keyID, material.TenantID, material.ProjectID, material.WorkerID, material.RunID, material.AttemptID, material.IdempotencyKey, material.RequestDigest}
	mac := hmac.New(sha256.New, key)
	for _, part := range parts {
		_, _ = fmt.Fprintf(mac, "%d:%s", len(part), part)
	}
	return "v1." + keyID + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil)), keyID, nil
}

type runClock interface{ Now() time.Time }

type systemRunClock struct{}

func (systemRunClock) Now() time.Time { return time.Now().UTC() }

// JobServer implements the generated durable-work API. It accepts identity
// only from the authenticated transport context, canonicalizes every command
// before persistence, and never exposes mutable aliases returned by a
// repository implementation.
type JobServer struct {
	internaljobv1.UnimplementedJobServiceServer
	repository JobRepository
	identities JobIdentityResolver
	pages      *RunPageTokenCodec
	clock      runClock
}

func NewJobServer(repository JobRepository, identities JobIdentityResolver, pages *RunPageTokenCodec) (*JobServer, error) {
	if repository == nil || identities == nil || pages == nil {
		return nil, errors.New("job service requires repository, identity resolver, and pagination codec")
	}
	return &JobServer{repository: repository, identities: identities, pages: pages, clock: systemRunClock{}}, nil
}

func (s *JobServer) identity(ctx context.Context) (JobIdentity, error) {
	identity, err := s.identities.ResolveJob(ctx)
	if err != nil || !boundedIdentity(identity.TenantID) || !boundedIdentity(identity.ProjectID) || !boundedIdentity(identity.Principal) {
		return JobIdentity{}, status.Error(codes.Unauthenticated, "authenticated principal identity is required")
	}
	return identity, nil
}

func jobCommandMetadata(identity JobIdentity, request proto.Message, value *commonv1.CommandContext, now time.Time) (JobCommandMetadata, error) {
	if request == nil || value == nil || now.IsZero() || !boundedIdentity(value.GetRequestId()) ||
		!boundedIdentity(value.GetIdempotencyKey()) || value.GetTenantId() != identity.TenantID ||
		value.GetProjectId() != identity.ProjectID || value.GetPrincipalId() != identity.Principal {
		return JobCommandMetadata{}, status.Error(codes.InvalidArgument, "authenticated command context with requestId and idempotencyKey is required")
	}
	if value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil {
		return JobCommandMetadata{}, status.Error(codes.InvalidArgument, "valid command deadline is required")
	}
	if !now.UTC().Before(value.GetDeadline().AsTime().UTC()) {
		return JobCommandMetadata{}, status.Error(codes.DeadlineExceeded, "command deadline elapsed")
	}
	cloned := proto.Clone(request)
	message := cloned.ProtoReflect()
	contextField := message.Descriptor().Fields().ByName(protoreflect.Name("context"))
	if contextField == nil || contextField.Kind() != protoreflect.MessageKind {
		return JobCommandMetadata{}, status.Error(codes.Internal, "durable request lacks command context")
	}
	message.Clear(contextField)
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(cloned)
	if err != nil {
		return JobCommandMetadata{}, status.Error(codes.Internal, "canonicalize durable request")
	}
	digestValue := sha256.Sum256(encoded)
	digest := "sha256:" + hex.EncodeToString(digestValue[:])
	if supplied := value.GetCanonicalRequestDigest(); supplied != "" && subtle.ConstantTimeCompare([]byte(supplied), []byte(digest)) != 1 {
		return JobCommandMetadata{}, status.Error(codes.InvalidArgument, "canonical request digest mismatch")
	}
	return JobCommandMetadata{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal,
		IdempotencyKey: value.GetIdempotencyKey(), RequestDigest: digest, ObservedAt: now.UTC(),
	}, nil
}

func (s *JobServer) RequestJob(ctx context.Context, request *internaljobv1.RequestJobRequest) (*internaljobv1.RequestJobResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetCommand() == nil {
		return nil, status.Error(codes.InvalidArgument, "job command is required")
	}
	command := proto.Clone(request.GetCommand()).(*jobv1.RequestJobCommand)
	now := s.clock.Now().UTC()
	metadata, err := jobCommandMetadata(identity, command, command.GetContext(), now)
	if err != nil {
		return nil, err
	}
	if !boundedIdentity(command.GetJobKind()) || command.GetConfiguration() == nil || !validArtifactReference(command.GetConfiguration(), true) ||
		(command.GetInput() != nil && !validArtifactReference(command.GetInput(), false)) {
		return nil, status.Error(codes.InvalidArgument, "jobKind and a valid content-addressed configuration are required")
	}
	var jobID string
	if requested := command.GetRequestedJobId(); requested != "" {
		if !validResourceLeaf(requested) {
			return nil, status.Error(codes.InvalidArgument, "requestedJobId must be a bounded resource-id leaf")
		}
		jobID = "jobs/" + requested
	} else if jobID, err = randomResourceID("jobs/"); err != nil {
		return nil, status.Error(codes.Internal, "generate job identity")
	}
	operationID, err := randomResourceID("operations/")
	if err != nil {
		return nil, status.Error(codes.Internal, "generate operation identity")
	}
	job := &jobv1.Job{
		JobId: jobID, OperationId: operationID, TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		State: jobv1.JobState_JOB_STATE_ACCEPTED, ResourceVersion: 1, JobKind: command.GetJobKind(),
		Input: cloneArtifactReference(command.GetInput()), Configuration: cloneArtifactReference(command.GetConfiguration()),
		CreatedAt: timestamppb.New(now), UpdatedAt: timestamppb.New(now), Etag: resourceETag(identity.TenantID, identity.ProjectID, jobID, 1),
	}
	operation := &operationv1.Operation{
		OperationId: operationID, TenantId: identity.TenantID, ProjectId: identity.ProjectID, JobId: jobID,
		State: operationv1.OperationState_OPERATION_STATE_PENDING, ResourceVersion: 1,
		CreatedAt: timestamppb.New(now), UpdatedAt: timestamppb.New(now), Etag: resourceETag(identity.TenantID, identity.ProjectID, operationID, 1),
	}
	result, err := s.repository.RequestJobSQL(ctx, job, operation, metadata)
	if err != nil {
		return nil, jobRPCError(err)
	}
	if result == nil || result.Job == nil || result.Operation == nil || requireJobScope(identity, result.Job.GetTenantId(), result.Job.GetProjectId()) != nil ||
		requireJobScope(identity, result.Operation.GetTenantId(), result.Operation.GetProjectId()) != nil {
		return nil, status.Error(codes.Internal, "job persistence returned an invalid scoped result")
	}
	return &internaljobv1.RequestJobResponse{Job: cloneJob(result.Job), Operation: proto.Clone(result.Operation).(*operationv1.Operation)}, nil
}

func (s *JobServer) GetJob(ctx context.Context, request *internaljobv1.GetJobRequest) (*internaljobv1.GetJobResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || len(request.GetIfNoneMatch()) > 512 || strings.ContainsAny(request.GetIfNoneMatch(), "\x00\r\n") {
		return nil, status.Error(codes.InvalidArgument, "valid job request is required")
	}
	jobID, err := scopedJobID(identity, request.GetName())
	if err != nil {
		return nil, err
	}
	job, err := s.repository.GetJobSQL(ctx, identity.TenantID, identity.ProjectID, jobID)
	if err != nil {
		return nil, jobRPCError(err)
	}
	if err = requireJobScope(identity, job.GetTenantId(), job.GetProjectId()); err != nil {
		return nil, err
	}
	return &internaljobv1.GetJobResponse{Job: cloneJob(job)}, nil
}

func (s *JobServer) ListJobs(ctx context.Context, request *internaljobv1.ListJobsRequest) (*internaljobv1.ListJobsResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || !validJobParent(identity, request.GetParent()) || strings.TrimSpace(request.GetFilter()) != "" ||
		(request.GetOrderBy() != "" && request.GetOrderBy() != "job_id") {
		return nil, status.Error(codes.InvalidArgument, "project parent, empty filter, and job_id ordering are required")
	}
	limit, err := runPageSize(request.GetPage().GetPageSize())
	if err != nil {
		return nil, err
	}
	cursorIdentity := jobCursorIdentity(identity)
	after := ""
	if token := request.GetPage().GetPageToken(); token != "" {
		after, err = s.pages.Decode(token, "jobs", cursorIdentity, request.GetParent())
		if err != nil {
			return nil, status.Error(codes.InvalidArgument, "invalid job page token")
		}
	}
	jobs, more, readAt, err := s.repository.ListJobsSQL(ctx, identity.TenantID, identity.ProjectID, after, limit)
	if err != nil {
		return nil, jobRPCError(err)
	}
	for _, job := range jobs {
		if err = requireJobScope(identity, job.GetTenantId(), job.GetProjectId()); err != nil {
			return nil, err
		}
	}
	next := ""
	if more && len(jobs) != 0 {
		next, err = s.pages.Encode("jobs", cursorIdentity, request.GetParent(), jobs[len(jobs)-1].GetJobId())
		if err != nil {
			return nil, status.Error(codes.Internal, "encode job page token")
		}
	}
	return &internaljobv1.ListJobsResponse{
		Jobs: cloneJobs(jobs), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt),
	}, nil
}

func (s *JobServer) CancelJob(ctx context.Context, request *internaljobv1.CancelJobRequest) (*internaljobv1.CancelJobResponse, error) {
	identity, err := s.identity(ctx)
	if err != nil {
		return nil, err
	}
	if request == nil || request.GetContext() == nil || request.GetEtag() == "" || len(request.GetEtag()) > 512 ||
		strings.ContainsAny(request.GetEtag(), "\x00\r\n") || len(request.GetReason()) > 4096 {
		return nil, status.Error(codes.InvalidArgument, "job name, etag, and command context are required")
	}
	jobID, err := scopedJobID(identity, request.GetName())
	if err != nil {
		return nil, err
	}
	metadata, err := jobCommandMetadata(identity, request, request.GetContext(), s.clock.Now().UTC())
	if err != nil {
		return nil, err
	}
	result, err := s.repository.CancelJobSQL(ctx, jobID, request.GetEtag(), request.GetReason(), metadata)
	if err != nil {
		return nil, jobRPCError(err)
	}
	if result == nil || result.Operation == nil || requireJobScope(identity, result.Operation.GetTenantId(), result.Operation.GetProjectId()) != nil {
		return nil, status.Error(codes.Internal, "job persistence returned an invalid scoped operation")
	}
	return &internaljobv1.CancelJobResponse{Operation: proto.Clone(result.Operation).(*operationv1.Operation)}, nil
}

func validArtifactReference(value interface {
	GetDigest() string
	GetMediaType() string
}, required bool,
) bool {
	if value == nil {
		return !required
	}
	digest := value.GetDigest()
	if len(digest) != 71 || !strings.HasPrefix(digest, "sha256:") || digest != strings.ToLower(digest) || !boundedIdentity(value.GetMediaType()) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(digest, "sha256:"))
	return err == nil
}

func cloneArtifactReference(value *artifactv1.ArtifactRef) *artifactv1.ArtifactRef {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*artifactv1.ArtifactRef)
}

func validResourceLeaf(value string) bool {
	if !boundedIdentity(value) || strings.Contains(value, "/") {
		return false
	}
	for _, r := range value {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_' || r == '.' {
			continue
		}
		return false
	}
	return true
}

func randomResourceID(prefix string) (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", err
	}
	return prefix + hex.EncodeToString(value[:]), nil
}

func scopedJobID(identity JobIdentity, name string) (string, error) {
	if name == "" || len(name) > 1024 || strings.TrimSpace(name) != name || strings.ContainsAny(name, "\x00\r\n") {
		return "", status.Error(codes.InvalidArgument, "job resource name is required")
	}
	parts := strings.Split(name, "/")
	switch {
	case len(parts) == 1 && validResourceLeaf(parts[0]):
		return "jobs/" + parts[0], nil
	case len(parts) == 2 && parts[0] == "jobs" && validResourceLeaf(parts[1]):
		return name, nil
	case len(parts) == 6 && parts[0] == "tenants" && parts[2] == "projects" && parts[4] == "jobs" &&
		parts[1] == identity.TenantID && parts[3] == identity.ProjectID && validResourceLeaf(parts[5]):
		return "jobs/" + parts[5], nil
	default:
		return "", status.Error(codes.PermissionDenied, "job name is outside authenticated scope")
	}
}

func validJobParent(identity JobIdentity, parent string) bool {
	return parent == identity.ProjectID || parent == "tenants/"+identity.TenantID+"/projects/"+identity.ProjectID
}

func requireJobScope(identity JobIdentity, tenantID, projectID string) error {
	if tenantID != identity.TenantID || projectID != identity.ProjectID {
		return status.Error(codes.PermissionDenied, "resource is outside authenticated scope")
	}
	return nil
}

func jobCursorIdentity(identity JobIdentity) WorkerIdentity {
	return WorkerIdentity{TenantID: identity.TenantID, ProjectID: identity.ProjectID, Principal: identity.Principal}
}

func resourceETag(tenantID, projectID, resourceID string, version int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%s\x00%d", tenantID, projectID, resourceID, version)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func jobRPCError(err error) error {
	switch {
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, "job resource not found")
	case errors.Is(err, ErrAlreadyExists), errors.Is(err, ErrIdempotencyConflict):
		return status.Error(codes.AlreadyExists, err.Error())
	case errors.Is(err, ErrInvalidJobCommand):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, ErrVersionConflict):
		return status.Error(codes.Aborted, err.Error())
	case errors.Is(err, ErrTerminalMutation):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "request canceled")
	case errors.Is(err, context.DeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, "request deadline exceeded")
	default:
		return status.Error(codes.Internal, "job persistence failure")
	}
}

// RunServer implements every generated worker-coordination RPC. Long-lived
// raw lease tokens are never stored or placed in protobuf messages: acquire
// returns the new token in response metadata and subsequent calls present it
// as authenticated request metadata.
type RunServer struct {
	internaljobv1.UnimplementedRunServiceServer
	repository RunRepository
	identities WorkerIdentityResolver
	pages      *RunPageTokenCodec
	clock      runClock
	tokens     LeaseTokenIssuer
}

func NewRunServer(repository RunRepository, identities WorkerIdentityResolver, pages *RunPageTokenCodec, tokens LeaseTokenIssuer) (*RunServer, error) {
	if repository == nil || identities == nil || pages == nil || tokens == nil {
		return nil, errors.New("run service requires repository, identity resolver, pagination codec, and lease token issuer")
	}
	return &RunServer{repository: repository, identities: identities, pages: pages, tokens: tokens, clock: systemRunClock{}}, nil
}

func (s *RunServer) worker(ctx context.Context, leaseRequired bool) (WorkerIdentity, error) {
	identity, err := s.identities.ResolveWorker(ctx)
	if err != nil {
		return WorkerIdentity{}, status.Error(codes.Unauthenticated, "authenticated worker identity is required")
	}
	if !boundedIdentity(identity.TenantID) || !boundedIdentity(identity.ProjectID) ||
		!boundedIdentity(identity.Principal) || !boundedIdentity(identity.WorkerID) {
		return WorkerIdentity{}, status.Error(codes.Unauthenticated, "authenticated worker identity is incomplete")
	}
	if leaseRequired && (len(identity.LeaseToken) < 32 || len(identity.LeaseToken) > 4096 ||
		strings.TrimSpace(identity.LeaseToken) != identity.LeaseToken || strings.ContainsAny(identity.LeaseToken, "\x00\r\n")) {
		return WorkerIdentity{}, status.Error(codes.Unauthenticated, "authenticated lease credential is required")
	}
	return identity, nil
}

func runCommandMetadata(identity WorkerIdentity, action string, request proto.Message, value *commonv1.CommandContext, now time.Time) (RunCommandMetadata, error) {
	if request == nil || value == nil || now.IsZero() || value.GetRequestId() == "" || value.GetIdempotencyKey() == "" ||
		value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID || value.GetPrincipalId() != identity.Principal ||
		!boundedIdentity(value.GetRequestId()) || !boundedIdentity(value.GetIdempotencyKey()) {
		return RunCommandMetadata{}, status.Error(codes.InvalidArgument, "authenticated command context with requestId and idempotencyKey is required")
	}
	if value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil {
		return RunCommandMetadata{}, status.Error(codes.InvalidArgument, "valid command deadline is required")
	}
	if !now.UTC().Before(value.GetDeadline().AsTime().UTC()) {
		return RunCommandMetadata{}, status.Error(codes.DeadlineExceeded, "command deadline elapsed")
	}
	cloned := proto.Clone(request)
	message := cloned.ProtoReflect()
	contextField := message.Descriptor().Fields().ByName(protoreflect.Name("context"))
	if contextField == nil || contextField.Kind() != protoreflect.MessageKind {
		return RunCommandMetadata{}, status.Error(codes.Internal, "durable request lacks command context")
	}
	message.Clear(contextField)
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(cloned)
	if err != nil {
		return RunCommandMetadata{}, status.Error(codes.Internal, "canonicalize durable request")
	}
	digestValue := sha256.Sum256(encoded)
	digest := "sha256:" + hex.EncodeToString(digestValue[:])
	if supplied := value.GetCanonicalRequestDigest(); supplied != "" && subtle.ConstantTimeCompare([]byte(supplied), []byte(digest)) != 1 {
		return RunCommandMetadata{}, status.Error(codes.InvalidArgument, "canonical request digest mismatch")
	}
	return RunCommandMetadata{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, PrincipalID: identity.Principal,
		WorkerID: identity.WorkerID, Action: action, IdempotencyKey: value.GetIdempotencyKey(),
		RequestDigest: digest, RequestID: value.GetRequestId(), TraceID: value.GetTraceId(),
		CorrelationID: value.GetCorrelationId(), CausationID: value.GetCausationId(), ObservedAt: now.UTC(),
	}, nil
}

func (s *RunServer) GetRun(ctx context.Context, request *internaljobv1.GetRunRequest) (*internaljobv1.GetRunResponse, error) {
	identity, err := s.worker(ctx, false)
	if err != nil {
		return nil, err
	}
	id, err := resourceID(request.GetName(), "runs")
	if err != nil {
		return nil, err
	}
	run, err := s.repository.GetRunSQL(ctx, identity.TenantID, identity.ProjectID, id)
	if err != nil {
		return nil, runRPCError(err)
	}
	if err = requireWorkerScope(identity, run.GetTenantId(), run.GetProjectId()); err != nil {
		return nil, err
	}
	return &internaljobv1.GetRunResponse{Run: proto.Clone(run).(*jobv1.Run)}, nil
}

func (s *RunServer) ListRuns(ctx context.Context, request *internaljobv1.ListRunsRequest) (*internaljobv1.ListRunsResponse, error) {
	identity, err := s.worker(ctx, false)
	if err != nil {
		return nil, err
	}
	if request == nil || strings.TrimSpace(request.GetFilter()) != "" {
		return nil, status.Error(codes.InvalidArgument, "run filters are not supported")
	}
	jobID, err := resourceID(request.GetParent(), "jobs")
	if err != nil {
		return nil, err
	}
	limit, err := runPageSize(request.GetPage().GetPageSize())
	if err != nil {
		return nil, err
	}
	after := ""
	if token := request.GetPage().GetPageToken(); token != "" {
		after, err = s.pages.Decode(token, "runs", identity, jobID)
		if err != nil {
			return nil, status.Error(codes.InvalidArgument, "invalid run page token")
		}
	}
	runs, more, readAt, err := s.repository.ListRunsSQL(ctx, identity.TenantID, identity.ProjectID, jobID, after, limit)
	if err != nil {
		return nil, runRPCError(err)
	}
	for _, run := range runs {
		if err = requireWorkerScope(identity, run.GetTenantId(), run.GetProjectId()); err != nil {
			return nil, err
		}
	}
	next := ""
	if more && len(runs) != 0 {
		next, err = s.pages.Encode("runs", identity, jobID, runs[len(runs)-1].GetRunId())
		if err != nil {
			return nil, status.Error(codes.Internal, "encode run page token")
		}
	}
	return &internaljobv1.ListRunsResponse{
		Runs: cloneRuns(runs), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt),
	}, nil
}

func (s *RunServer) GetAttempt(ctx context.Context, request *internaljobv1.GetAttemptRequest) (*internaljobv1.GetAttemptResponse, error) {
	identity, err := s.worker(ctx, false)
	if err != nil {
		return nil, err
	}
	id, err := resourceID(request.GetName(), "attempts")
	if err != nil {
		return nil, err
	}
	attempt, err := s.repository.GetAttemptSQL(ctx, identity.TenantID, identity.ProjectID, id)
	if err != nil {
		return nil, runRPCError(err)
	}
	if err = requireWorkerScope(identity, attempt.GetTenantId(), attempt.GetProjectId()); err != nil {
		return nil, err
	}
	return &internaljobv1.GetAttemptResponse{Attempt: proto.Clone(attempt).(*jobv1.Attempt)}, nil
}

func (s *RunServer) ListAttempts(ctx context.Context, request *internaljobv1.ListAttemptsRequest) (*internaljobv1.ListAttemptsResponse, error) {
	identity, err := s.worker(ctx, false)
	if err != nil {
		return nil, err
	}
	runID, err := resourceID(request.GetParent(), "runs")
	if err != nil {
		return nil, err
	}
	limit, err := runPageSize(request.GetPage().GetPageSize())
	if err != nil {
		return nil, err
	}
	after := ""
	if token := request.GetPage().GetPageToken(); token != "" {
		after, err = s.pages.Decode(token, "attempts", identity, runID)
		if err != nil {
			return nil, status.Error(codes.InvalidArgument, "invalid attempt page token")
		}
	}
	attempts, more, readAt, err := s.repository.ListAttemptsSQL(ctx, identity.TenantID, identity.ProjectID, runID, after, limit)
	if err != nil {
		return nil, runRPCError(err)
	}
	for _, attempt := range attempts {
		if err = requireWorkerScope(identity, attempt.GetTenantId(), attempt.GetProjectId()); err != nil {
			return nil, err
		}
	}
	next := ""
	if more && len(attempts) != 0 {
		next, err = s.pages.Encode("attempts", identity, runID, attempts[len(attempts)-1].GetAttemptId())
		if err != nil {
			return nil, status.Error(codes.Internal, "encode attempt page token")
		}
	}
	return &internaljobv1.ListAttemptsResponse{
		Attempts: cloneAttempts(attempts), Page: &commonv1.PageResponse{NextPageToken: next}, ReadTime: timestamppb.New(readAt),
	}, nil
}

func (s *RunServer) AcquireAttemptLease(ctx context.Context, request *internaljobv1.AcquireAttemptLeaseRequest) (*internaljobv1.AcquireAttemptLeaseResponse, error) {
	identity, err := s.worker(ctx, false)
	if err != nil {
		return nil, err
	}
	now := s.clock.Now()
	commandMetadata, err := runCommandMetadata(identity, actionAcquireLease, request, request.GetContext(), now)
	if err != nil {
		return nil, err
	}
	runID, err := resourceID(request.GetRunName(), "runs")
	if err != nil {
		return nil, err
	}
	if !boundedIdentity(request.GetAttemptId()) || request.GetLeaseDuration() == nil || !request.GetLeaseDuration().IsValid() {
		return nil, status.Error(codes.InvalidArgument, "attemptId and valid leaseDuration are required")
	}
	material := LeaseTokenMaterial{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, WorkerID: identity.WorkerID,
		RunID: runID, AttemptID: request.GetAttemptId(), IdempotencyKey: commandMetadata.IdempotencyKey,
		RequestDigest: commandMetadata.RequestDigest,
	}
	token, tokenKeyID, err := s.tokens.Issue("", material)
	if err != nil {
		return nil, status.Error(codes.Internal, "generate lease credential")
	}
	result, err := s.repository.AcquireLeaseSQL(ctx, AcquireLeaseCommand{
		TenantID: identity.TenantID, RunID: runID, AttemptID: request.GetAttemptId(), WorkerID: identity.WorkerID,
		Token: token, TokenKeyID: tokenKeyID, Duration: request.GetLeaseDuration().AsDuration(), Now: now, Command: commandMetadata,
	})
	if err != nil {
		return nil, runRPCError(err)
	}
	if result.TokenKeyID != tokenKeyID {
		token, _, err = s.tokens.Issue(result.TokenKeyID, material)
		if err != nil {
			return nil, status.Error(codes.FailedPrecondition, "lease credential recovery key is unavailable")
		}
	}
	digest, digestErr := LeaseTokenDigest(token)
	if digestErr != nil || !equalLeaseTokenDigest(result.Fence.GetLeaseTokenDigest(), digest) {
		return nil, status.Error(codes.Internal, "recovered lease credential does not match durable fence")
	}
	if err = requireWorkerScope(identity, result.Attempt.GetTenantId(), result.Attempt.GetProjectId()); err != nil {
		return nil, err
	}
	if err = grpc.SetHeader(ctx, metadata.Pairs(leaseTokenHeader, token)); err != nil {
		return nil, status.Error(codes.Unavailable, "publish lease credential")
	}
	return &internaljobv1.AcquireAttemptLeaseResponse{Attempt: cloneAttempt(result.Attempt), Fence: cloneFence(result.Fence)}, nil
}

func (s *RunServer) RenewAttemptLease(ctx context.Context, request *internaljobv1.RenewAttemptLeaseRequest) (*internaljobv1.RenewAttemptLeaseResponse, error) {
	attempt, fence, err := s.renew(ctx, request, request.GetContext(), request.GetFence(), request.GetLeaseDuration(), request.GetExpectedResourceVersion(), false)
	if err != nil {
		return nil, err
	}
	return &internaljobv1.RenewAttemptLeaseResponse{Attempt: attempt, Fence: fence}, nil
}

func (s *RunServer) HeartbeatAttempt(ctx context.Context, request *internaljobv1.HeartbeatAttemptRequest) (*internaljobv1.HeartbeatAttemptResponse, error) {
	attempt, fence, err := s.renew(ctx, request, request.GetContext(), request.GetFence(), request.GetLeaseDuration(), request.GetExpectedResourceVersion(), true)
	if err != nil {
		return nil, err
	}
	return &internaljobv1.HeartbeatAttemptResponse{Attempt: attempt, Fence: fence, ObservedAt: timestamppb.New(s.clock.Now())}, nil
}

func (s *RunServer) renew(ctx context.Context, request proto.Message, commandContext *commonv1.CommandContext, fence *jobv1.LeaseFence, duration interface {
	IsValid() bool
	AsDuration() time.Duration
}, expected int64, heartbeat bool,
) (*jobv1.Attempt, *jobv1.LeaseFence, error) {
	identity, credentials, err := s.leaseCredentials(ctx, commandContext, fence, expected)
	if err != nil {
		return nil, nil, err
	}
	if duration == nil || !duration.IsValid() {
		return nil, nil, status.Error(codes.InvalidArgument, "valid leaseDuration is required")
	}
	now := s.clock.Now()
	action := actionRenewLease
	if heartbeat {
		action = actionHeartbeat
	}
	metadata, err := runCommandMetadata(identity, action, request, commandContext, now)
	if err != nil {
		return nil, nil, err
	}
	command := RenewLeaseCommand{Credentials: credentials, ExpectedResourceVersion: expected, Duration: duration.AsDuration(), Now: now, Command: metadata}
	var result *LeaseMutationResult
	if heartbeat {
		result, err = s.repository.HeartbeatLeaseSQL(ctx, command)
	} else {
		result, err = s.repository.RenewLeaseSQL(ctx, command)
	}
	if err != nil {
		return nil, nil, runRPCError(err)
	}
	if err = requireWorkerScope(identity, result.Attempt.GetTenantId(), result.Attempt.GetProjectId()); err != nil {
		return nil, nil, err
	}
	return cloneAttempt(result.Attempt), cloneFence(result.Fence), nil
}

func (s *RunServer) CancelAttempt(ctx context.Context, request *internaljobv1.CancelAttemptRequest) (*internaljobv1.CancelAttemptResponse, error) {
	identity, credentials, err := s.leaseCredentials(ctx, request.GetContext(), request.GetFence(), request.GetExpectedResourceVersion())
	if err != nil {
		return nil, err
	}
	if len(request.GetReason()) > 1024 || strings.ContainsRune(request.GetReason(), '\x00') {
		return nil, status.Error(codes.InvalidArgument, "cancellation reason is invalid")
	}
	now := s.clock.Now()
	commandMetadata, err := runCommandMetadata(identity, actionCancelAttempt, request, request.GetContext(), now)
	if err != nil {
		return nil, err
	}
	result, err := s.repository.CancelAttemptSQL(ctx, CancelAttemptCommand{
		Credentials: credentials, ExpectedResourceVersion: request.GetExpectedResourceVersion(),
		Reason: request.GetReason(), Now: now, Command: commandMetadata,
	})
	if err != nil {
		return nil, runRPCError(err)
	}
	if result == nil || result.Attempt == nil || result.Run == nil {
		return nil, status.Error(codes.Internal, "worker persistence returned an incomplete cancellation")
	}
	if err = requireWorkerScope(identity, result.Run.GetTenantId(), result.Run.GetProjectId()); err != nil {
		return nil, err
	}
	return &internaljobv1.CancelAttemptResponse{Attempt: cloneAttempt(result.Attempt), Run: cloneRun(result.Run)}, nil
}

func (s *RunServer) ExpireAttemptLeases(ctx context.Context, request *internaljobv1.ExpireAttemptLeasesRequest) (*internaljobv1.ExpireAttemptLeasesResponse, error) {
	identity, err := s.worker(ctx, false)
	if err != nil {
		return nil, err
	}
	if !validProjectParent(identity, request.GetParent()) {
		return nil, status.Error(codes.PermissionDenied, "lease expiry parent is outside authenticated scope")
	}
	limit := int(request.GetLimit())
	if limit == 0 {
		limit = 100
	}
	if limit < 1 || limit > 1000 {
		return nil, status.Error(codes.InvalidArgument, "lease expiry limit must be between 1 and 1000")
	}
	now := s.clock.Now()
	commandMetadata, err := runCommandMetadata(identity, actionExpireLeases, request, request.GetContext(), now)
	if err != nil {
		return nil, err
	}
	result, err := s.repository.ExpireLeasesSQL(ctx, ExpireLeasesCommand{
		TenantID: identity.TenantID, Limit: limit, Now: now, Command: commandMetadata,
	})
	if err != nil {
		return nil, runRPCError(err)
	}
	if result == nil {
		return nil, status.Error(codes.Internal, "worker persistence returned an incomplete expiry result")
	}
	return &internaljobv1.ExpireAttemptLeasesResponse{Attempts: cloneAttempts(result.Attempts), ObservedAt: timestamppb.New(result.ObservedAt)}, nil
}

func (s *RunServer) CommitAttempt(ctx context.Context, request *internaljobv1.CommitAttemptRequest) (*internaljobv1.CommitAttemptResponse, error) {
	identity, credentials, err := s.leaseCredentials(ctx, request.GetContext(), request.GetFence(), request.GetExpectedResourceVersion())
	if err != nil {
		return nil, err
	}
	if request.GetAttempt() == nil || !validCommitMask(request.GetUpdateMask().GetPaths()) {
		return nil, status.Error(codes.InvalidArgument, "attempt and updateMask {state,outputs,error} are required")
	}
	now := s.clock.Now()
	commandMetadata, err := runCommandMetadata(identity, actionCommitAttempt, request, request.GetContext(), now)
	if err != nil {
		return nil, err
	}
	featureCompletion, transformCompletion, err := bindDomainCompletion(request)
	if err != nil {
		return nil, err
	}
	result, err := s.repository.CompleteAttemptSQL(ctx, CompleteAttemptCommand{
		Credentials: credentials, Attempt: proto.Clone(request.GetAttempt()).(*jobv1.Attempt),
		Fence:                   cloneFence(request.GetFence()),
		FeatureMaterialization:  featureCompletion,
		TransformExecution:      transformCompletion,
		UpdateMask:              append([]string(nil), request.GetUpdateMask().GetPaths()...),
		ExpectedResourceVersion: request.GetExpectedResourceVersion(), Now: now, Command: commandMetadata,
	})
	if err != nil {
		return nil, runRPCError(err)
	}
	if result == nil || result.Attempt == nil || result.Run == nil {
		return nil, status.Error(codes.Internal, "worker persistence returned an incomplete completion")
	}
	if err = requireWorkerScope(identity, result.Run.GetTenantId(), result.Run.GetProjectId()); err != nil {
		return nil, err
	}
	return &internaljobv1.CommitAttemptResponse{Attempt: cloneAttempt(result.Attempt), Run: cloneRun(result.Run)}, nil
}

func bindDomainCompletion(request *internaljobv1.CommitAttemptRequest) (*featurev1.CommitFeatureMaterializationCommand, *transformv1.CommitTransformExecutionCommand, error) {
	if request == nil {
		return nil, nil, status.Error(codes.InvalidArgument, "attempt completion request is required")
	}
	switch completion := request.GetDomainCompletion().(type) {
	case nil:
		return nil, nil, nil
	case *internaljobv1.CommitAttemptRequest_FeatureMaterialization:
		if completion.FeatureMaterialization == nil || !proto.Equal(completion.FeatureMaterialization.GetFence(), request.GetFence()) {
			return nil, nil, status.Error(codes.InvalidArgument, "feature completion must carry the current attempt fence")
		}
		value := proto.Clone(completion.FeatureMaterialization).(*featurev1.CommitFeatureMaterializationCommand)
		value.Context = proto.Clone(request.GetContext()).(*commonv1.CommandContext)
		return value, nil, nil
	case *internaljobv1.CommitAttemptRequest_TransformExecution:
		if completion.TransformExecution == nil || !proto.Equal(completion.TransformExecution.GetFence(), request.GetFence()) {
			return nil, nil, status.Error(codes.InvalidArgument, "transform completion must carry the current attempt fence")
		}
		value := proto.Clone(completion.TransformExecution).(*transformv1.CommitTransformExecutionCommand)
		value.Context = proto.Clone(request.GetContext()).(*commonv1.CommandContext)
		return nil, value, nil
	default:
		return nil, nil, status.Error(codes.InvalidArgument, "unsupported domain completion")
	}
}

func (s *RunServer) leaseCredentials(ctx context.Context, commandContext *commonv1.CommandContext, fence *jobv1.LeaseFence, expected int64) (WorkerIdentity, LeaseCredentials, error) {
	identity, err := s.worker(ctx, true)
	if err != nil {
		return WorkerIdentity{}, LeaseCredentials{}, err
	}
	if err = validateCommandContext(identity, commandContext); err != nil {
		return WorkerIdentity{}, LeaseCredentials{}, err
	}
	if fence == nil || fence.GetAttemptId() == "" || fence.GetLeaseEpoch() == 0 || expected < 1 ||
		fence.GetTenantId() != identity.TenantID || fence.GetProjectId() != identity.ProjectID {
		return WorkerIdentity{}, LeaseCredentials{}, status.Error(codes.InvalidArgument, "current scoped fence and expectedResourceVersion are required")
	}
	return identity, LeaseCredentials{
		TenantID: identity.TenantID, ProjectID: identity.ProjectID, AttemptID: fence.GetAttemptId(), WorkerID: identity.WorkerID,
		Token: identity.LeaseToken, Epoch: fence.GetLeaseEpoch(),
	}, nil
}

func validateCommandContext(identity WorkerIdentity, value *commonv1.CommandContext) error {
	if value == nil || value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID ||
		value.GetPrincipalId() != identity.Principal || value.GetIdempotencyKey() == "" {
		return status.Error(codes.InvalidArgument, "command context must match authenticated scope and include idempotencyKey")
	}
	return nil
}

func requireWorkerScope(identity WorkerIdentity, tenantID, projectID string) error {
	if tenantID != identity.TenantID || projectID != identity.ProjectID {
		return status.Error(codes.PermissionDenied, "resource is outside authenticated scope")
	}
	return nil
}

func validProjectParent(identity WorkerIdentity, parent string) bool {
	return parent == identity.ProjectID || parent == "tenants/"+identity.TenantID+"/projects/"+identity.ProjectID
}

func boundedIdentity(value string) bool {
	if value == "" || len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
		return false
	}
	return true
}

func resourceID(name, collection string) (string, error) {
	if name == "" || len(name) > 1024 || strings.TrimSpace(name) != name || strings.ContainsAny(name, "\x00\r\n") {
		return "", status.Error(codes.InvalidArgument, collection+" resource name is required")
	}
	parts := strings.Split(name, "/")
	if len(parts) == 1 && boundedIdentity(name) {
		return name, nil
	}
	if len(parts) < 2 || parts[len(parts)-2] != collection || !boundedIdentity(parts[len(parts)-1]) {
		return "", status.Error(codes.InvalidArgument, "invalid "+collection+" resource name")
	}
	return parts[len(parts)-1], nil
}

func validCommitMask(paths []string) bool {
	if len(paths) == 0 {
		return false
	}
	seen := make(map[string]struct{}, len(paths))
	for _, path := range paths {
		if path != "state" && path != "outputs" && path != "error" {
			return false
		}
		if _, exists := seen[path]; exists {
			return false
		}
		seen[path] = struct{}{}
	}
	_, state := seen["state"]
	return state
}

func runPageSize(value uint32) (int, error) {
	if value == 0 {
		return 50, nil
	}
	if value > 200 {
		return 0, status.Error(codes.InvalidArgument, "pageSize must be between 1 and 200")
	}
	return int(value), nil
}

func runRPCError(err error) error {
	switch {
	case errors.Is(err, ErrNotFound):
		return status.Error(codes.NotFound, "worker resource not found")
	case errors.Is(err, ErrLeaseHeld), errors.Is(err, ErrVersionConflict):
		return status.Error(codes.Aborted, err.Error())
	case errors.Is(err, ErrIdempotencyConflict):
		return status.Error(codes.AlreadyExists, err.Error())
	case errors.Is(err, ErrInvalidLease), errors.Is(err, ErrInvalidLeaseToken), errors.Is(err, ErrInvalidOutcome):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, ErrLeaseOwner):
		return status.Error(codes.PermissionDenied, err.Error())
	case errors.Is(err, ErrLeaseExpired), errors.Is(err, ErrStaleCompletion), errors.Is(err, ErrTerminalMutation):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, context.Canceled):
		return status.Error(codes.Canceled, "request canceled")
	case errors.Is(err, context.DeadlineExceeded):
		return status.Error(codes.DeadlineExceeded, "request deadline exceeded")
	default:
		return status.Error(codes.Internal, "worker persistence failure")
	}
}

func cloneRun(value *jobv1.Run) *jobv1.Run {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*jobv1.Run)
}

func cloneJob(value *jobv1.Job) *jobv1.Job {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*jobv1.Job)
}

func cloneJobs(values []*jobv1.Job) []*jobv1.Job {
	result := make([]*jobv1.Job, 0, len(values))
	for _, value := range values {
		result = append(result, cloneJob(value))
	}
	return result
}

func cloneRuns(values []*jobv1.Run) []*jobv1.Run {
	result := make([]*jobv1.Run, 0, len(values))
	for _, value := range values {
		result = append(result, cloneRun(value))
	}
	return result
}

func cloneAttempt(value *jobv1.Attempt) *jobv1.Attempt {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*jobv1.Attempt)
}

func cloneAttempts(values []*jobv1.Attempt) []*jobv1.Attempt {
	result := make([]*jobv1.Attempt, 0, len(values))
	for _, value := range values {
		result = append(result, cloneAttempt(value))
	}
	return result
}

func cloneFence(value *jobv1.LeaseFence) *jobv1.LeaseFence {
	if value == nil {
		return nil
	}
	return proto.Clone(value).(*jobv1.LeaseFence)
}

// RunPageTokenCodec signs keyset cursors and binds them to the authenticated
// tenant/project, collection, and parent. Cursors disclose no credentials.
type RunPageTokenCodec struct{ key []byte }

type runPageToken struct {
	Kind, Tenant, Project, Parent, After string
}

func NewRunPageTokenCodec(key []byte) (*RunPageTokenCodec, error) {
	if len(key) < 32 {
		return nil, errors.New("run pagination HMAC key requires at least 32 bytes")
	}
	return &RunPageTokenCodec{key: append([]byte(nil), key...)}, nil
}

func (c *RunPageTokenCodec) Encode(kind string, identity WorkerIdentity, parent, after string) (string, error) {
	payload, err := json.Marshal(runPageToken{Kind: kind, Tenant: identity.TenantID, Project: identity.ProjectID, Parent: parent, After: after})
	if err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, c.key)
	_, _ = mac.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil)), nil
}

func (c *RunPageTokenCodec) Decode(value, kind string, identity WorkerIdentity, parent string) (string, error) {
	if len(value) > 4096 {
		return "", errors.New("page token is too large")
	}
	parts := strings.Split(value, ".")
	if len(parts) != 2 {
		return "", errors.New("malformed page token")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return "", err
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return "", err
	}
	mac := hmac.New(sha256.New, c.key)
	_, _ = mac.Write(payload)
	if !hmac.Equal(signature, mac.Sum(nil)) {
		return "", errors.New("page token signature mismatch")
	}
	var token runPageToken
	if err = json.Unmarshal(payload, &token); err != nil {
		return "", err
	}
	if token.Kind != kind || token.Tenant != identity.TenantID || token.Project != identity.ProjectID || token.Parent != parent || token.After == "" {
		return "", errors.New("page token context mismatch")
	}
	return token.After, nil
}

var (
	_ internaljobv1.RunServiceServer = (*RunServer)(nil)
	_ internaljobv1.JobServiceServer = (*JobServer)(nil)
)
