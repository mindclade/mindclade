package policies

import "time"

type Decision struct {
	TenantID string
	ActorID  string
	Action   string
	Allowed  bool
	At       time.Time
}

type DecisionRecorder interface {
	RecordDecision(Decision)
}
