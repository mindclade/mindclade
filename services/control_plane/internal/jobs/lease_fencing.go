package jobs

import jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"

func ValidLease(attempt *jobv1.Attempt, attemptID string, epoch uint64) bool {
	return attempt != nil && attempt.GetAttemptId() == attemptID && attempt.GetLeaseEpoch() == epoch && attempt.GetState() != jobv1.AttemptState_ATTEMPT_STATE_FENCED
}
