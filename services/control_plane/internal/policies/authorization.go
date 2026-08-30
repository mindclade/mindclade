package policies

import (
	"errors"

	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

var ErrDenied = errors.New("authorization denied")

type Principal struct {
	ID       string
	TenantID string
	Actions  map[string]bool
}

type Authorizer interface {
	Authorize(Principal, string, string) error
}

// DenyByDefault grants only actions explicitly present on the principal and only in its tenant.
type DenyByDefault struct{}

func (DenyByDefault) Authorize(principal Principal, action, tenantID string) error {
	if err := tenants.RequireScope(principal.TenantID, tenantID); err != nil {
		return ErrDenied
	}
	if principal.ID == "" || !principal.Actions[action] {
		return ErrDenied
	}
	return nil
}
