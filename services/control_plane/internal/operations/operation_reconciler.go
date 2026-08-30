package operations

import "context"

type DesiredStatePublisher interface {
	Publish(context.Context, OutboxMessage) error
}

type Reconciler struct{ Publisher DesiredStatePublisher }

// Publish is invoked after a durable outbox read, never inside operation acceptance.
func (r Reconciler) Publish(ctx context.Context, message OutboxMessage) error {
	return r.Publisher.Publish(ctx, message)
}
