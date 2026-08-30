package jobs

func ValidLease(attempt Attempt, attemptID string, epoch uint64) bool {
	return attempt.ID == attemptID && attempt.LeaseEpoch == epoch && attempt.State != "FENCED"
}
