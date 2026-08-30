package artifacts

import "context"

type Verifier interface {
	Verify(context.Context, Artifact) error
}

type Reconciler struct{ Verifier Verifier }

// Reconcile verifies an immutable record through a port; it never mutates object bytes.
func (r Reconciler) Reconcile(ctx context.Context, artifact Artifact) error {
	return r.Verifier.Verify(ctx, artifact)
}
