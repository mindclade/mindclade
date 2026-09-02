package artifacts

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	internalartifactv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/artifact/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	objectstorage "github.com/mindclade/mindclade/services/control_plane/internal/platform/storage"
)

var (
	ErrUnauthenticated     = errors.New("authenticated identity is required")
	ErrPermissionDenied    = errors.New("authenticated identity does not own the artifact resource")
	ErrInvalidArgument     = errors.New("invalid artifact request")
	ErrConflict            = errors.New("artifact content metadata conflicts with an existing digest")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different artifact command content")
	ErrRevisionConflict    = errors.New("artifact lease etag conflict")
	ErrInvalidTransition   = errors.New("invalid artifact state transition")
	ErrStagingUnverified   = errors.New("artifact staging receipt is not verified")
	ErrPageToken           = errors.New("artifact page token is invalid")
	ErrUploadExpired       = errors.New("artifact upload session expired")
	ErrChunkConflict       = errors.New("artifact upload chunk conflicts with durable progress")
	ErrIntegrityFailure    = errors.New("artifact transfer integrity verification failed")
)

const (
	maxArtifactPageSize     = 100
	defaultArtifactPageSize = 50
	maxLeaseDuration        = 30 * 24 * time.Hour
	maxUploadDuration       = 24 * time.Hour
	defaultUploadDuration   = 2 * time.Hour
	maxArtifactChunkBytes   = 4 << 20
	defaultDownloadChunk    = 256 << 10
	maxDownloadChunk        = 1 << 20
)

var reasonCodePattern = regexp.MustCompile(`^[A-Z][A-Z0-9_]{1,63}$`)

// Identity is resolved from authenticated transport state. Identity fields in
// CommandContext are evidence only and never grant access.
type Identity struct {
	TenantID  string
	ProjectID string
	Principal string
}

type IdentityResolver interface {
	Resolve(context.Context) (Identity, error)
}

type Clock interface{ Now() time.Time }

type realClock struct{}

func (realClock) Now() time.Time { return time.Now().UTC() }

// StagingReceiptStore validates an immutable receipt produced by the artifact
// transfer plane. Implementations must verify content digest and exact size;
// existence alone is insufficient.
type StagingReceiptStore interface {
	VerifyReceipt(context.Context, Identity, string, *artifactv1.ArtifactRef) error
}

type StagingVerifier interface {
	Verify(context.Context, Identity, string, *artifactv1.ArtifactRef) error
}

type receiptVerifier struct{ store StagingReceiptStore }

func NewStagingVerifier(store StagingReceiptStore) (StagingVerifier, error) {
	if store == nil {
		return nil, errors.New("staging receipt store is required")
	}
	return receiptVerifier{store: store}, nil
}

func (v receiptVerifier) Verify(ctx context.Context, identity Identity, receipt string, artifact *artifactv1.ArtifactRef) error {
	if !validDigest(receipt) || artifact == nil || !validDigest(artifact.GetDigest()) {
		return ErrStagingUnverified
	}
	if err := v.store.VerifyReceipt(ctx, identity, receipt, clone(artifact)); err != nil {
		return fmt.Errorf("%w: %w", ErrStagingUnverified, err)
	}
	return nil
}

// Repository accepts and returns generated protobuf resources. Implementations
// clone all messages at the boundary and keep private SQL row types private.
type ServiceRepository interface {
	GetArtifact(context.Context, Identity, string) (*artifactv1.ArtifactRef, time.Time, error)
	ListArtifacts(context.Context, Identity, ArtifactPage) ([]*artifactv1.ArtifactRef, *ArtifactCursor, time.Time, error)
	ResolveArtifactAlias(context.Context, Identity, string) (*artifactv1.ArtifactRef, error)
	CommitArtifact(context.Context, Identity, *artifactv1.CommitArtifactCommand, string, time.Time) (*artifactv1.ArtifactRef, bool, error)
	QuarantineArtifact(context.Context, Identity, *internalartifactv1.QuarantineArtifactRequest, string, time.Time) (*jobv1.Operation, bool, error)
	AcquireArtifactLease(context.Context, Identity, *internalartifactv1.AcquireArtifactLeaseRequest, string, time.Time) (*commonv1.ResourceRef, bool, error)
	ReleaseArtifactLease(context.Context, Identity, *internalartifactv1.ReleaseArtifactLeaseRequest, string, time.Time) (bool, error)
}

