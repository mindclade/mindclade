package idempotency

import (
	"crypto/sha256"
	"encoding/hex"
)

type CommandKey struct {
	TenantID string
	Value    string
}

func CanonicalHash(canonicalRequest []byte) string {
	digest := sha256.Sum256(canonicalRequest)
	return "sha256:" + hex.EncodeToString(digest[:])
}
