package outbox

import (
	"context"
	"time"
)

// Publisher is called after Claim, never from a command transaction.
type Publisher interface {
	Publish(context.Context, Message) error
}

type Dispatcher struct {
	Store     *Store
	Publisher Publisher
	Now       func() time.Time
}

func (d Dispatcher) Deliver(ctx context.Context, id string) error {
	message, ok := d.Store.Claim(id)
	if !ok {
		return nil
	}
	if err := d.Publisher.Publish(ctx, message); err != nil {
		return err
	}
	now := d.Now
	if now == nil {
		now = time.Now
	}
	d.Store.MarkDelivered(id, message.DeliveryEpoch, now().UTC())
	return nil
}
