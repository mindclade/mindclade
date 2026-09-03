package admin

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	adminv1 "github.com/mindclade/mindclade/protocols/generated/go/admin/v1"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internaladminv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/admin/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

var (
	ErrUnauthenticated       = errors.New("authenticated administrative identity is required")
	ErrPermissionDenied      = errors.New("administrative resource is outside the authenticated scope")
	ErrInvalidArgument       = errors.New("invalid administrative request")
	ErrNotFound              = errors.New("administrative resource not found")
	ErrAlreadyExists         = errors.New("administrative resource already exists")
	ErrIdempotencyConflict   = errors.New("idempotency key was reused with different administrative intent")
	ErrRevisionConflict      = errors.New("administrative revision or etag conflict")
	ErrInvalidTransition     = errors.New("invalid administrative lifecycle transition")
	ErrDeadlineExceeded      = errors.New("administrative request deadline has elapsed")
	ErrExporterNotConfigured = errors.New("audit exporter is not configured")
)

type Identity struct {
	TenantID  string
	ProjectID string
	Principal string
}

type IdentityResolver interface {
	Resolve(context.Context) (Identity, error)
}

type (
	Clock     interface{ Now() time.Time }
	realClock struct{}
)

func (realClock) Now() time.Time { return time.Now().UTC() }

type ProjectPage struct {
	Limit     int
	AfterTime time.Time
	AfterName string
	Filter    string
	Order     string
	State     adminv1.ProjectState
}

type AuditPage struct {
	Limit       int
	AfterTime   time.Time
	AfterID     string
	QueryDigest string
	ProjectID   string
}

type Repository interface {
	GetTenant(context.Context, Identity, string) (*adminv1.Tenant, error)
	UpdateTenant(context.Context, Identity, *internaladminv1.UpdateTenantRequest, string, time.Time) (*operationv1.Operation, bool, error)
	CreateProject(context.Context, Identity, *internaladminv1.CreateProjectRequest, string, time.Time) (*operationv1.Operation, bool, error)
	GetProject(context.Context, Identity, string) (*adminv1.Project, error)
	ListProjects(context.Context, Identity, ProjectPage) ([]*adminv1.Project, string, time.Time, error)
	UpdateProject(context.Context, Identity, *internaladminv1.UpdateProjectRequest, string, time.Time) (*operationv1.Operation, bool, error)
	QueryAuditRecords(context.Context, Identity, *adminv1.AuditQuery, AuditPage) ([]*adminv1.AuditRecord, string, error)
	ExportAuditRecords(context.Context, Identity, *internaladminv1.ExportAuditRecordsRequest, string, time.Time) (*operationv1.Operation, bool, error)
	GetAuditExport(context.Context, Identity, string) (*adminv1.AuditExport, error)
}

// ExportCompletionRepository is the private worker-facing completion seam. It
// is not exposed through the administrative client API.
type ExportCompletionRepository interface {
	CompleteAuditExport(context.Context, Identity, string, string, *artifactv1.ArtifactRef, time.Time) (*adminv1.AuditExport, error)
}

