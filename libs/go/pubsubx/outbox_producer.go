package pubsubx

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

// MaxOutboxEnvelopeBytes bounds a single enqueued envelope.
//
// The bound exists so an oversized event fails at the write, inside the
// caller's transaction, rather than at the relay. A relay-side failure is
// discovered asynchronously: the row burns its publish attempts, lands in
// quarantine, and the operator reads a dead letter instead of a stack trace
// pointing at the code that produced it. The write is the last point at which
// the failure is still attached to its cause.
//
// The value matches the internal SDK's message ceiling, so an event too large
// to enqueue is also too large for a client to have sent.
const MaxOutboxEnvelopeBytes = 8 << 20

// insertOutboxMessage is the single statement that writes the outbox. Every
// producing service shares it, so a column added here cannot be missed by one
// caller. The fourteen hand-copied variants this replaced had already drifted:
// one omitted the resource_id fallback below, another sourced the tenant from
// its command rather than the envelope, and none bounded the envelope size.
const insertOutboxMessage = `INSERT INTO outbox_messages` +
	` (id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,` +
	`aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at)` +
	` VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`

// OutboxExecutor is the minimal database surface the producer needs. A
// *sql.Tx satisfies it, which is the only way callers are meant to use this:
// the row must be written with the caller's transaction so the event is
// enqueued if and only if the business change commits.
type OutboxExecutor interface {
	ExecContext(context.Context, string, ...any) (sql.Result, error)
	// Rollback is never called here. It is in the interface because *sql.Tx has
	// it and *sql.DB does not, which is what makes "must run in the caller's
	// transaction" a thing the compiler checks rather than a comment. A
	// *sql.DB passed here would insert the row whether or not the business
	// change committed -- the one guarantee the outbox exists to provide.
	Rollback() error
}

// InsertOutboxMessage enqueues one event envelope for delivery.
//
// THIS FUNCTION MUST BE CALLED WITHIN THE CALLER'S TRANSACTION. Nothing is
// delivered inline; a background relay claims committed rows and publishes
// them.
//
// Every column is derived from the envelope. That is deliberate: the row is a
// routing and integrity projection of the envelope it carries, so a row whose
// tenant or aggregate identity disagreed with its own payload would be
// unreadable by the consumer that trusts the envelope. Callers that hold a
// tenant identifier separately must not pass it — if it differs from
// envelope.tenant_id the envelope is wrong, and writing the caller's value
// would hide that rather than surface it.
func InsertOutboxMessage(ctx context.Context, exec OutboxExecutor, envelope *commonv1.EventEnvelope, at time.Time) error {
	// MarshalEnvelope validates, so it runs first and this function validates
	// exactly once. `aggregateIdentity` then derives from the validated
	// envelope through the same definition `AggregateIdentity` exports.
	// Deriving it inline instead is what let one variant read only subject.name
	// and drop the resource_id fallback, which would have written an empty
	// aggregate_id -- and so a broken ordering key -- for any subject that
	// carried an id but no name.
	encoded, err := MarshalEnvelope(envelope)
	if err != nil {
		return err
	}
	aggregateType, aggregateID := aggregateIdentity(envelope)
	if len(encoded) > MaxOutboxEnvelopeBytes {
		return fmt.Errorf(
			"%w: envelope for %s is %d bytes, over the %d byte outbox limit",
			ErrInvalidEnvelope, envelope.GetEventType(), len(encoded), MaxOutboxEnvelopeBytes,
		)
	}
	_, err = exec.ExecContext(
		ctx, insertOutboxMessage,
		envelope.GetEventId(),
		envelope.GetTenantId(),
		envelope.GetEventType(),
		envelope.GetEventVersion(),
		aggregateType,
		aggregateID,
		envelope.GetAggregateSequence(),
		envelope.GetPayloadDigest(),
		encoded,
		at.UTC(),
	)
	return err
}
