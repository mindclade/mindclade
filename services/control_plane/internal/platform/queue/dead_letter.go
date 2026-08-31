package queue

import (
	"time"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

type DeadLetter struct {
	Envelope *commonv1.EventEnvelope
	Reason   string
	At       time.Time
}

type DeadLetterSink interface {
	Quarantine(DeadLetter) error
}
