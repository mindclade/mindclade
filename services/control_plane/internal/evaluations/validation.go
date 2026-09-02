package evaluations

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"math"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	evaluationv1 "github.com/mindclade/mindclade/protocols/generated/go/evaluation/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	policyv1 "github.com/mindclade/mindclade/protocols/generated/go/policy/v1"
)

const (
	defaultPageSize = 50
	maximumPageSize = 200
)

func validateIdentity(identity Identity) error {
	for label, value := range map[string]string{"tenant": identity.TenantID, "project": identity.ProjectID, "principal": identity.Principal} {
		if value == "" || len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
			return fmt.Errorf("%w: invalid %s", ErrUnauthenticated, label)
		}
	}
	return nil
}

func canonicalDigest(command proto.Message) (string, error) {
	if command == nil {
		return "", ErrInvalidArgument
	}
	copy := proto.Clone(command)
	message := copy.ProtoReflect()
	field := message.Descriptor().Fields().ByName(protoreflect.Name("context"))
	if field != nil && field.Kind() == protoreflect.MessageKind {
		message.Clear(field)
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(copy)
	if err != nil {
		return "", fmt.Errorf("canonicalize evaluation command: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateContext(identity Identity, command proto.Message, value *commonv1.CommandContext, now time.Time) (string, error) {
	if err := validateIdentity(identity); err != nil {
		return "", err
	}
	if value == nil || value.GetRequestId() == "" || value.GetIdempotencyKey() == "" || now.IsZero() {
		return "", fmt.Errorf("%w: context, request_id, and idempotency_key are required", ErrInvalidArgument)
	}
	for label, item := range map[string]string{"request_id": value.GetRequestId(), "idempotency_key": value.GetIdempotencyKey()} {
		if len(item) > 255 || strings.TrimSpace(item) != item || strings.ContainsAny(item, "\x00\r\n") {
			return "", fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
		}
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID || value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID || value.GetPrincipalId() != "" && value.GetPrincipalId() != identity.Principal {
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
	digest, err := canonicalDigest(command)
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
		if character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || index > 0 && strings.ContainsRune("._~-", character) {
			continue
		}
		return false
	}
	return true
}

func projectParent(identity Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func runName(identity Identity, id string) string {
	return projectParent(identity) + "/evaluationRuns/" + id
}

func resultName(identity Identity, id string) string {
	return projectParent(identity) + "/evaluationResults/" + id
}

func decisionName(identity Identity, id string) string {
	return projectParent(identity) + "/promotionDecisions/" + id
}

func canonicalScopedName(identity Identity, name, collection string) (string, error) {
	prefix := projectParent(identity) + "/" + collection + "/"
	if !strings.HasPrefix(name, prefix) || !validID(strings.TrimPrefix(name, prefix)) {
		return "", ErrPermissionDenied
	}
	return name, nil
}

func validateArtifact(value *artifactv1.ArtifactRef, label string, required bool) error {
	if value == nil {
		if required {
			return fmt.Errorf("%w: %s is required", ErrInvalidArgument, label)
		}
		return nil
	}
	if !validSHA256(value.GetDigest()) || value.GetMediaType() == "" || value.GetSizeBytes() < 0 || value.GetSizeBytes() > 1<<50 || value.GetIntegrityDigest() != "" && !validSHA256(value.GetIntegrityDigest()) || len(value.GetUri()) > 8192 {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	return nil
}

func validateReference(identity Identity, value *commonv1.ResourceRef, label string) error {
	if value == nil || value.GetResourceType() == "" || value.GetResourceId() == "" || value.GetName() == "" || value.GetResourceVersion() < 0 || len(value.GetName()) > 2048 {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID || value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validatePolicy(value *policyv1.PolicyReference) error {
	if value == nil || value.GetName() == "" || value.GetUid() == "" || value.GetPolicyType() == "" || value.GetVersion() == "" || !validSHA256(value.GetDigest()) || value.GetResourceRevision() <= 0 || value.GetEffectiveTime() == nil || value.GetEffectiveTime().CheckValid() != nil {
		return fmt.Errorf("%w: invalid policy snapshot", ErrInvalidArgument)
	}
	if err := validateArtifact(value.GetDocument(), "policy document", true); err != nil {
		return err
	}
	if expiry := value.GetExpireTime(); expiry != nil && (expiry.CheckValid() != nil || !expiry.AsTime().After(value.GetEffectiveTime().AsTime())) {
		return fmt.Errorf("%w: invalid policy expiry", ErrInvalidArgument)
	}
	return nil
}

func validateFence(identity Identity, value *jobv1.LeaseFence, now time.Time) error {
	if value == nil || identity.WorkerID == "" || identity.LeaseToken == "" || value.GetJobId() == "" || value.GetRunId() == "" || value.GetAttemptId() == "" || value.GetLeaseEpoch() == 0 || value.GetDeadline() == nil || value.GetDeadline().CheckValid() != nil || !now.Before(value.GetDeadline().AsTime()) {
		return ErrStaleFence
	}
	if value.GetTenantId() != identity.TenantID || value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validateMetric(value *evaluationv1.MetricSummary) error {
	if value == nil || value.GetMetricId() == "" || value.GetMetricVersion() == "" || value.GetDirection() == evaluationv1.MetricDirection_METRIC_DIRECTION_UNSPECIFIED || math.IsNaN(value.GetValue()) || math.IsInf(value.GetValue(), 0) {
		return ErrInvalidArgument
	}
	lower, lowerSet := value.GetIntervalLower(), value.IntervalLower != nil
	upper, upperSet := value.GetIntervalUpper(), value.IntervalUpper != nil
	if lowerSet != upperSet || lowerSet && (math.IsNaN(lower) || math.IsInf(lower, 0) || math.IsNaN(upper) || math.IsInf(upper, 0) || lower > upper) {
		return ErrInvalidArgument
	}
	return nil
}

func resourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func pageLimit(requested uint32) (int, error) {
	if requested == 0 {
		return defaultPageSize, nil
	}
	if requested > maximumPageSize {
		return 0, fmt.Errorf("%w: page_size exceeds %d", ErrInvalidArgument, maximumPageSize)
	}
	return int(requested), nil
}
