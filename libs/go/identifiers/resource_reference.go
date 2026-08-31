package identifiers

import (
	"fmt"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

// ResourceRef is an alias, not an independently owned model. Protobuf remains
// the sole editable authority for the resource-reference wire contract.
type ResourceRef = commonv1.ResourceRef

// NewResourceRef constructs and validates the generated contract type.
func NewResourceRef(tenantID, projectID, resourceType, resourceID string, version int64) (*commonv1.ResourceRef, error) {
	ref := &commonv1.ResourceRef{
		ResourceType:    resourceType,
		ResourceId:      resourceID,
		TenantId:        tenantID,
		ProjectId:       projectID,
		ResourceVersion: version,
	}
	if err := ValidateResourceRef(ref); err != nil {
		return nil, err
	}
	return ref, nil
}

// ValidateResourceRef applies domain validation to the generated message.
func ValidateResourceRef(ref *commonv1.ResourceRef) error {
	if ref == nil {
		return fmt.Errorf("resource reference is required")
	}
	if ref.GetTenantId() == "" || ref.GetProjectId() == "" || ref.GetResourceType() == "" || ref.GetResourceVersion() <= 0 {
		return fmt.Errorf("resource reference requires tenant, project, type, id, and positive version")
	}
	if _, err := ParseResourceID(ref.GetResourceType(), ref.GetResourceId()); err != nil {
		return err
	}
	return nil
}