// TransferRepository is a generated-message boundary around durable resumable
// transfer state. Provider-specific object metadata remains in DownloadSource.
type TransferRepository interface {
	BeginArtifactUpload(context.Context, Identity, *internalartifactv1.BeginArtifactUploadRequest, string, time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error)
	UploadArtifactChunk(context.Context, Identity, *internalartifactv1.UploadArtifactChunkRequest, string, time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error)
	GetArtifactUpload(context.Context, Identity, string, time.Time) (*internalartifactv1.ArtifactUploadSession, error)
	FinalizeArtifactUpload(context.Context, Identity, *internalartifactv1.FinalizeArtifactUploadRequest, string, time.Time) (*internalartifactv1.ArtifactUploadSession, *internalartifactv1.ArtifactStagingReceipt, bool, error)
	AbortArtifactUpload(context.Context, Identity, *internalartifactv1.AbortArtifactUploadRequest, string, time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error)
	QuarantineArtifactUpload(context.Context, Identity, *internalartifactv1.QuarantineArtifactUploadRequest, string, time.Time) (*internalartifactv1.ArtifactUploadSession, bool, error)
	OpenArtifact(context.Context, Identity, string, int64) (*artifactv1.ArtifactRef, io.ReadCloser, error)
}

type DownloadSource struct {
	Artifact *artifactv1.ArtifactRef
	Object   objectstorage.Object
}

type ArtifactPage struct {
	Limit       int
	State       string
	Order       string
	Filter      string
	AfterTime   time.Time
	AfterDigest string
}

type ArtifactCursor struct {
	AfterTime   time.Time
	AfterDigest string
}

type SQLRepository struct {
	DB      *sql.DB
	Staging StagingVerifier
	Events  EventFactory
	Objects objectstorage.TransferObjectStore
}

type EventFactory interface {
	Committed(Identity, *artifactv1.ArtifactRef, *commonv1.CommandContext, uint64, time.Time) (*commonv1.EventEnvelope, error)
	Quarantined(Identity, *artifactv1.ArtifactRef, string, []*artifactv1.EvidenceRef, *commonv1.CommandContext, uint64, time.Time) (*commonv1.EventEnvelope, error)
	StagingFinalized(Identity, string, *artifactv1.ArtifactRef, string, *commonv1.CommandContext, uint64, time.Time, time.Time) (*commonv1.EventEnvelope, error)
}

func (r SQLRepository) validate() error {
	if r.DB == nil || r.Staging == nil || r.Events == nil {
		return errors.New("artifact SQL repository requires database, staging verifier, and event factory")
	}
	return nil
}

func (r SQLRepository) validateTransfer() error {
	if err := r.validate(); err != nil {
		return err
	}
	if r.Objects == nil {
		return errors.New("artifact SQL transfer repository requires object storage")
	}
	return nil
}

type pageToken struct {
	Version     int    `json:"v"`
	Kind        string `json:"kind"`
	Tenant      string `json:"tenant"`
	Project     string `json:"project"`
	Filter      string `json:"filter"`
	Order       string `json:"order"`
	AfterTime   string `json:"after_time"`
	AfterDigest string `json:"after_digest"`
}

type PageTokenCodec struct{ key []byte }

func NewPageTokenCodec(key []byte) (*PageTokenCodec, error) {
	if len(key) < 32 {
		return nil, errors.New("artifact page token HMAC key must be at least 32 bytes")
	}
	return &PageTokenCodec{key: append([]byte(nil), key...)}, nil
}

