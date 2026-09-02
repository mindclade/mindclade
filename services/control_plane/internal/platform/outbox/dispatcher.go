package outbox

import (
	"context"
	"errors"
	"fmt"
	"time"

	gcppubsub "cloud.google.com/go/pubsub/v2"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

var ErrDeliveryClaimLost = errors.New("outbox delivery claim lost")

const DefaultMaxPublishAttempts uint32 = 10

// Publisher is called only after the command transaction commits.
type Publisher interface {
	Publish(context.Context, *commonv1.EventEnvelope) error
}

type DeliveryStore interface {
	Claim(context.Context, string, int, time.Time, time.Duration) ([]DeliveryRecord, error)
	Acknowledge(context.Context, string, string, uint64, time.Time) (bool, error)
	Retry(context.Context, string, string, uint64, time.Time, error) (bool, error)
	Quarantine(context.Context, string, string, uint64, time.Time, error) (bool, error)
}

type Dispatcher struct {
	Store       DeliveryStore
	Publisher   Publisher
	Now         func() time.Time
	ClaimTTL    time.Duration
	RetryDelay  func(uint32) time.Duration
	MaxAttempts uint32
}

// DeliverBatch supports both the SQLStore and deterministic in-memory test
// store through the same claim/ack/retry fencing contract.
func (d Dispatcher) DeliverBatch(ctx context.Context, tenantID string, limit int) (int, error) {
	if d.Store == nil || d.Publisher == nil {
		return 0, errors.New("outbox dispatcher requires a store and publisher")
	}
	nowFn := d.Now
	if nowFn == nil {
		nowFn = time.Now
	}
	claimTTL := d.ClaimTTL
	if claimTTL == 0 {
		claimTTL = 30 * time.Second
	}
	claimedAt := nowFn().UTC()
	records, err := d.Store.Claim(ctx, tenantID, limit, claimedAt, claimTTL)
	if err != nil {
		return 0, err
	}
	delivered := 0
	var failures []error
	maxAttempts := d.MaxAttempts
	if maxAttempts == 0 {
		maxAttempts = DefaultMaxPublishAttempts
	}
	if maxAttempts > 1000 {
		return 0, errors.New("outbox maximum publish attempts must not exceed 1000")
	}
	for _, record := range records {
		if record.DecodeError != nil || record.Envelope == nil {
			cause := record.DecodeError
			if cause == nil {
				cause = queue.ErrInvalidEnvelope
			}
			quarantined, quarantineErr := d.Store.Quarantine(ctx, record.TenantID, record.ID, record.DeliveryEpoch, nowFn().UTC(), cause)
			switch {
			case quarantineErr != nil:
				failures = append(failures, errors.Join(cause, quarantineErr))
			case !quarantined:
				failures = append(failures, fmt.Errorf("%w: quarantine %s@%d", ErrDeliveryClaimLost, record.ID, record.DeliveryEpoch))
			default:
				failures = append(failures, fmt.Errorf("quarantined corrupt outbox event %s: %w", record.ID, cause))
			}
			continue
		}
		if err = d.Publisher.Publish(ctx, record.Envelope); err != nil {
			if record.PublishAttempts >= maxAttempts {
				quarantined, quarantineErr := d.Store.Quarantine(ctx, record.TenantID, record.ID, record.DeliveryEpoch, nowFn().UTC(), err)
				switch {
				case quarantineErr != nil:
					failures = append(failures, errors.Join(err, quarantineErr))
				case !quarantined:
					failures = append(failures, fmt.Errorf("%w: quarantine %s@%d", ErrDeliveryClaimLost, record.ID, record.DeliveryEpoch))
				default:
					failures = append(failures, fmt.Errorf("publish attempts exhausted for %s: %w", record.ID, err))
				}
				continue
			}
			delay := defaultRetryDelay(record.PublishAttempts)
			if d.RetryDelay != nil {
				delay = d.RetryDelay(record.PublishAttempts)
			}
			if delay < 0 || delay > 24*time.Hour {
				failures = append(failures, fmt.Errorf("%s: invalid retry delay", record.ID))
				continue
			}
			updated, retryErr := d.Store.Retry(ctx, record.TenantID, record.ID, record.DeliveryEpoch, nowFn().UTC().Add(delay), err)
			switch {
			case retryErr != nil:
				failures = append(failures, errors.Join(err, retryErr))
			case !updated:
				failures = append(failures, fmt.Errorf("%w: retry %s@%d", ErrDeliveryClaimLost, record.ID, record.DeliveryEpoch))
			default:
				failures = append(failures, fmt.Errorf("publish %s: %w", record.ID, err))
			}
			continue
		}
		acknowledged, ackErr := d.Store.Acknowledge(ctx, record.TenantID, record.ID, record.DeliveryEpoch, nowFn().UTC())
		if ackErr != nil {
			failures = append(failures, ackErr)
			continue
		}
		if !acknowledged {
			failures = append(failures, fmt.Errorf("%w: acknowledge %s@%d", ErrDeliveryClaimLost, record.ID, record.DeliveryEpoch))
			continue
		}
		delivered++
	}
	return delivered, errors.Join(failures...)
}

func defaultRetryDelay(attempt uint32) time.Duration {
	if attempt == 0 {
		attempt = 1
	}
	shift := attempt - 1
	if shift > 8 {
		shift = 8
	}
	return time.Second * (1 << shift)
}

// PubSubPublisher is the production Google Cloud Pub/Sub transport adapter.
// The client owns authentication; this adapter publishes canonical protobuf
// envelope bytes and blocks for the server acknowledgement before outbox ack.
type PubSubPublisher struct {
	publisher *gcppubsub.Publisher
}

func NewPubSubPublisher(client *gcppubsub.Client, topicName string) (*PubSubPublisher, error) {
	if client == nil || topicName == "" {
		return nil, errors.New("Pub/Sub client and topic are required")
	}
	publisher := client.Publisher(topicName)
	publisher.EnableMessageOrdering = true
	return &PubSubPublisher{publisher: publisher}, nil
}

func (p *PubSubPublisher) Publish(ctx context.Context, envelope *commonv1.EventEnvelope) error {
	if p == nil || p.publisher == nil {
		return errors.New("Pub/Sub publisher is not initialized")
	}
	encoded, err := queue.MarshalEnvelope(envelope)
	if err != nil {
		return err
	}
	orderingKey, err := queue.OrderingKey(envelope)
	if err != nil {
		return err
	}
	attributes, err := queue.TransportAttributes(envelope)
	if err != nil {
		return err
	}
	result := p.publisher.Publish(ctx, &gcppubsub.Message{
		Data:        encoded,
		OrderingKey: orderingKey,
		Attributes:  attributes,
	})
	if _, err = result.Get(ctx); err != nil {
		// Pub/Sub pauses this ordering key after an asynchronous publish error.
		// Resume before returning so the durable outbox retry can make progress.
		p.publisher.ResumePublish(orderingKey)
		return fmt.Errorf("publish Pub/Sub event %s: %w", envelope.GetEventId(), err)
	}
	return nil
}

func (p *PubSubPublisher) Close() {
	if p != nil && p.publisher != nil {
		p.publisher.Stop()
	}
}
