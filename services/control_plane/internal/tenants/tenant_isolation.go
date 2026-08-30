package tenants

import "errors"

var ErrTenantMismatch = errors.New("tenant scope mismatch")

// RequireScope is the mandatory boundary check before reading or mutating a tenant resource.
func RequireScope(principalTenant, resourceTenant string) error {
	if principalTenant == "" || resourceTenant == "" || principalTenant != resourceTenant {
		return ErrTenantMismatch
	}
	return nil
}