func (c *PageTokenCodec) Encode(identity Identity, page ArtifactPage, cursor *ArtifactCursor) (string, error) {
	if c == nil || cursor == nil || cursor.AfterTime.IsZero() || !validDigest(cursor.AfterDigest) {
		return "", ErrPageToken
	}
	payload, err := json.Marshal(pageToken{Version: 1, Kind: "artifacts", Tenant: identity.TenantID, Project: identity.ProjectID, Filter: page.Filter, Order: page.Order, AfterTime: cursor.AfterTime.UTC().Format(time.RFC3339Nano), AfterDigest: cursor.AfterDigest})
	if err != nil {
		return "", ErrPageToken
	}
	signature := hmac.New(sha256.New, c.key)
	_, _ = signature.Write(payload)
	return base64.RawURLEncoding.EncodeToString(payload) + "." + base64.RawURLEncoding.EncodeToString(signature.Sum(nil)), nil
}

func (c *PageTokenCodec) Decode(token string, identity Identity, page ArtifactPage) (*ArtifactCursor, error) {
	if c == nil || len(token) > 4096 {
		return nil, ErrPageToken
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 {
		return nil, ErrPageToken
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return nil, ErrPageToken
	}
	supplied, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, ErrPageToken
	}
	expected := hmac.New(sha256.New, c.key)
	_, _ = expected.Write(payload)
	if !hmac.Equal(supplied, expected.Sum(nil)) {
		return nil, ErrPageToken
	}
	var decoded pageToken
	if err = json.Unmarshal(payload, &decoded); err != nil || decoded.Version != 1 || decoded.Kind != "artifacts" || decoded.Tenant != identity.TenantID || decoded.Project != identity.ProjectID || decoded.Filter != page.Filter || decoded.Order != page.Order || !validDigest(decoded.AfterDigest) {
		return nil, ErrPageToken
	}
	after, err := time.Parse(time.RFC3339Nano, decoded.AfterTime)
	if err != nil {
		return nil, ErrPageToken
	}
	return &ArtifactCursor{AfterTime: after.UTC(), AfterDigest: decoded.AfterDigest}, nil
}

func validateIdentity(identity Identity) error {
	for _, value := range []string{identity.TenantID, identity.ProjectID, identity.Principal} {
		if value == "" || len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
			return ErrUnauthenticated
		}
	}
	return nil
}

func validateArtifact(identity Identity, artifact *artifactv1.ArtifactRef, input bool) error {
	if artifact == nil || !validDigest(artifact.GetDigest()) || artifact.GetMediaType() == "" || len(artifact.GetMediaType()) > 255 || strings.ContainsAny(artifact.GetMediaType(), "\x00\r\n") || artifact.GetSizeBytes() < 0 || artifact.GetSizeBytes() > 5*1024*1024*1024*1024 {
		return ErrInvalidArgument
	}
	if input && artifact.GetUri() != "" {
		return fmt.Errorf("%w: provider storage locators are not accepted", ErrInvalidArgument)
	}
	if artifact.GetIntegrityDigest() != "" && artifact.GetIntegrityDigest() != artifact.GetDigest() {
		return fmt.Errorf("%w: integrity digest differs from content digest", ErrInvalidArgument)
	}
	if (artifact.GetSchemaId() == "") != (artifact.GetSchemaVersion() == "") {
		return fmt.Errorf("%w: schema id and version must be present together", ErrInvalidArgument)
	}
	_ = identity
	return nil
}

func validDigest(value string) bool {
	if !strings.HasPrefix(value, "sha256:") || len(value) != len("sha256:")+64 || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}

func validateCommandContext(identity Identity, command proto.Message, commandContext *commonv1.CommandContext, at time.Time) (string, error) {
	if command == nil || commandContext == nil || commandContext.GetRequestId() == "" || len(commandContext.GetRequestId()) > 255 || commandContext.GetIdempotencyKey() == "" || len(commandContext.GetIdempotencyKey()) > 255 {
		return "", ErrInvalidArgument
	}
	if commandContext.GetTenantId() != "" && commandContext.GetTenantId() != identity.TenantID || commandContext.GetProjectId() != "" && commandContext.GetProjectId() != identity.ProjectID || commandContext.GetPrincipalId() != "" && commandContext.GetPrincipalId() != identity.Principal {
		return "", ErrPermissionDenied
	}
	if deadline := commandContext.GetDeadline(); deadline != nil {
		if err := deadline.CheckValid(); err != nil || !deadline.AsTime().After(at) {
			return "", ErrInvalidArgument
		}
	}
	copyMessage := proto.Clone(command)
	contextField := copyMessage.ProtoReflect().Descriptor().Fields().ByName("context")
	if contextField == nil || contextField.Message() == nil {
		return "", ErrInvalidArgument
	}
	copyMessage.ProtoReflect().Clear(contextField)
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copyMessage)
	if err != nil {
		return "", ErrInvalidArgument
	}
	digestValue := sha256.Sum256(encoded)
	digest := "sha256:" + hex.EncodeToString(digestValue[:])
	if provided := commandContext.GetCanonicalRequestDigest(); provided != "" && subtle.ConstantTimeCompare([]byte(provided), []byte(digest)) != 1 {
		return "", ErrIdempotencyConflict
	}
	commandContext.CanonicalRequestDigest = digest
	return digest, nil
}

