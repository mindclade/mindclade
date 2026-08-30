package queue

import "time"

type DeadLetter struct {
	Envelope Envelope
	Reason   string
	At       time.Time
}

type DeadLetterSink interface {
	Quarantine(DeadLetter) error
}
