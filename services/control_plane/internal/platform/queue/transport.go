package queue

import "context"

type Envelope struct {
	EventID       string
	TenantID      string
	EventType     string
	PayloadDigest string
	LeaseEpoch    uint64
}

// Transport is an at-least-once envelope transport. It deliberately exposes no database capability.
type Transport interface {
	Publish(context.Context, Envelope) error
}
