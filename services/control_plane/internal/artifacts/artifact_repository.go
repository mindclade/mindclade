package artifacts

import (
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"sync"

	"google.golang.org/protobuf/proto"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/tenants"
)

var ErrNotFound = errors.New("artifact not found")

type artifactState uint8

const (
	artifactStateUnspecified artifactState = iota
	artifactStateReserved
	artifactStateCataloged
)

// artifactRow is private persistence state. ArtifactRef remains the generated
// boundary type; fence and catalog state are relational adapter metadata.
type artifactRow struct {
	tenantID string
	ref      *artifactv1.ArtifactRef
	fence    uint64
	state    artifactState
}

type Repository struct {
	mu        sync.Mutex
	artifacts map[string]artifactRow
	fences    map[string]uint64
}

func NewRepository() *Repository {
	return &Repository{artifacts: make(map[string]artifactRow), fences: make(map[string]uint64)}
}

func (r *Repository) Reserve(tenantID string, artifact *artifactv1.ArtifactRef) (*artifactv1.ArtifactRef, uint64, error) {
	if err := validateArtifactRef(tenantID, artifact); err != nil {
		return nil, 0, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	key := tenantID + "\x00" + artifact.GetDigest()
	r.fences[key]++
	fence := r.fences[key]
	ref := cloneArtifactRef(artifact)
	r.artifacts[key] = artifactRow{tenantID: tenantID, ref: ref, fence: fence, state: artifactStateReserved}
	return cloneArtifactRef(ref), fence, nil
}

func (r *Repository) Put(tenantID string, artifact *artifactv1.ArtifactRef, fence uint64) error {
	if err := validateArtifactRef(tenantID, artifact); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	key := tenantID + "\x00" + artifact.GetDigest()
	if current, ok := r.artifacts[key]; ok && current.fence > fence {
		return ErrNotFound
	}
	r.artifacts[key] = artifactRow{
		tenantID: tenantID,
		ref:      cloneArtifactRef(artifact),
		fence:    fence,
		state:    artifactStateCataloged,
	}
	return nil
}

func (r *Repository) Get(tenantID, digest string) (*artifactv1.ArtifactRef, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	row, ok := r.artifacts[tenantID+"\x00"+digest]
	if !ok || row.state != artifactStateCataloged {
		return nil, ErrNotFound
	}
	if err := tenants.RequireScope(tenantID, row.tenantID); err != nil {
		return nil, err
	}
	return cloneArtifactRef(row.ref), nil
}

func cloneArtifactRef(ref *artifactv1.ArtifactRef) *artifactv1.ArtifactRef {
	if ref == nil {
		return nil
	}
	return proto.Clone(ref).(*artifactv1.ArtifactRef)
}

func validateArtifactRef(tenantID string, ref *artifactv1.ArtifactRef) error {
	if tenantID == "" || ref == nil {
		return ErrNotFound
	}
	if !strings.HasPrefix(ref.GetDigest(), "sha256:") || len(ref.GetDigest()) != len("sha256:")+64 {
		return errors.New("artifact digest must be sha256:<64 lowercase hex>")
	}
	digestHex := strings.TrimPrefix(ref.GetDigest(), "sha256:")
	if digestHex != strings.ToLower(digestHex) {
		return errors.New("artifact digest must use lowercase hex")
	}
	if _, err := hex.DecodeString(digestHex); err != nil {
		return fmt.Errorf("invalid artifact digest: %w", err)
	}
	if ref.GetMediaType() == "" || ref.GetSizeBytes() < 0 {
		return errors.New("artifact media type and non-negative size are required")
	}
	return nil
}
