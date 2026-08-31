package artifacts

import (
	"context"

	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
)

type Verifier interface {
	Verify(context.Context, *artifactv1.ArtifactRef) error
}

type Reconciler struct{ Verifier Verifier }

// Reconcile verifies an immutable record through a port; it never mutates object bytes.
func (r Reconciler) Reconcile(ctx context.Context, artifact *artifactv1.ArtifactRef) error {
	return r.Verifier.Verify(ctx, artifact)
}
