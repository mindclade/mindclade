package identifiers

import (
	"fmt"
	"strings"
)

// ParseResourceID validates an opaque generated-contract resource_id without
// introducing a second Go wire type. The returned string is assigned directly
// to commonv1.ResourceRef.ResourceId.
func ParseResourceID(kind, value string) (string, error) {
	if kind == "" || len(value) < 10 || !strings.HasPrefix(value, kind+"_") {
		return "", fmt.Errorf("invalid %q resource id", kind)
	}
	return value, nil
}
