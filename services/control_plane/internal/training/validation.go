package training

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/known/timestamppb"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	trainingv1 "github.com/mindclade/mindclade/protocols/generated/go/training/v1"
)

const maxPostgresBigint = uint64(1<<63 - 1)

func validateIdentity(identity Identity) error {
	for label, value := range map[string]string{
		"tenant": identity.TenantID, "project": identity.ProjectID, "principal": identity.Principal,
	} {
		if value == "" || strings.TrimSpace(value) != value || len(value) > 255 || strings.ContainsAny(value, "\x00\r\n") {
			return fmt.Errorf("%w: invalid %s identity", ErrUnauthenticated, label)
		}
	}
	return nil
}

func validateContext(identity Identity, command proto.Message, commandContext *commonv1.CommandContext, now time.Time) (string, error) {
	if command == nil || commandContext == nil || now.IsZero() {
		return "", fmt.Errorf("%w: command and context are required", ErrInvalidArgument)
	}
	if err := validateIdentity(identity); err != nil {
		return "", err
	}
	if commandContext.GetRequestId() == "" || commandContext.GetIdempotencyKey() == "" {
		return "", fmt.Errorf("%w: request_id and idempotency_key are required", ErrInvalidArgument)
	}
	for label, value := range map[string]string{
		"request_id": commandContext.GetRequestId(), "idempotency_key": commandContext.GetIdempotencyKey(),
	} {
		if len(value) > 255 || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\x00\r\n") {
			return "", fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
		}
	}
	for label, value := range map[string]string{
		"trace_id": commandContext.GetTraceId(), "correlation_id": commandContext.GetCorrelationId(), "causation_id": commandContext.GetCausationId(),
	} {
		if len(value) > 255 || strings.ContainsAny(value, "\x00\r\n") {
			return "", fmt.Errorf("%w: invalid %s", ErrInvalidArgument, label)
		}
	}
	if commandContext.GetTenantId() != "" && commandContext.GetTenantId() != identity.TenantID {
		return "", ErrPermissionDenied
	}
	if commandContext.GetProjectId() != "" && commandContext.GetProjectId() != identity.ProjectID {
		return "", ErrPermissionDenied
	}
	if commandContext.GetPrincipalId() != "" && commandContext.GetPrincipalId() != identity.Principal {
		return "", ErrPermissionDenied
	}
	if deadline := commandContext.GetDeadline(); deadline != nil {
		if err := deadline.CheckValid(); err != nil {
			return "", fmt.Errorf("%w: invalid command deadline: %w", ErrInvalidArgument, err)
		}
		if !now.Before(deadline.AsTime()) {
			return "", ErrDeadlineExceeded
		}
	}
	digest, err := canonicalCommandDigest(command)
	if err != nil {
		return "", err
	}
	// The server-computed digest is authoritative. A caller may provide the
	// same value as an early corruption check, but internal SDKs are not
	// required to reproduce language-specific protobuf serialization. The
	// transport server materializes this field before persistence and events.
	if supplied := commandContext.GetCanonicalRequestDigest(); supplied != "" &&
		subtle.ConstantTimeCompare([]byte(digest), []byte(supplied)) != 1 {
		return "", fmt.Errorf("%w: canonical request digest mismatch", ErrInvalidArgument)
	}
	return digest, nil
}

// validateRepositoryCommand repeats authentication-bound canonicalization at
// the durable boundary. This prevents an in-process caller from bypassing the
// transport server's identity, deadline, or command-digest checks.
func validateRepositoryCommand(identity Identity, command proto.Message, commandContext *commonv1.CommandContext, digest string, now time.Time) error {
	canonical, err := validateContext(identity, command, commandContext, now)
	if err != nil {
		return err
	}
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(digest)) != 1 {
		return fmt.Errorf("%w: repository command digest mismatch", ErrInvalidArgument)
	}
	return nil
}

func validateCommandDeadline(deadline *timestamppb.Timestamp, now time.Time) error {
	if deadline == nil {
		return fmt.Errorf("%w: explicit worker command deadline is required", ErrInvalidArgument)
	}
	if err := deadline.CheckValid(); err != nil {
		return fmt.Errorf("%w: invalid worker command deadline", ErrInvalidArgument)
	}
	if !now.Before(deadline.AsTime()) {
		return ErrDeadlineExceeded
	}
	return nil
}

