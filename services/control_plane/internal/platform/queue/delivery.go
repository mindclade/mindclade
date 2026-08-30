package queue

import "context"

type Handler interface {
	Handle(context.Context, Envelope) error
}

type Delivery struct {
	Envelope Envelope
	Attempts uint32
}

func (d Delivery) Retryable(maxAttempts uint32) bool {
	return d.Attempts < maxAttempts
}
