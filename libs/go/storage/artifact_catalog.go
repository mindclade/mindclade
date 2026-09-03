package storage

import "context"

type ArtifactRecord struct {
	TenantID  string
	Digest    string
	MediaType string
	Size      int64
}

// Catalog stores tenant-scoped metadata only; object paths are never durable identity.
type Catalog interface {
	Register(context.Context, ArtifactRecord) error
	Get(context.Context, string, string) (ArtifactRecord, error)
}