func validateScopedReference(identity Identity, value *commonv1.ResourceRef, label string) error {
	if value == nil || value.GetResourceType() == "" || value.GetResourceId() == "" || value.GetName() == "" || value.GetResourceVersion() < 0 ||
		len(value.GetResourceType()) > 128 || len(value.GetResourceId()) > 512 || len(value.GetName()) > 2048 || len(value.GetEtag()) > 512 ||
		strings.ContainsRune(value.GetResourceType(), '\x00') || strings.ContainsRune(value.GetResourceId(), '\x00') || strings.ContainsRune(value.GetName(), '\x00') || strings.ContainsRune(value.GetEtag(), '\x00') {
		return fmt.Errorf("%w: %s reference is required", ErrInvalidArgument, label)
	}
	if value.GetTenantId() != "" && value.GetTenantId() != identity.TenantID {
		return ErrPermissionDenied
	}
	if value.GetProjectId() != "" && value.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	return nil
}

func validateArtifactReference(value *artifactv1.ArtifactRef, label string, required bool) error {
	if value == nil {
		if required {
			return fmt.Errorf("%w: %s artifact is required", ErrInvalidArgument, label)
		}
		return nil
	}
	if !validSHA256Digest(value.GetDigest()) || value.GetMediaType() == "" || value.GetSizeBytes() < 0 ||
		(value.GetIntegrityDigest() != "" && !validSHA256Digest(value.GetIntegrityDigest())) ||
		len(value.GetMediaType()) > 255 || len(value.GetArtifactKind()) > 255 || len(value.GetSchemaId()) > 1024 || len(value.GetUri()) > 8192 || len(value.GetSchemaVersion()) > 255 ||
		strings.ContainsRune(value.GetMediaType(), '\x00') || strings.ContainsRune(value.GetArtifactKind(), '\x00') || strings.ContainsRune(value.GetSchemaId(), '\x00') || strings.ContainsRune(value.GetUri(), '\x00') || strings.ContainsRune(value.GetSchemaVersion(), '\x00') {
		return fmt.Errorf("%w: invalid %s artifact", ErrInvalidArgument, label)
	}
	return nil
}

func validateProgressArtifacts(value *trainingv1.TrainingProgress) error {
	if value == nil {
		return nil
	}
	if err := validateArtifactReference(value.GetProgressLedger(), "progress ledger", false); err != nil {
		return err
	}
	if err := validateArtifactReference(value.GetMetricSnapshot(), "metric snapshot", false); err != nil {
		return err
	}
	if value.GetLatestDataRange() != nil {
		if err := validateArtifactReference(value.GetLatestDataRange().GetBatchReceipt(), "batch receipt", true); err != nil {
			return err
		}
	}
	return nil
}

func validSHA256Digest(value string) bool {
	if len(value) != len("sha256:")+64 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}

func validateVerificationEvidence(evidence *artifactv1.EvidenceRef, subjectDigest string) error {
	if evidence == nil || evidence.GetEvidenceKind() == "" || !validSHA256Digest(evidence.GetDigest()) || !validSHA256Digest(evidence.GetSubjectDigest()) {
		return fmt.Errorf("%w: verification evidence is incomplete", ErrInvalidArgument)
	}
	if evidence.GetPolicyDigest() != "" && !validSHA256Digest(evidence.GetPolicyDigest()) {
		return fmt.Errorf("%w: verification policy digest is invalid", ErrInvalidArgument)
	}
	if subtle.ConstantTimeCompare([]byte(evidence.GetSubjectDigest()), []byte(subjectDigest)) != 1 {
		return fmt.Errorf("%w: verification evidence does not bind the checkpoint manifest", ErrInvalidArgument)
	}
	return nil
}

