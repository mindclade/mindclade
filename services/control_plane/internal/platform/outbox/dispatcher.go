package outbox

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"time"

	gcppubsub "cloud.google.com/go/pubsub/v2"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

var ErrDeliveryClaimLost = errors.New("outbox delivery claim lost")

// Publisher is called only after the command transaction commits.
type Publisher interface {
	Publish(context.Context, *commonv1.EventEnvelope) error
}

type DeliveryStore interface {
	Claim(context.Context, string, int, time.Time, time.Duration) ([]DeliveryRecord, error)
	Acknowledge(context.Context, string, string, uint64, time.Time) (bool, error)
	Retry(context.Context, string, string, uint64, time.Time, error) (bool, error)
}

type Dispatcher struct {
	Store      DeliveryStore
	Publisher  Publisher
	Now        func() time.Time
	ClaimTTL   time.Duration
	RetryDelay func(uint32) time.Duration
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
	for _, record := range records {
		if err = d.Publisher.Publish(ctx, record.Envelope); err != nil {
			delay := defaultRetryDelay(record.PublishAttempts)
			if d.RetryDelay != nil {
				delay = d.RetryDelay(record.PublishAttempts)
			}
			if delay < 0 || delay > 24*time.Hour {
				failures = append(failures, fmt.Errorf("%s: invalid retry delay", record.ID))
				continue
			}
			updated, retryErr := d.Store.Retry(ctx, record.TenantID, record.ID, record.DeliveryEpoch, nowFn().UTC().Add(delay), err)
			if retryErr != nil {
				failures = append(failures, errors.Join(err, retryErr))
			} else if !updated {
				failures = append(failures, fmt.Errorf("%w: retry %s@%d", ErrDeliveryClaimLost, record.ID, record.DeliveryEpoch))
			} else {
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
	return time.Second * time.Duration(uint64(1)<<shift)
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
	orderingSource := envelope.GetTenantId() + "\x00" + envelope.GetSubject().GetResourceType() + "\x00" + envelope.GetSubject().GetResourceId()
	orderingDigest := sha256.Sum256([]byte(orderingSource))
	result := p.publisher.Publish(ctx, &gcppubsub.Message{
		Data:        encoded,
		OrderingKey: "sha256:" + hex.EncodeToString(orderingDigest[:]),
		Attributes: map[string]string{
			"event_id":             envelope.GetEventId(),
			"event_type":           envelope.GetEventType(),
			"event_version":        strconv.FormatUint(uint64(envelope.GetEventVersion()), 10),
			"tenant_id":            envelope.GetTenantId(),
			"payload_digest":       envelope.GetPayloadDigest(),
			"payload_content_type": envelope.GetPayloadContentType(),
		},
	})
	if _, err = result.Get(ctx); err != nil {
		return fmt.Errorf("publish Pub/Sub event %s: %w", envelope.GetEventId(), err)
	}
	return nil
}

func (p *PubSubPublisher) Close() {
	if p != nil && p.publisher != nil {
		p.publisher.Stop()
	}
}
