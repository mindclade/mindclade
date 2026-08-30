package artifacts

import (
	"errors"
	"sync"

	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

var ErrNotFound = errors.New("artifact not found")

type Artifact struct {
	TenantID  string
	Digest    string
	MediaType string
	Size      int64
	Fence     uint64
	State     string
}

type Repository struct {
	mu        sync.Mutex
	artifacts map[string]Artifact
	fences    map[string]uint64
}

func NewRepository() *Repository {
	return &Repository{artifacts: make(map[string]Artifact), fences: make(map[string]uint64)}
}

func (r *Repository) Reserve(artifact Artifact) (Artifact, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := artifact.TenantID + "\x00" + artifact.Digest
	r.fences[key]++
	artifact.Fence, artifact.State = r.fences[key], "RESERVED"
	r.artifacts[key] = artifact
	return artifact, nil
}

func (r *Repository) Put(artifact Artifact) error {
	if artifact.TenantID == "" || artifact.Digest == "" || artifact.Size < 0 {
		return ErrNotFound
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	key := artifact.TenantID + "\x00" + artifact.Digest
	if current, ok := r.artifacts[key]; ok && current.Fence > artifact.Fence {
		return ErrNotFound
	}
	artifact.State = "CATALOGED"
	r.artifacts[key] = artifact
	return nil
}

func (r *Repository) Get(tenantID, digest string) (Artifact, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	artifact, ok := r.artifacts[tenantID+"\x00"+digest]
	if !ok || artifact.State != "CATALOGED" {
		return Artifact{}, ErrNotFound
	}
	if err := tenants.RequireScope(tenantID, artifact.TenantID); err != nil {
		return Artifact{}, err
	}
	return artifact, nil
}
