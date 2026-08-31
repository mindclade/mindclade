package jobs

import (
	"time"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

func ValidLease(attempt *jobv1.Attempt, fence *jobv1.LeaseFence, workerID, token string, at time.Time) bool {
	if attempt == nil || fence == nil || workerID == "" || at.IsZero() {
		return false
	}
	presentedDigest, err := LeaseTokenDigest(token)
	if err != nil || !equalLeaseTokenDigest(fence.GetLeaseTokenDigest(), presentedDigest) {
		return false
	}
	if attempt.GetAttemptId() != fence.GetAttemptId() || attempt.GetRunId() != fence.GetRunId() ||
		attempt.GetJobId() != fence.GetJobId() || attempt.GetTenantId() != fence.GetTenantId() ||
		attempt.GetProjectId() != fence.GetProjectId() || attempt.GetLeaseEpoch() != fence.GetLeaseEpoch() ||
		attempt.GetWorkerId() != workerID {
		return false
	}
	if attempt.GetState() != jobv1.AttemptState_ATTEMPT_STATE_LEASED && attempt.GetState() != jobv1.AttemptState_ATTEMPT_STATE_RUNNING {
		return false
	}
	if attempt.GetLeaseExpiresAt() == nil || fence.GetDeadline() == nil ||
		attempt.GetLeaseExpiresAt().CheckValid() != nil || fence.GetDeadline().CheckValid() != nil {
		return false
	}
	now := at.UTC()
	return now.Before(attempt.GetLeaseExpiresAt().AsTime()) && now.Before(fence.GetDeadline().AsTime()) &&
		attempt.GetLeaseExpiresAt().AsTime().Equal(fence.GetDeadline().AsTime())
}