func sanitizeArtifact(value *artifactv1.ArtifactRef) *artifactv1.ArtifactRef {
	result := clone(value)
	if result != nil {
		result.Uri = ""
	}
	return result
}

func clone[T proto.Message](value T) T {
	if any(value) == nil {
		var zero T
		return zero
	}
	return proto.Clone(value).(T)
}

func canonicalParent(identity Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func canonicalArtifactName(identity Identity, digest string) string {
	return canonicalParent(identity) + "/artifacts/" + digest
}

func canonicalUploadName(identity Identity, uploadID string) string {
	return canonicalParent(identity) + "/artifactUploads/" + uploadID
}

func uploadIDFromName(identity Identity, name string) (string, error) {
	prefix := canonicalParent(identity) + "/artifactUploads/"
	if !strings.HasPrefix(name, prefix) {
		return "", ErrPermissionDenied
	}
	id := strings.TrimPrefix(name, prefix)
	if !aliasPattern.MatchString(id) {
		return "", ErrInvalidArgument
	}
	return id, nil
}

func artifactDigestFromName(identity Identity, name string) (string, error) {
	prefix := canonicalParent(identity) + "/artifacts/"
	if !strings.HasPrefix(name, prefix) || !validDigest(strings.TrimPrefix(name, prefix)) {
		return "", ErrPermissionDenied
	}
	return strings.TrimPrefix(name, prefix), nil
}

func etag(kind, tenantID, projectID, id string, revision int64) string {
	value := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%s\x00%s\x00%d", kind, tenantID, projectID, id, revision)))
	return base64.RawURLEncoding.EncodeToString(value[:])
}

func operationID(identity Identity, key string) string {
	value := sha256.Sum256([]byte(identity.TenantID + "\x00" + identity.ProjectID + "\x00artifact-quarantine\x00" + key))
	return canonicalParent(identity) + "/operations/artifact-quarantine-" + hex.EncodeToString(value[:16])
}

func leaseID(identity Identity, digest string) string {
	value := sha256.Sum256([]byte(identity.TenantID + "\x00" + identity.ProjectID + "\x00" + identity.Principal + "\x00" + digest))
	return hex.EncodeToString(value[:16])
}

func completedQuarantineOperation(identity Identity, id string, artifact *artifactv1.ArtifactRef, at time.Time) *jobv1.Operation {
	targetName := canonicalArtifactName(identity, artifact.GetDigest())
	return &jobv1.Operation{
		OperationId: id, TenantId: identity.TenantID, ProjectId: identity.ProjectID,
		State: jobv1.OperationState_OPERATION_STATE_SUCCEEDED, ResourceVersion: 1,
		CreatedAt: timestamppb.New(at.UTC()), UpdatedAt: timestamppb.New(at.UTC()), Done: true,
		Etag:   etag("artifact-operation", identity.TenantID, identity.ProjectID, id, 1),
		Target: &commonv1.ResourceRef{ResourceType: "artifact", ResourceId: artifact.GetDigest(), TenantId: identity.TenantID, ProjectId: identity.ProjectID, ResourceVersion: 1, Name: targetName, Etag: etag("artifact", identity.TenantID, identity.ProjectID, artifact.GetDigest(), 1)},
	}
}

var _ internalartifactv1.ArtifactServiceServer = (*Server)(nil)
