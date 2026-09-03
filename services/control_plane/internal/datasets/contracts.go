package datasets

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

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	datasetv1 "github.com/mindclade/mindclade/protocols/generated/go/dataset/v1"
	internaldatasetv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/dataset/v1"
	operationv1 "github.com/mindclade/mindclade/protocols/generated/go/operation/v1"
)

var (
	ErrUnauthenticated          = errors.New("authenticated identity is required")
	ErrPermissionDenied         = errors.New("resource is outside the authenticated scope")
	ErrInvalidArgument          = errors.New("invalid dataset request")
	ErrNotFound                 = errors.New("dataset resource not found")
	ErrAlreadyExists            = errors.New("dataset resource already exists")
	ErrIdempotencyConflict      = errors.New("idempotency key was reused with different command content")
	ErrRevisionConflict         = errors.New("dataset resource revision or etag conflict")
	ErrInvalidTransition        = errors.New("invalid dataset lifecycle transition")
	ErrEventContractUnavailable = errors.New("authoritative event contract is unavailable")
	ErrDeadlineExceeded         = errors.New("dataset command deadline has elapsed")
)

// These constants make the authoritative event names explicit for diagnostics
// and alternate repositories that cannot emit the registered payload family.
const (
	CreateEventContract  = "mindclade.events.dataset.v1.DatasetCreated"
	UpdateEventContract  = "mindclade.events.dataset.v1.DatasetUpdated"
	PublishEventContract = "mindclade.events.dataset.v1.DatasetReleasePublished"
	RevokeEventContract  = "mindclade.events.dataset.v1.DatasetReleaseRevoked"
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

// PostgreSQL timestamptz resolves to microseconds. Truncating here keeps an
// accepted command and its idempotent replay byte-identical: without it a
// response built in memory keeps nanosecond digits the database drops.
func (realClock) Now() time.Time { return time.Now().UTC().Truncate(time.Microsecond) }

type DatasetPage struct {
	Limit     int
	AfterTime time.Time
	AfterName string
	Filter    string
	Order     string
	State     datasetv1.DatasetState
}

type ReleasePage struct {
	Limit     int
	Parent    string
	AfterTime time.Time
	AfterName string
	Filter    string
	Order     string
	State     datasetv1.DatasetReleaseState
}

// Repository boundaries accept and return generated values only. Implementors
// clone every message so callers cannot mutate persisted state through aliases.
type Repository interface {
	CreateDataset(context.Context, Identity, *datasetv1.CreateDatasetCommand, string, time.Time) (*operationv1.Operation, bool, error)
	GetDataset(context.Context, Identity, string) (*datasetv1.Dataset, error)
	ListDatasets(context.Context, Identity, DatasetPage) ([]*datasetv1.Dataset, string, time.Time, error)
	UpdateDataset(context.Context, Identity, *datasetv1.UpdateDatasetCommand, string, time.Time) (*operationv1.Operation, bool, error)
	PublishDatasetRelease(context.Context, Identity, *datasetv1.PublishDatasetReleaseCommand, string, time.Time) (*operationv1.Operation, bool, error)
	RevokeDatasetRelease(context.Context, Identity, *datasetv1.RevokeDatasetReleaseCommand, string, time.Time) (*operationv1.Operation, bool, error)
	GetDatasetRelease(context.Context, Identity, string) (*datasetv1.DatasetRelease, error)
	ListDatasetReleases(context.Context, Identity, ReleasePage) ([]*datasetv1.DatasetRelease, string, time.Time, error)
}

// EventFactory is the activation seam for the additive dataset event family.
// Implementations must construct registered typed protobuf payloads; the
// repository will never accept handwritten bytes or generic JSON events.
type EventFactory interface {
	Created(Identity, *datasetv1.Dataset, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Updated(Identity, *datasetv1.Dataset, []string, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Published(Identity, *datasetv1.DatasetRelease, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Revoked(Identity, *datasetv1.DatasetRelease, []*artifactv1.EvidenceRef, *operationv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type SQLRepository struct {
	DB         *sql.DB
	Pagination *PageTokenCodec
	Events     EventFactory
}

var _ internaldatasetv1.DatasetServiceServer = (*Server)(nil)

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
	for _, value := range []string{identity.TenantID, identity.ProjectID, identity.Principal} {
		if value == "" || len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
			return ErrUnauthenticated
		}
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
		return "", fmt.Errorf("canonicalize dataset command: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateContext(identity Identity, command proto.Message, value *commonv1.CommandContext, now time.Time) (string, error) {
	if err := validateIdentity(identity); err != nil {
		return "", err
	}
	if value == nil || value.GetRequestId() == "" || value.GetIdempotencyKey() == "" {
		return "", fmt.Errorf("%w: command context, request_id, and idempotency_key are required", ErrInvalidArgument)
	}
	for _, item := range []string{value.GetRequestId(), value.GetIdempotencyKey()} {
		if len(item) > 255 || strings.TrimSpace(item) != item || strings.ContainsAny(item, "\x00\r\n") {
			return "", ErrInvalidArgument
		}
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID {
		return "", ErrPermissionDenied
	}
	if value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID {
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

func missingEvent(contract string) error {
	return fmt.Errorf("%w: %s", ErrEventContractUnavailable, contract)
}

func validSHA256(value string) bool {
	if len(value) != 71 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}

func validateArtifact(value *artifactv1.ArtifactRef, label string) error {
	if value == nil || !validSHA256(value.GetDigest()) || value.GetMediaType() == "" || value.GetSizeBytes() < 0 ||
		(value.GetIntegrityDigest() != "" && !validSHA256(value.GetIntegrityDigest())) {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	return nil
}

func validateEvidence(value *artifactv1.EvidenceRef, label string) error {
	if value == nil || !validSHA256(value.GetDigest()) || !validSHA256(value.GetSubjectDigest()) || value.GetEvidenceKind() == "" ||
		(value.GetPolicyDigest() != "" && !validSHA256(value.GetPolicyDigest())) {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	return nil
}

func validateReference(identity Identity, value *commonv1.ResourceRef, kind, label string) error {
	if value == nil || value.GetResourceType() != kind || value.GetResourceId() == "" || value.GetName() == "" || value.GetResourceVersion() < 0 {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID {
		return ErrPermissionDenied
	}
	if value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
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

func resourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func canonicalDatasetName(identity Identity, value string) (string, error) {
	prefix := "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID + "/datasets/"
	if strings.HasPrefix(value, prefix) {
		value = strings.TrimPrefix(value, prefix)
	} else if strings.HasPrefix(value, "tenants/") {
		return "", ErrNotFound
	}
	if !validID(value) {
		return "", ErrInvalidArgument
	}
	return prefix + value, nil
}

func canonicalReleaseName(identity Identity, value string) (string, error) {
	prefix := "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID + "/datasets/"
	remainder := strings.TrimPrefix(value, prefix)
	parts := strings.Split(remainder, "/releases/")
	if !strings.HasPrefix(value, prefix) || len(parts) != 2 || !validID(parts[0]) || !validID(parts[1]) {
		return "", ErrNotFound
	}
	return value, nil
}

func validProjectParent(identity Identity, parent string) bool {
	return parent == "tenants/"+identity.TenantID+"/projects/"+identity.ProjectID
}

func validDatasetParent(identity Identity, parent string) bool {
	prefix := "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID + "/datasets/"
	return strings.HasPrefix(parent, prefix) && len(strings.TrimPrefix(parent, prefix)) > 0 && !strings.Contains(strings.TrimPrefix(parent, prefix), "/")
}

func parseFilter(filter, prefix string, values map[string]int32) (int32, error) {
	if filter == "" {
		return 0, nil
	}
	parts := strings.Split(filter, "=")
	if len(parts) != 2 || strings.TrimSpace(parts[0]) != "state" {
		return 0, fmt.Errorf("%w: only state=<enum> is supported", ErrInvalidArgument)
	}
	value := strings.ToUpper(strings.TrimSpace(parts[1]))
	if !strings.HasPrefix(value, prefix) {
		value = prefix + value
	}
	number, ok := values[value]
	if !ok || number == 0 {
		return 0, ErrInvalidArgument
	}
	return number, nil
}
