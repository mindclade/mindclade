package experiments

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	experimentv1 "github.com/mindclade/mindclade/protocols/generated/go/experiment/v1"
)

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
	for _, field := range []string{value.GetRequestId(), value.GetIdempotencyKey()} {
		if len(field) > 255 || strings.TrimSpace(field) != field || strings.ContainsAny(field, "\x00\r\n") {
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

func validID(value string) bool {
	if value == "" || len(value) > 128 {
		return false
	}
	for index, character := range value {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') || (character >= '0' && character <= '9') || (index > 0 && strings.ContainsRune("._~-", character)) {
			continue
		}
		return false
	}
	return true
}

func validReasonCode(value string) bool {
	if value == "" || len(value) > 128 || value != strings.ToUpper(value) {
		return false
	}
	for index, character := range value {
		if (character >= 'A' && character <= 'Z') || (character >= '0' && character <= '9') || (index > 0 && character == '_') {
			continue
		}
		return false
	}
	return true
}

func validSHA256(value string) bool {
	if len(value) != 71 || !strings.HasPrefix(value, "sha256:") || strings.ToLower(value) != value {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}

func validateArtifact(value *artifactv1.ArtifactRef, label string, required bool) error {
	if value == nil {
		if required {
			return fmt.Errorf("%w: %s is required", ErrInvalidArgument, label)
		}
		return nil
	}
	if !validSHA256(value.GetDigest()) || value.GetMediaType() == "" || len(value.GetMediaType()) > 255 || value.GetSizeBytes() < 0 || (value.GetIntegrityDigest() != "" && !validSHA256(value.GetIntegrityDigest())) || len(value.GetUri()) > 4096 {
		return fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
	}
	return nil
}

func validateEvidence(value *artifactv1.EvidenceRef) error {
	if value == nil || !validSHA256(value.GetDigest()) || !validSHA256(value.GetSubjectDigest()) || value.GetEvidenceKind() == "" || len(value.GetEvidenceKind()) > 128 || (value.GetPolicyDigest() != "" && !validSHA256(value.GetPolicyDigest())) {
		return ErrInvalidArgument
	}
	return nil
}

func validateReference(identity Identity, value *commonv1.ResourceRef, kind string, requireRevision bool) error {
	if value == nil || value.GetResourceType() != kind || !validID(value.GetResourceId()) || value.GetName() == "" || value.GetResourceVersion() < 0 {
		return ErrInvalidArgument
	}
	if requireRevision && (value.GetResourceVersion() < 1 || !validSHA256(value.GetEtag())) {
		return ErrInvalidArgument
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID {
		return ErrPermissionDenied
	}
	if value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validateError(value *commonv1.ErrorDetail) error {
	if value == nil || value.GetCode() == commonv1.ErrorCode_ERROR_CODE_UNSPECIFIED || value.GetMessage() == "" || len(value.GetMessage()) > 4096 || len(value.GetFieldViolations()) > 128 || len(value.GetPreconditionViolations()) > 128 {
		return ErrInvalidArgument
	}
	if value.GetRetryAfter() != nil && value.GetRetryAfter().CheckValid() != nil {
		return ErrInvalidArgument
	}
	return nil
}

func validateMap(values map[string]string, maximumValue int) error {
	if len(values) > 128 {
		return ErrInvalidArgument
	}
	for key, value := range values {
		if key == "" || len(key) > 128 || len(value) > maximumValue || strings.TrimSpace(key) != key || strings.ContainsAny(key, "\x00\r\n") || strings.ContainsRune(value, '\x00') {
			return ErrInvalidArgument
		}
	}
	return nil
}

func projectParent(identity Identity) string {
	return "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID
}

func experimentName(identity Identity, value string) (string, error) {
	prefix := projectParent(identity) + "/experiments/"
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

func studyName(identity Identity, parent, value string) (string, error) {
	canonicalParent, err := experimentName(identity, parent)
	if err != nil {
		return "", err
	}
	prefix := canonicalParent + "/studies/"
	if strings.HasPrefix(value, prefix) {
		value = strings.TrimPrefix(value, prefix)
	} else if strings.Contains(value, "/") {
		return "", ErrNotFound
	}
	if !validID(value) {
		return "", ErrInvalidArgument
	}
	return prefix + value, nil
}

func trialName(identity Identity, parent, value string) (string, error) {
	if !validStudyParent(identity, parent) {
		return "", ErrNotFound
	}
	prefix := parent + "/trials/"
	if strings.HasPrefix(value, prefix) {
		value = strings.TrimPrefix(value, prefix)
	} else if strings.Contains(value, "/") {
		return "", ErrNotFound
	}
	if !validID(value) {
		return "", ErrInvalidArgument
	}
	return prefix + value, nil
}

func validExperimentParent(identity Identity, value string) bool {
	canonical, err := experimentName(identity, value)
	return err == nil && canonical == value
}

func validStudyParent(identity Identity, value string) bool {
	prefix := projectParent(identity) + "/experiments/"
	if !strings.HasPrefix(value, prefix) {
		return false
	}
	remainder := strings.TrimPrefix(value, prefix)
	parts := strings.Split(remainder, "/studies/")
	return len(parts) == 2 && validID(parts[0]) && validID(parts[1])
}

func parentStudy(name string) string {
	index := strings.LastIndex(name, "/trials/")
	if index < 0 {
		return ""
	}
	return name[:index]
}

func lastSegment(value string) string {
	if index := strings.LastIndexByte(value, '/'); index >= 0 {
		return value[index+1:]
	}
	return value
}

func resourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func normalizeMask(command *experimentv1.UpdateExperimentCommand) ([]string, error) {
	if command == nil || command.GetExperiment() == nil || command.GetUpdateMask() == nil || command.GetEtag() == "" || command.GetEtag() != command.GetExperiment().GetEtag() {
		return nil, ErrInvalidArgument
	}
	mask := clone(command.GetUpdateMask())
	mask.Normalize()
	if !mask.IsValid(&experimentv1.Experiment{}) || len(mask.GetPaths()) == 0 || len(mask.GetPaths()) > 4 {
		return nil, ErrInvalidArgument
	}
	allowed := map[string]bool{"display_name": true, "labels": true, "annotations": true, "policy_classification": true}
	for _, path := range mask.GetPaths() {
		if !allowed[path] {
			return nil, ErrInvalidArgument
		}
	}
	return append([]string(nil), mask.GetPaths()...), nil
}

func validateCreateExperiment(identity Identity, command *experimentv1.CreateExperimentCommand) error {
	if command == nil || command.GetContext() == nil || !validID(command.GetExperimentId()) || command.GetDisplayName() == "" || len(command.GetDisplayName()) > 512 || command.GetKind() == experimentv1.ExperimentKind_EXPERIMENT_KIND_UNSPECIFIED || command.GetPolicyClassification() == "" || len(command.GetPolicyClassification()) > 128 || len(command.GetSubjects()) == 0 || len(command.GetSubjects()) > 256 {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, command.GetProject(), "project", false); err != nil || command.GetProject().GetName() != projectParent(identity) || command.GetProject().GetResourceId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	if err := validateArtifact(command.GetIntentManifest(), "intent manifest", true); err != nil {
		return err
	}
	if err := validateReference(identity, command.GetUsePolicy(), "use_policy", true); err != nil {
		return err
	}
	for _, subject := range command.GetSubjects() {
		if subject == nil || subject.GetResourceType() == "" || !validID(subject.GetResourceId()) || subject.GetName() == "" || subject.GetResourceVersion() < 1 || !validSHA256(subject.GetEtag()) {
			return ErrInvalidArgument
		}
		if subject.GetTenantId() != "" && subject.GetTenantId() != identity.TenantID {
			return ErrPermissionDenied
		}
	}
	if err := validateMap(command.GetLabels(), 256); err != nil {
		return err
	}
	return validateMap(command.GetAnnotations(), 4096)
}

func validateCreateStudy(identity Identity, command *experimentv1.CreateStudyCommand) error {
	if command == nil || command.GetContext() == nil || !validID(command.GetStudyId()) || command.GetType() == experimentv1.StudyType_STUDY_TYPE_UNSPECIFIED {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, command.GetExperiment(), "experiment", true); err != nil || !validExperimentParent(identity, command.GetExperiment().GetName()) {
		return ErrInvalidArgument
	}
	for label, artifact := range map[string]*artifactv1.ArtifactRef{"study manifest": command.GetStudyManifest(), "base configuration": command.GetBaseConfiguration(), "search space": command.GetSearchSpace(), "objective specification": command.GetObjectiveSpecification()} {
		if err := validateArtifact(artifact, label, true); err != nil {
			return err
		}
	}
	budget := command.GetBudget()
	if budget == nil || budget.GetMaximumTrials() == 0 || budget.GetMaximumTrials() > 100000 || budget.GetMaximumParallelTrials() == 0 || budget.GetMaximumParallelTrials() > budget.GetMaximumTrials() || budget.GetMaximumDuration() == nil || budget.GetMaximumDuration().CheckValid() != nil || budget.GetMaximumDuration().AsDuration() <= 0 || budget.GetMaximumDuration().AsDuration() > 365*24*time.Hour {
		return ErrInvalidArgument
	}
	return nil
}

func validateCreateTrial(identity Identity, command *experimentv1.CreateTrialCommand) error {
	if command == nil || command.GetContext() == nil || !validID(command.GetTrialId()) || command.GetTrialNumber() == 0 {
		return ErrInvalidArgument
	}
	if err := validateReference(identity, command.GetStudy(), "study", true); err != nil || !validStudyParent(identity, command.GetStudy().GetName()) {
		return ErrInvalidArgument
	}
	if err := validateArtifact(command.GetResolvedConfiguration(), "resolved configuration", true); err != nil {
		return err
	}
	if execution := command.GetExecution(); execution != nil {
		if execution.GetResourceType() == "" || !validID(execution.GetResourceId()) || execution.GetName() == "" || execution.GetResourceVersion() < 0 {
			return ErrInvalidArgument
		}
		if execution.GetTenantId() != "" && execution.GetTenantId() != identity.TenantID {
			return ErrPermissionDenied
		}
	}
	return nil
}

func validateCompleteTrial(command *experimentv1.CompleteTrialCommand) error {
	if command == nil || command.GetContext() == nil || command.GetEtag() == "" || command.GetOutcome() == experimentv1.TrialOutcome_TRIAL_OUTCOME_UNSPECIFIED || command.GetOutcome() == experimentv1.TrialOutcome_TRIAL_OUTCOME_CANCELLED || len(command.GetEvidence()) > 256 {
		return ErrInvalidArgument
	}
	switch command.GetOutcome() {
	case experimentv1.TrialOutcome_TRIAL_OUTCOME_SUCCEEDED, experimentv1.TrialOutcome_TRIAL_OUTCOME_INFEASIBLE, experimentv1.TrialOutcome_TRIAL_OUTCOME_PRUNED:
		if err := validateArtifact(command.GetResultManifest(), "result manifest", true); err != nil {
			return err
		}
		if command.GetError() != nil {
			return ErrInvalidArgument
		}
	case experimentv1.TrialOutcome_TRIAL_OUTCOME_FAILED:
		if err := validateError(command.GetError()); err != nil {
			return err
		}
		if command.GetResultManifest() != nil {
			return ErrInvalidArgument
		}
	default:
		return ErrInvalidArgument
	}
	for _, evidence := range command.GetEvidence() {
		if err := validateEvidence(evidence); err != nil {
			return err
		}
	}
	return nil
}

func experimentTransitionAllowed(from, to experimentv1.ExperimentState) bool {
	switch from {
	case experimentv1.ExperimentState_EXPERIMENT_STATE_DRAFT:
		return to == experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE || to == experimentv1.ExperimentState_EXPERIMENT_STATE_CANCELLED
	case experimentv1.ExperimentState_EXPERIMENT_STATE_ACTIVE:
		return to == experimentv1.ExperimentState_EXPERIMENT_STATE_COMPLETED || to == experimentv1.ExperimentState_EXPERIMENT_STATE_CANCELLED
	case experimentv1.ExperimentState_EXPERIMENT_STATE_COMPLETED, experimentv1.ExperimentState_EXPERIMENT_STATE_CANCELLED:
		return to == experimentv1.ExperimentState_EXPERIMENT_STATE_ARCHIVED
	default:
		return false
	}
}

func studyTransitionAllowed(from, to experimentv1.StudyState) bool {
	switch from {
	case experimentv1.StudyState_STUDY_STATE_CREATED:
		return to == experimentv1.StudyState_STUDY_STATE_RUNNING || to == experimentv1.StudyState_STUDY_STATE_CANCELLED
	case experimentv1.StudyState_STUDY_STATE_RUNNING:
		return to == experimentv1.StudyState_STUDY_STATE_PAUSED || to == experimentv1.StudyState_STUDY_STATE_COMPLETED || to == experimentv1.StudyState_STUDY_STATE_CANCELLED || to == experimentv1.StudyState_STUDY_STATE_FAILED
	case experimentv1.StudyState_STUDY_STATE_PAUSED:
		return to == experimentv1.StudyState_STUDY_STATE_RUNNING || to == experimentv1.StudyState_STUDY_STATE_CANCELLED || to == experimentv1.StudyState_STUDY_STATE_FAILED
	default:
		return false
	}
}

func trialTransitionAllowed(from, to experimentv1.TrialState) bool {
	switch from {
	case experimentv1.TrialState_TRIAL_STATE_CREATED:
		return to == experimentv1.TrialState_TRIAL_STATE_ADMITTED || to == experimentv1.TrialState_TRIAL_STATE_CANCELLED || to == experimentv1.TrialState_TRIAL_STATE_INVALID
	case experimentv1.TrialState_TRIAL_STATE_ADMITTED:
		return to == experimentv1.TrialState_TRIAL_STATE_RUNNING || to == experimentv1.TrialState_TRIAL_STATE_CANCELLED || to == experimentv1.TrialState_TRIAL_STATE_INVALID
	case experimentv1.TrialState_TRIAL_STATE_RUNNING:
		return to == experimentv1.TrialState_TRIAL_STATE_CANCELLED || to == experimentv1.TrialState_TRIAL_STATE_INVALID
	default:
		return false
	}
}

func normalizeOrder(value string) (string, error) {
	value = strings.ToLower(strings.Join(strings.Fields(value), " "))
	if value == "" {
		return "create_time desc,name desc", nil
	}
	if value != "create_time desc,name desc" && value != "create_time asc,name asc" {
		return "", ErrInvalidArgument
	}
	return value, nil
}

func filterState(filter string, values map[string]int32, prefix string) (int32, error) {
	if filter == "" {
		return 0, nil
	}
	parts := strings.Split(filter, "=")
	if len(parts) != 2 || strings.TrimSpace(parts[0]) != "state" {
		return 0, ErrInvalidArgument
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

func sortedMapKeys(values map[string]string) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
