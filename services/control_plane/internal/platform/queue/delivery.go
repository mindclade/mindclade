package queue

import (
	"context"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

type Handler interface {
	Handle(context.Context, *commonv1.EventEnvelope) error
}

type Delivery struct {
	Envelope *commonv1.EventEnvelope
	Attempts uint32
}

func (d Delivery) Retryable(maxAttempts uint32) bool {
	return d.Attempts < maxAttempts
}
