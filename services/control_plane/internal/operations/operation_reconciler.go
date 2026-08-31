package operations

import (
	"context"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

type DesiredStatePublisher interface {
	Publish(context.Context, *commonv1.EventEnvelope) error
}

type Reconciler struct{ Publisher DesiredStatePublisher }

// Publish is invoked after a durable outbox read, never inside operation acceptance.
func (r Reconciler) Publish(ctx context.Context, envelope *commonv1.EventEnvelope) error {
	return r.Publisher.Publish(ctx, envelope)
}