func canonicalCommandDigest(command proto.Message) (string, error) {
	if command == nil {
		return "", fmt.Errorf("%w: command is required", ErrInvalidArgument)
	}
	cloned := proto.Clone(command)
	message := cloned.ProtoReflect()
	contextField := message.Descriptor().Fields().ByName(protoreflect.Name("context"))
	if contextField == nil || contextField.Kind() != protoreflect.MessageKind {
		return "", fmt.Errorf("%w: durable command lacks context", ErrInvalidArgument)
	}
	message.Clear(contextField)
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(cloned)
	if err != nil {
		return "", fmt.Errorf("marshal canonical command: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

func validateFence(identity Identity, fence *jobv1.LeaseFence, now time.Time) error {
	if fence == nil || identity.WorkerID == "" || identity.LeaseToken == "" || fence.GetJobId() == "" || fence.GetRunId() == "" || fence.GetAttemptId() == "" || fence.GetLeaseEpoch() == 0 || fence.GetLeaseEpoch() > maxPostgresBigint {
		return ErrStaleFence
	}
	if len(identity.WorkerID) > 255 || strings.TrimSpace(identity.WorkerID) != identity.WorkerID || strings.ContainsAny(identity.WorkerID, "\x00\r\n") || len(identity.LeaseToken) > 4096 || strings.ContainsRune(identity.LeaseToken, '\x00') {
		return ErrUnauthenticated
	}
	if fence.GetTenantId() != identity.TenantID || fence.GetProjectId() != identity.ProjectID {
		return ErrPermissionDenied
	}
	if fence.GetDeadline() == nil {
		return ErrStaleFence
	}
	if err := fence.GetDeadline().CheckValid(); err != nil {
		return ErrStaleFence
	}
	if !now.Before(fence.GetDeadline().AsTime()) {
		return ErrLeaseExpired
	}
	presented := sha256.Sum256([]byte(identity.LeaseToken))
	presentedDigest := "sha256:" + hex.EncodeToString(presented[:])
	if subtle.ConstantTimeCompare([]byte(presentedDigest), []byte(fence.GetLeaseTokenDigest())) != 1 {
		return ErrLeaseToken
	}
	return nil
}

func monotonicProgress(previous, next *trainingv1.TrainingProgress) error {
	if next == nil || next.GetTrainingRunName() == "" || next.GetProgressRevision() == 0 || next.GetCommittedAt() == nil {
		return fmt.Errorf("%w: incomplete progress", ErrInvalidArgument)
	}
	if err := next.GetCommittedAt().CheckValid(); err != nil {
		return fmt.Errorf("%w: invalid committed_at", ErrInvalidArgument)
	}
	if err := validateProgressStorage(next); err != nil {
		return err
	}
	if update := next.GetLatestCommittedUpdate(); update != nil && (update.GetValue() == "" || update.GetSequence() == 0) {
		return fmt.Errorf("%w: incomplete latest committed update", ErrInvalidArgument)
	}
	if data := next.GetLatestDataRange(); data != nil {
		if data.GetDatasetRelease() == nil || data.GetSplitName() == "" || data.GetPartitionId() == "" || data.GetEndOrdinalExclusive() <= data.GetStartOrdinal() || data.GetBatchReceipt() == nil {
			return fmt.Errorf("%w: incomplete committed data range", ErrInvalidArgument)
		}
	}
	if previous == nil {
		return nil
	}
	if previous.GetCommittedAt() == nil {
		return ErrNonMonotonicProgress
	}
	if next.GetTrainingRunName() != previous.GetTrainingRunName() ||
		next.GetProgressRevision() <= previous.GetProgressRevision() ||
		next.GetCommittedUpdateCount() < previous.GetCommittedUpdateCount() ||
		next.GetCommittedSampleCount() < previous.GetCommittedSampleCount() ||
		next.GetCommittedTokenCount() < previous.GetCommittedTokenCount() ||
		next.GetEffectiveWorkUnits() < previous.GetEffectiveWorkUnits() ||
		next.GetCommittedAt().AsTime().Before(previous.GetCommittedAt().AsTime()) {
		return ErrNonMonotonicProgress
	}
	if previous.GetEffectiveWorkUnitName() != "" && next.GetEffectiveWorkUnitName() != previous.GetEffectiveWorkUnitName() {
		return ErrNonMonotonicProgress
	}
	if previousUpdate := previous.GetLatestCommittedUpdate(); previousUpdate != nil {
		nextUpdate := next.GetLatestCommittedUpdate()
		if nextUpdate == nil || nextUpdate.GetSequence() <= previousUpdate.GetSequence() {
			return ErrNonMonotonicProgress
		}
	}
	if previousRange := previous.GetLatestDataRange(); previousRange != nil {
		nextRange := next.GetLatestDataRange()
		if nextRange == nil {
			return ErrNonMonotonicProgress
		}
		if proto.Equal(previousRange.GetDatasetRelease(), nextRange.GetDatasetRelease()) &&
			previousRange.GetSplitName() == nextRange.GetSplitName() && previousRange.GetPartitionId() == nextRange.GetPartitionId() &&
			(nextRange.GetStartOrdinal() < previousRange.GetStartOrdinal() || nextRange.GetEndOrdinalExclusive() < previousRange.GetEndOrdinalExclusive()) {
			return ErrNonMonotonicProgress
		}
	}
	return nil
}

func validateProgressStorage(value *trainingv1.TrainingProgress) error {
	if value == nil {
		return nil
	}
	values := []uint64{
		value.GetProgressRevision(), value.GetCommittedUpdateCount(), value.GetCommittedSampleCount(),
		value.GetCommittedTokenCount(), value.GetEffectiveWorkUnits(),
	}
	if value.GetLatestCommittedUpdate() != nil {
		values = append(values, value.GetLatestCommittedUpdate().GetSequence())
	}
	if value.GetLatestDataRange() != nil {
		values = append(values, value.GetLatestDataRange().GetStartOrdinal(), value.GetLatestDataRange().GetEndOrdinalExclusive())
	}
	for _, number := range values {
		if number > maxPostgresBigint {
			return fmt.Errorf("%w: progress counter exceeds durable bigint range", ErrInvalidArgument)
		}
	}
	return nil
}

func validResourceID(value string) bool {
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

func validReason(value string) bool {
	return value != "" && len(value) <= 1024 && strings.TrimSpace(value) != "" && !strings.ContainsRune(value, '\x00')
}

func validateTerminalCommand(command *trainingv1.CompleteTrainingRunCommand) error {
	if command == nil {
		return ErrInvalidArgument
	}
	switch command.GetClassification() {
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_SUCCEEDED:
		if command.GetResultManifest() == nil || command.GetFinalCheckpoint() == nil || command.GetError() != nil {
			return fmt.Errorf("%w: successful completion requires result manifest and final checkpoint without an error", ErrInvalidArgument)
		}
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_CANCELLED:
		if command.GetResultManifest() != nil {
			return fmt.Errorf("%w: cancelled completion cannot publish a result manifest", ErrInvalidArgument)
		}
	case trainingv1.TrainingTerminalClassification_TRAINING_TERMINAL_CLASSIFICATION_UNSPECIFIED:
		return ErrInvalidArgument
	default:
		if command.GetError() == nil {
			return fmt.Errorf("%w: failed completion requires a typed error", ErrInvalidArgument)
		}
	}
	return nil
}

func validateDurableError(identity Identity, detail *commonv1.ErrorDetail) error {
	if detail == nil {
		return nil
	}
	if detail.GetCode() == commonv1.ErrorCode_ERROR_CODE_UNSPECIFIED || len(detail.GetMessage()) > 4096 || strings.ContainsRune(detail.GetMessage(), '\x00') || len(detail.GetErrorId()) > 255 {
		return fmt.Errorf("%w: invalid durable error detail", ErrInvalidArgument)
	}
	if detail.GetSubject() != nil {
		if err := validateScopedReference(identity, detail.GetSubject(), "error subject"); err != nil {
			return err
		}
	}
	if len(detail.GetFieldViolations()) > 100 || len(detail.GetPreconditionViolations()) > 100 {
		return fmt.Errorf("%w: too many durable error violations", ErrInvalidArgument)
	}
	for _, violation := range detail.GetFieldViolations() {
		if violation == nil || violation.GetField() == "" || len(violation.GetField()) > 512 || len(violation.GetDescription()) > 2048 || strings.ContainsRune(violation.GetDescription(), '\x00') {
			return fmt.Errorf("%w: invalid field violation", ErrInvalidArgument)
		}
	}
	for _, violation := range detail.GetPreconditionViolations() {
		if violation == nil || violation.GetType() == "" || len(violation.GetType()) > 255 || len(violation.GetSubject()) > 1024 || len(violation.GetDescription()) > 2048 || strings.ContainsRune(violation.GetDescription(), '\x00') {
			return fmt.Errorf("%w: invalid precondition violation", ErrInvalidArgument)
		}
	}
	return nil
}

func resourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func canonicalTrainingRunName(identity Identity, value string) (string, error) {
	prefix := "tenants/" + identity.TenantID + "/projects/" + identity.ProjectID + "/trainingRuns/"
	switch {
	case strings.HasPrefix(value, prefix):
		value = strings.TrimPrefix(value, prefix)
	case strings.HasPrefix(value, "tenants/"):
		// A fully scoped name outside the authenticated boundary is intentionally
		// indistinguishable from an absent resource.
		return "", ErrNotFound
	case strings.HasPrefix(value, "trainingRuns/"):
		value = strings.TrimPrefix(value, "trainingRuns/")
	}
	if !validResourceID(value) {
		return "", fmt.Errorf("%w: invalid training run name", ErrInvalidArgument)
	}
	return prefix + value, nil
}

func terminalRun(state trainingv1.TrainingRunState) bool {
	return state == trainingv1.TrainingRunState_TRAINING_RUN_STATE_COMPLETED ||
		state == trainingv1.TrainingRunState_TRAINING_RUN_STATE_FAILED ||
		state == trainingv1.TrainingRunState_TRAINING_RUN_STATE_CANCELLED
}
