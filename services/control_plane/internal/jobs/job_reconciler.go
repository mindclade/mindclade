package jobs

import (
	"context"

	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

type LeaseObserver interface {
	Observe(context.Context, *jobv1.Attempt) (string, error)
}

type Reconciler struct{ Observer LeaseObserver }

// Reconcile observes external workload state; it does not provide a DB capability to workers.
func (r Reconciler) Reconcile(ctx context.Context, attempt *jobv1.Attempt) (string, error) {
	return r.Observer.Observe(ctx, attempt)
}