type EventFactory interface {
	TenantUpdated(Identity, *adminv1.Tenant, []string, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	ProjectCreated(Identity, *adminv1.Project, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	ProjectUpdated(Identity, *adminv1.Project, []string, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	AuditExportRequested(Identity, *adminv1.AuditExport, *adminv1.AuditQuery, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	AuditExportCompleted(Identity, *adminv1.AuditExport, *operationv1.Operation, time.Time) (*commonv1.EventEnvelope, error)
}

type SQLRepository struct {
	DB                 *sql.DB
	Pagination         *PageTokenCodec
	Events             EventFactory
	ExporterConfigured bool
}

var _ internaladminv1.AdminServiceServer = (*Server)(nil)

func clone[T proto.Message](value T) T {
	if any(value) == nil {
		var zero T
		return zero
	}
	return proto.Clone(value).(T)
}

func cloneSlice[T proto.Message](values []T) []T {
	result := make([]T, 0, len(values))
	for _, value := range values {
		result = append(result, clone(value))
	}
	return result
}

func validateIdentity(identity Identity) error {
	for _, value := range []string{identity.TenantID, identity.Principal} {
		if value == "" || len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
			return ErrUnauthenticated
		}
	}
	if identity.ProjectID != "" && (len(identity.ProjectID) > 255 || strings.TrimSpace(identity.ProjectID) != identity.ProjectID || strings.ContainsAny(identity.ProjectID, "\x00\r\n")) {
		return ErrUnauthenticated
	}
	return nil
}

func canonicalCommandDigest(command proto.Message) (string, error) {
	if command == nil {
		return "", ErrInvalidArgument
	}
	copy := proto.Clone(command)
	message := copy.ProtoReflect()
	field := message.Descriptor().Fields().ByName(protoreflect.Name("context"))
	if field == nil || field.Kind() != protoreflect.MessageKind {
		return "", ErrInvalidArgument
	}
	message.Clear(field)
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copy)
	if err != nil {
		return "", fmt.Errorf("canonicalize admin command: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateContext(identity Identity, command proto.Message, value *commonv1.CommandContext, projectID string, now time.Time) (string, error) {
	if err := validateIdentity(identity); err != nil {
		return "", err
	}
	if value == nil || value.GetRequestId() == "" || value.GetIdempotencyKey() == "" {
		return "", ErrInvalidArgument
	}
	for _, item := range []string{value.GetRequestId(), value.GetIdempotencyKey()} {
		if len(item) > 255 || strings.TrimSpace(item) != item || strings.ContainsAny(item, "\x00\r\n") {
			return "", ErrInvalidArgument
		}
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID {
		return "", ErrPermissionDenied
	}
	if value.GetProjectId() != "" && value.GetProjectId() != projectID {
		return "", ErrPermissionDenied
	}
	if identity.ProjectID != "" && projectID != "" && identity.ProjectID != projectID {
		return "", ErrPermissionDenied
	}
	if value.GetPrincipalId() != "" && value.GetPrincipalId() != identity.Principal {
		return "", ErrPermissionDenied
	}
	if deadline := value.GetDeadline(); deadline != nil {
		if deadline.CheckValid() != nil {
			return "", ErrInvalidArgument
		}
		if !now.Before(deadline.AsTime()) {
			return "", ErrDeadlineExceeded
		}
	}
	digest, err := canonicalCommandDigest(command)
	if err != nil {
		return "", err
	}
	if supplied := value.GetCanonicalRequestDigest(); supplied != "" && subtle.ConstantTimeCompare([]byte(supplied), []byte(digest)) != 1 {
		return "", fmt.Errorf("%w: canonical request digest mismatch", ErrInvalidArgument)
	}
	return digest, nil
}

func validSHA256(value string) bool {
	if len(value) != 71 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}

func validID(value string) bool {
	if value == "" || len(value) > 128 {
		return false
	}
	for index, character := range value {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || (index > 0 && strings.ContainsRune("._~-", character)) {
			continue
		}
		return false
	}
	return true
}

func validateArtifact(value *artifactv1.ArtifactRef) error {
	if value == nil || !validSHA256(value.GetDigest()) || value.GetMediaType() == "" || value.GetSizeBytes() < 0 ||
		(value.GetIntegrityDigest() != "" && !validSHA256(value.GetIntegrityDigest())) {
		return ErrInvalidArgument
	}
	return nil
}

func validateResource(value *commonv1.ResourceRef, tenantID string) error {
	if value == nil || value.GetResourceType() == "" || value.GetResourceId() == "" || value.GetName() == "" || value.GetResourceVersion() < 0 {
		return ErrInvalidArgument
	}
	if value.GetTenantId() != "" && value.GetTenantId() != tenantID {
		return ErrPermissionDenied
	}
	return nil
}

func validatePolicyReference(value *policyv1.PolicyReference) error {
	if value == nil || value.GetName() == "" || value.GetUid() == "" || value.GetPolicyType() == "" || value.GetVersion() == "" ||
		!validSHA256(value.GetDigest()) || value.GetResourceRevision() <= 0 || value.GetEffectiveTime() == nil || value.GetEffectiveTime().CheckValid() != nil || validateArtifact(value.GetDocument()) != nil {
		return ErrInvalidArgument
	}
	if expiry := value.GetExpireTime(); expiry != nil && (expiry.CheckValid() != nil || !expiry.AsTime().After(value.GetEffectiveTime().AsTime())) {
		return ErrInvalidArgument
	}
	return nil
}

func tenantName(identity Identity, value string) (string, error) {
	expected := "tenants/" + identity.TenantID
	if value == identity.TenantID || value == expected {
		return expected, nil
	}
	return "", ErrNotFound
}

func projectName(identity Identity, value string) (string, string, error) {
	prefix := "tenants/" + identity.TenantID + "/projects/"
	if strings.HasPrefix(value, prefix) {
		value = strings.TrimPrefix(value, prefix)
	} else if strings.HasPrefix(value, "tenants/") {
		return "", "", ErrNotFound
	}
	if !validID(value) {
		return "", "", ErrInvalidArgument
	}
	if identity.ProjectID != "" && identity.ProjectID != value {
		return "", "", ErrPermissionDenied
	}
	return prefix + value, value, nil
}

func exportName(identity Identity, value string) (string, string, error) {
	tenantPrefix := "tenants/" + identity.TenantID + "/"
	projectID := identity.ProjectID
	prefix := tenantPrefix + "auditExports/"
	if strings.HasPrefix(value, tenantPrefix+"projects/") {
		remainder := strings.TrimPrefix(value, tenantPrefix+"projects/")
		parts := strings.SplitN(remainder, "/", 3)
		if len(parts) != 3 || parts[1] != "auditExports" || !validID(parts[0]) {
			return "", "", ErrInvalidArgument
		}
		if identity.ProjectID != "" && identity.ProjectID != parts[0] {
			return "", "", ErrPermissionDenied
		}
		projectID = parts[0]
		prefix = tenantPrefix + "projects/" + projectID + "/auditExports/"
	} else if projectID != "" {
		prefix = tenantPrefix + "projects/" + projectID + "/auditExports/"
	}
	if strings.HasPrefix(value, prefix) {
		value = strings.TrimPrefix(value, prefix)
	} else if strings.HasPrefix(value, "tenants/") {
		return "", "", ErrNotFound
	}
	if !validID(value) {
		return "", "", ErrInvalidArgument
	}
	return prefix + value, projectID, nil
}

func resourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func lastSegment(value string) string {
	if index := strings.LastIndexByte(value, '/'); index >= 0 {
		return value[index+1:]
	}
	return value
}

func tenantResource(identity Identity, value *adminv1.Tenant) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "tenant", ResourceId: identity.TenantID, TenantId: identity.TenantID, ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func projectResource(identity Identity, value *adminv1.Project) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "project", ResourceId: lastSegment(value.GetName()), TenantId: identity.TenantID, ProjectId: lastSegment(value.GetName()), ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func exportResource(identity Identity, value *adminv1.AuditExport) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{ResourceType: "audit_export", ResourceId: lastSegment(value.GetName()), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag()}
}

func operationResource(value *operationv1.Operation) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{ResourceType: "operation", ResourceId: lastSegment(value.GetOperationId()), TenantId: value.GetTenantId(), ProjectId: value.GetProjectId(), ResourceVersion: value.GetResourceVersion(), Name: value.GetOperationId(), Etag: value.GetEtag()}
}
