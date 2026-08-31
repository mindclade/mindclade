package storage

import (
	"context"
	"fmt"
	"time"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	"google.golang.org/protobuf/proto"
)

// Claim is an adapter around the authoritative generated envelope. Scheduling
// and fencing metadata stays private so it cannot become a competing message
// contract.
type Claim struct {
	Envelope *commonv1.EventEnvelope
	delivery deliveryMetadata
}

type deliveryMetadata struct {
	epoch       uint64
	availableAt time.Time
}

func NewClaim(envelope *commonv1.EventEnvelope, epoch uint64, availableAt time.Time) (Claim, error) {
	if envelope == nil || envelope.GetEventId() == "" || epoch == 0 || availableAt.IsZero() {
		return Claim{}, fmt.Errorf("invalid outbox claim")
	}
	return Claim{
		Envelope: proto.Clone(envelope).(*commonv1.EventEnvelope),
		delivery: deliveryMetadata{epoch: epoch, availableAt: availableAt.UTC()},
	}, nil
}

func (claim Claim) DeliveryEpoch() uint64 { return claim.delivery.epoch }

func (claim Claim) AvailableAt() time.Time { return claim.delivery.availableAt }

type Outbox interface {
	Enqueue(context.Context, *commonv1.EventEnvelope, time.Time) error
	Claim(context.Context, int, time.Time) ([]Claim, error)
	Acknowledge(context.Context, string, uint64) error
}
