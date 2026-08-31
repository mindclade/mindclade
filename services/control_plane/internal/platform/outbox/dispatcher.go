package outbox

import (
	"context"
	"time"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

// Publisher is called after Claim, never from a command transaction.
type Publisher interface {
	Publish(context.Context, *commonv1.EventEnvelope) error
}

type Dispatcher struct {
	Store     *Store
	Publisher Publisher
	Now       func() time.Time
}

func (d Dispatcher) Deliver(ctx context.Context, id string) error {
	record, ok := d.Store.Claim(id)
	if !ok {
		return nil
	}
	if err := d.Publisher.Publish(ctx, record.Envelope); err != nil {
		return err
	}
	now := d.Now
	if now == nil {
		now = time.Now
	}
	d.Store.MarkDelivered(id, record.DeliveryEpoch, now().UTC())
	return nil
}
