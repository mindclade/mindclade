package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"

	"google.golang.org/api/idtoken"
)

func parseHMACKeyRing(raw, activeKeyID string) (map[string][]byte, error) {
	var encoded map[string]string
	if err := json.Unmarshal([]byte(raw), &encoded); err != nil {
		return nil, errors.New("must be a JSON object of key IDs to base64 values")
	}
	if len(encoded) == 0 || len(encoded) > 16 {
		return nil, errors.New("must contain between 1 and 16 keys")
	}
	keys := make(map[string][]byte, len(encoded))
	for keyID, value := range encoded {
		if !validConfiguredIdentity(keyID) {
			zeroKeyRing(keys)
			return nil, errors.New("contains an invalid key ID")
		}
		decoded, decodeErr := base64.RawStdEncoding.DecodeString(value)
		if decodeErr != nil {
			decoded, decodeErr = base64.StdEncoding.DecodeString(value)
		}
		if decodeErr != nil || len(decoded) < 32 {
			zeroKeyRing(keys)
			return nil, fmt.Errorf("key %q must encode at least 32 random bytes", keyID)
		}
		keys[keyID] = decoded
	}
	if _, ok := keys[activeKeyID]; !ok {
		zeroKeyRing(keys)
		return nil, errors.New("does not contain the active key ID")
	}
	return keys, nil
}

func zeroKeyRing(keys map[string][]byte) {
	for _, key := range keys {
		for index := range key {
			key[index] = 0
		}
	}
}

func zeroBytes(value []byte) {
	for index := range value {
		value[index] = 0
	}
}

func parseIdentityList(value string) ([]string, error) {
	seen := make(map[string]struct{})
	result := make([]string, 0)
	for _, item := range strings.Split(value, ",") {
		item = strings.TrimSpace(item)
		if !validConfiguredIdentity(item) {
			return nil, errors.New("list contains an invalid identity")
		}
		if _, duplicate := seen[item]; duplicate {
			continue
		}
		seen[item] = struct{}{}
		result = append(result, item)
	}
	if len(result) == 0 {
		return nil, errors.New("list requires at least one identity")
	}
	return result, nil
}

func validConfiguredIdentity(value string) bool {
	if value == "" || len(value) > 255 || strings.TrimSpace(value) != value {
		return false
	}
	for _, character := range value {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || strings.ContainsRune("-_.:@", character) {
			continue
		}
		return false
	}
	return true
}

// googleIDTokenVerifier validates short-lived workload-identity ID tokens.
// Authorization remains an explicit allowlist and scope mapping owned by the
// deployment; token possession alone never selects a tenant or project.
type googleIDTokenVerifier struct {
	audience string
	subjects map[string]verifiedIdentityClaims
}

func newGoogleIDTokenVerifier(
	audience string,
	subjects map[string]verifiedIdentityClaims,
) (*googleIDTokenVerifier, error) {
	if audience == "" || len(audience) > 1024 || strings.ContainsAny(audience, " \t\r\n\x00") {
		return nil, errors.New("google ID-token audience is required and must be bounded")
	}
	if len(subjects) == 0 || len(subjects) > 10000 {
		return nil, errors.New("google ID-token verifier requires between 1 and 10000 subject mappings")
	}
	verified := make(map[string]verifiedIdentityClaims, len(subjects))
	for subject, scope := range subjects {
		if subject == "" || len(subject) > 512 || strings.ContainsAny(subject, " \t\r\n\x00") {
			return nil, errors.New("google ID-token subject mapping contains an invalid subject")
		}
		if !validConfiguredIdentity(scope.tenantID) || !validConfiguredIdentity(scope.projectID) ||
			!validConfiguredIdentity(scope.principalID) {
			return nil, fmt.Errorf("google ID-token subject %q has an invalid tenant, project, or principal mapping", subject)
		}
		if scope.workerID != "" && !validConfiguredIdentity(scope.workerID) {
			return nil, fmt.Errorf("google ID-token subject %q has an invalid worker mapping", subject)
		}
		if scope.leaseToken != "" {
			return nil, fmt.Errorf("google ID-token subject %q must not contain a lease credential", subject)
		}
		if len(scope.roles) == 0 {
			return nil, fmt.Errorf("google ID-token subject %q requires at least one authorization role", subject)
		}
		roles := make(map[string]struct{}, len(scope.roles))
		for role := range scope.roles {
			if !supportedAuthorizationRole(role) {
				return nil, fmt.Errorf("google ID-token subject %q contains unsupported role %q", subject, role)
			}
			roles[role] = struct{}{}
		}
		scope.roles = roles
		verified[subject] = scope
	}
	return &googleIDTokenVerifier{audience: audience, subjects: verified}, nil
}

func (v *googleIDTokenVerifier) Verify(ctx context.Context, token string) (verifiedIdentityClaims, error) {
	if v == nil {
		return verifiedIdentityClaims{}, errors.New("google ID-token verifier is not configured")
	}
	payload, err := idtoken.Validate(ctx, token, v.audience)
	if err != nil || payload == nil || payload.Subject == "" {
		return verifiedIdentityClaims{}, errors.New("google ID token is invalid")
	}
	claims, allowed := v.subjects[payload.Subject]
	if !allowed {
		return verifiedIdentityClaims{}, errors.New("google ID-token subject is not authorized")
	}
	if claims.workerID == "" {
		// Human/service callers are not silently promoted to workers. Worker
		// identity is an explicit deployment-owned authorization mapping.
		claims.workerID = ""
	}
	claims.roles = cloneRoles(claims.roles)
	return claims, nil
}

type subjectMappingDocument struct {
	TenantID    string   `json:"tenant_id"`
	ProjectID   string   `json:"project_id"`
	PrincipalID string   `json:"principal_id"`
	WorkerID    string   `json:"worker_id,omitempty"`
	Roles       []string `json:"roles"`
}

func parseSubjectMappings(raw string) (map[string]verifiedIdentityClaims, error) {
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.DisallowUnknownFields()
	var document map[string]subjectMappingDocument
	if err := decoder.Decode(&document); err != nil {
		return nil, fmt.Errorf("must be a JSON object of subject identity mappings: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return nil, errors.New("must contain exactly one JSON object")
	}
	if len(document) == 0 || len(document) > 10000 {
		return nil, errors.New("must contain between 1 and 10000 subject mappings")
	}
	result := make(map[string]verifiedIdentityClaims, len(document))
	for subject, mapping := range document {
		roles := make(map[string]struct{}, len(mapping.Roles))
		for _, role := range mapping.Roles {
			if !supportedAuthorizationRole(role) {
				return nil, fmt.Errorf("subject %q contains unsupported role %q", subject, role)
			}
			roles[role] = struct{}{}
		}
		result[subject] = verifiedIdentityClaims{
			tenantID: mapping.TenantID, projectID: mapping.ProjectID,
			principalID: mapping.PrincipalID, workerID: mapping.WorkerID, roles: roles,
		}
	}
	return result, nil
}

func supportedAuthorizationRole(role string) bool {
	switch role {
	case "platform", "worker", "scheduler", "auditor", "admin",
		"platform-admin", "platform-operator", "automation-operator", "automation-viewer", "automation-worker",
		"agent-admin", "agent-user", "agent-worker", "approver":
		return true
	default:
		return false
	}
}

func cloneRoles(source map[string]struct{}) map[string]struct{} {
	result := make(map[string]struct{}, len(source))
	for role := range source {
		result[role] = struct{}{}
	}
	return result
}
