package policies

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
	internalpolicyv1 "github.com/mindclade/mindclade/protocols/generated/go/internalrpc/policy/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

var (
	ErrUnauthenticated     = errors.New("authenticated identity is required")
	ErrPermissionDenied    = errors.New("policy resource is outside the authenticated scope")
	ErrInvalidArgument     = errors.New("invalid policy request")
	ErrNotFound            = errors.New("policy resource not found")
	ErrAlreadyExists       = errors.New("policy resource already exists")
	ErrIdempotencyConflict = errors.New("idempotency key was reused with different policy intent")
	ErrRevisionConflict    = errors.New("policy revision or etag conflict")
	ErrInvalidTransition   = errors.New("invalid policy lifecycle transition")
	ErrDeadlineExceeded    = errors.New("policy request deadline has elapsed")
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

type PolicyPage struct {
	Limit     int
	AfterTime time.Time
	AfterName string
	Filter    string
	Order     string
	State     policyv1.UsePolicyState
}

// PolicyEngineResult is behavior, not a second wire model. The repository owns
// canonical identity, digests, timestamps, and generated message assembly.
type PolicyEngineResult struct {
	Outcome     policyv1.AuthorizationOutcome
	ReasonCode  string
	SafeReason  string
	Constraints []*policyv1.AuthorizationConstraint
	ExpireTime  time.Time
}

type EvaluationEngine interface {
	Evaluate(context.Context, Identity, *internalpolicyv1.EvaluateAuthorizationRequest, []*policyv1.PolicyReference) (PolicyEngineResult, error)
}

// DenyAllEvaluator is the safe production default when no policy interpreter
// has been configured. Unavailability can never turn into an allow decision.
type DenyAllEvaluator struct{ ReasonCode string }

func (d DenyAllEvaluator) Evaluate(context.Context, Identity, *internalpolicyv1.EvaluateAuthorizationRequest, []*policyv1.PolicyReference) (PolicyEngineResult, error) {
	reason := d.ReasonCode
	if reason == "" {
		reason = "POLICY_ENGINE_UNAVAILABLE"
	}
	return PolicyEngineResult{
		Outcome:    policyv1.AuthorizationOutcome_AUTHORIZATION_OUTCOME_DENY,
		ReasonCode: reason,
		SafeReason: "authorization could not be granted",
	}, nil
}

type Repository interface {
	EvaluateAuthorization(context.Context, Identity, *internalpolicyv1.EvaluateAuthorizationRequest, string, time.Time) (*policyv1.AuthorizationDecision, bool, error)
	CreateUsePolicy(context.Context, Identity, *internalpolicyv1.CreateUsePolicyRequest, string, time.Time) (*jobv1.Operation, bool, error)
	UpdateUsePolicy(context.Context, Identity, *internalpolicyv1.UpdateUsePolicyRequest, string, time.Time) (*jobv1.Operation, bool, error)
	GetUsePolicy(context.Context, Identity, string) (*policyv1.UsePolicy, error)
	ListUsePolicies(context.Context, Identity, PolicyPage) ([]*policyv1.UsePolicy, string, time.Time, error)
	ActivateUsePolicy(context.Context, Identity, *internalpolicyv1.ActivateUsePolicyRequest, string, time.Time) (*jobv1.Operation, bool, error)
	RevokeUsePolicy(context.Context, Identity, *internalpolicyv1.RevokeUsePolicyRequest, string, time.Time) (*jobv1.Operation, bool, error)
	ResolvePolicySnapshot(context.Context, Identity, string, time.Time) (*policyv1.PolicyReference, error)
}

type EventFactory interface {
	DecisionRecorded(Identity, *policyv1.AuthorizationDecision, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	PolicyCreated(Identity, *policyv1.UsePolicy, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	PolicyUpdated(Identity, *policyv1.UsePolicy, []string, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	PolicyActivated(Identity, *policyv1.UsePolicy, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
	PolicyRevoked(Identity, *policyv1.UsePolicy, string, *jobv1.Operation, *commonv1.CommandContext, time.Time) (*commonv1.EventEnvelope, error)
}

type SQLRepository struct {
	DB         *sql.DB
	Pagination *PageTokenCodec
	Events     EventFactory
	Evaluator  EvaluationEngine
}

var _ internalpolicyv1.PolicyServiceServer = (*Server)(nil)

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
		return "", fmt.Errorf("canonicalize policy command: %w", err)
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

func validSHA256(value string) bool {
	if len(value) != 71 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}

func validateArtifact(value *artifactv1.ArtifactRef) error {
	if value == nil || !validSHA256(value.GetDigest()) || value.GetMediaType() == "" || value.GetSizeBytes() < 0 ||
		(value.GetIntegrityDigest() != "" && !validSHA256(value.GetIntegrityDigest())) {
		return ErrInvalidArgument
	}
	return nil
}

func validatePolicyReference(value *policyv1.PolicyReference, now time.Time) error {
	if value == nil || value.GetName() == "" || value.GetUid() == "" || value.GetPolicyType() == "" || value.GetVersion() == "" ||
		!validSHA256(value.GetDigest()) || value.GetResourceRevision() <= 0 || value.GetEffectiveTime() == nil || value.GetEffectiveTime().CheckValid() != nil ||
		validateArtifact(value.GetDocument()) != nil {
		return ErrInvalidArgument
	}
	if value.GetEffectiveTime().AsTime().After(now) {
		return ErrInvalidArgument
	}
	if expiry := value.GetExpireTime(); expiry != nil {
		if expiry.CheckValid() != nil || !expiry.AsTime().After(now) || !expiry.AsTime().After(value.GetEffectiveTime().AsTime()) {
			return ErrInvalidArgument
		}
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

func projectParent(identity Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func policyName(identity Identity, value string) (string, error) {
	prefix := projectParent(identity) + "/usePolicies/"
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

func usePolicyResource(identity Identity, value *policyv1.UsePolicy) *commonv1.ResourceRef {
	return &commonv1.ResourceRef{
		ResourceType: "use_policy", ResourceId: lastSegment(value.GetName()), TenantId: identity.TenantID,
		ProjectId: identity.ProjectID, ResourceVersion: value.GetRevision(), Name: value.GetName(), Etag: value.GetEtag(),
	}
}

func operationResource(value *jobv1.Operation) *commonv1.ResourceRef {
	if value == nil {
		return nil
	}
	return &commonv1.ResourceRef{
		ResourceType: "operation", ResourceId: lastSegment(value.GetOperationId()), TenantId: value.GetTenantId(),
		ProjectId: value.GetProjectId(), ResourceVersion: value.GetResourceVersion(), Name: value.GetOperationId(), Etag: value.GetEtag(),
	}
}
