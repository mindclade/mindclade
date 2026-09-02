package models

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
	internalmodelv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/model/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	modelv1 "github.com/mindclade/mindclade/protocols/generated/go/model/v1"
)

var (
	ErrUnauthenticated          = errors.New("authenticated identity is required")
	ErrPermissionDenied         = errors.New("resource is outside the authenticated scope")
	ErrInvalidArgument          = errors.New("invalid model request")
	ErrNotFound                 = errors.New("model resource not found")
	ErrAlreadyExists            = errors.New("model resource already exists")
	ErrIdempotencyConflict      = errors.New("idempotency key was reused with different command content")
	ErrRevisionConflict         = errors.New("model release revision or etag conflict")
	ErrInvalidTransition        = errors.New("invalid model release stage transition")
	ErrEventContractUnavailable = errors.New("authoritative event contract is unavailable")
	ErrDeadlineExceeded         = errors.New("model command deadline has elapsed")
)

const RegisterReleaseEventContract = "mindclade.events.model.v1.ModelReleaseRegistered"

type (
	Identity         struct{ TenantID, ProjectID, Principal string }
	IdentityResolver interface {
		Resolve(context.Context) (Identity, error)
	}
)

type (
	Clock     interface{ Now() time.Time }
	realClock struct{}
)

func (realClock) Now() time.Time { return time.Now().UTC() }

type ModelPage struct {
	Limit                    int
	AfterTime                time.Time
	AfterName, Filter, Order string
	State                    modelv1.ModelState
}
type ReleasePage struct {
	Limit                    int
	Parent                   string
	AfterTime                time.Time
	AfterName, Filter, Order string
	Stage                    modelv1.ModelReleaseStage
}

type Repository interface {
	RegisterModel(context.Context, Identity, *modelv1.RegisterModelCommand, string, time.Time) (*jobv1.Operation, bool, error)
	GetModel(context.Context, Identity, string) (*modelv1.Model, error)
	ListModels(context.Context, Identity, ModelPage) ([]*modelv1.Model, string, time.Time, error)
	RegisterModelRelease(context.Context, Identity, *modelv1.RegisterModelReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error)
	GetModelRelease(context.Context, Identity, string) (*modelv1.ModelRelease, error)
	ListModelReleases(context.Context, Identity, ReleasePage) ([]*modelv1.ModelRelease, string, time.Time, error)
	PromoteModelRelease(context.Context, Identity, *modelv1.PromoteModelReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error)
	RevokeModelRelease(context.Context, Identity, *modelv1.RevokeModelReleaseCommand, string, time.Time) (*jobv1.Operation, bool, error)
}

type EventFactory interface {
	Registered(Identity, *modelv1.Model, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Promoted(Identity, *modelv1.ModelRelease, modelv1.ModelReleaseStage, []*artifactv1.EvidenceRef, *artifactv1.EvidenceRef, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	Revoked(Identity, *modelv1.ModelRelease, []*artifactv1.EvidenceRef, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

// ModelReleaseEventFactory is kept separate so alternate EventFactory
// implementations must explicitly opt into immutable release admission.
type ModelReleaseEventFactory interface {
	ReleaseRegistered(Identity, *modelv1.ModelRelease, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type SQLRepository struct {
	DB         *sql.DB
	Pagination *PageTokenCodec
	Events     EventFactory
}

var _ internalmodelv1.ModelServiceServer = (*Server)(nil)

func clone[T proto.Message](value T) T {
	if any(value) == nil {
		var zero T
		return zero
	}
	return proto.Clone(value).(T)
}

func cloneSlice[T proto.Message](values []T) []T {
	result := make([]T, 0, len(values))
	for _, v := range values {
		result = append(result, clone(v))
	}
	return result
}

func validateIdentity(identity Identity) error {
	for _, v := range []string{identity.TenantID, identity.ProjectID, identity.Principal} {
		if v == "" || len(v) > 255 || strings.TrimSpace(v) != v || strings.ContainsAny(v, "\x00\r\n") {
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
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateContext(identity Identity, command proto.Message, value *commonv1.CommandContext, now time.Time) (string, error) {
	if err := validateIdentity(identity); err != nil {
		return "", err
	}
	if value == nil || value.GetRequestId() == "" || value.GetIdempotencyKey() == "" {
		return "", ErrInvalidArgument
	}
	for _, v := range []string{value.GetRequestId(), value.GetIdempotencyKey()} {
		if len(v) > 255 || strings.TrimSpace(v) != v || strings.ContainsAny(v, "\x00\r\n") {
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

func validSHA256(v string) bool {
	if len(v) != 71 || !strings.HasPrefix(v, "sha256:") || v != strings.ToLower(v) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(v, "sha256:"))
	return err == nil
}

func validateArtifact(v *artifactv1.ArtifactRef, label string) error {
	if v == nil || !validSHA256(v.GetDigest()) || v.GetMediaType() == "" || v.GetSizeBytes() < 0 || (v.GetIntegrityDigest() != "" && !validSHA256(v.GetIntegrityDigest())) {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	return nil
}

func validateEvidence(v *artifactv1.EvidenceRef, label string) error {
	if v == nil || !validSHA256(v.GetDigest()) || !validSHA256(v.GetSubjectDigest()) || v.GetEvidenceKind() == "" || (v.GetPolicyDigest() != "" && !validSHA256(v.GetPolicyDigest())) {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	return nil
}

func validateReference(identity Identity, v *commonv1.ResourceRef, kind, label string) error {
	if v == nil || v.GetResourceType() != kind || v.GetResourceId() == "" || v.GetName() == "" || v.GetResourceVersion() < 0 {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	if v.GetTenantId() != "" && v.GetTenantId() != identity.TenantID {
		return ErrPermissionDenied
	}
	if v.GetProjectId() != "" && v.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validID(v string) bool {
	if v == "" || len(v) > 128 {
		return false
	}
	for i, c := range v {
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || (i > 0 && strings.ContainsRune("._~-", c)) {
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

func projectParent(identity Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func modelName(identity Identity, id string) (string, error) {
	prefix := projectParent(identity) + "/models/"
	if strings.HasPrefix(id, prefix) {
		id = strings.TrimPrefix(id, prefix)
	} else if strings.HasPrefix(id, "tenants/") {
		return "", ErrNotFound
	}
	if !validID(id) {
		return "", ErrInvalidArgument
	}
	return prefix + id, nil
}

func releaseName(identity Identity, id string) (string, error) {
	prefix := projectParent(identity) + "/models/"
	if !strings.HasPrefix(id, prefix) || !strings.Contains(strings.TrimPrefix(id, prefix), "/releases/") {
		return "", ErrNotFound
	}
	return id, nil
}

func missingEvent(contract string) error {
	return fmt.Errorf("%w: %s", ErrEventContractUnavailable, contract)
}
