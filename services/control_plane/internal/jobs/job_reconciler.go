package jobs

import "context"

type LeaseObserver interface {
	Observe(context.Context, Attempt) (string, error)
}

type Reconciler struct{ Observer LeaseObserver }

// Reconcile observes external workload state; it does not provide a DB capability to workers.
func (r Reconciler) Reconcile(ctx context.Context, attempt Attempt) (string, error) {
	return r.Observer.Observe(ctx, attempt)
}
