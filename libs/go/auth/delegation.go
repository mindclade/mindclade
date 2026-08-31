package auth

import (
	"errors"
	"time"
)

type Delegation struct {
	TenantID, Subject, Action, ResourcePrefix string
	LeaseEpoch                                uint64
	ExpiresAt                                 time.Time
}

func (d Delegation) ValidAt(now time.Time) error {
	if d.TenantID == "" || d.Subject == "" || d.Action == "" || d.ResourcePrefix == "" || d.LeaseEpoch == 0 || !now.Before(d.ExpiresAt) {
		return errors.New("invalid delegation")
	}
	return nil
}
