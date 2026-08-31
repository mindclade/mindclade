package audit

import (
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"google.golang.org/protobuf/proto"

	auditv1 "github.com/mindclade/mindclade/protocols/generated/go/audit/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/platform/queue"
)

// eventRow represents normalized audit columns plus the immutable protobuf
// bytes permitted at the audit boundary. It is private and cannot become a
// second event API.
type eventRow struct {
	eventID, tenantID, actorID, action, subjectID string
	occurredAt                                    time.Time
	payloadDigest                                 string
	envelopeBytes                                 []byte
}

type Store struct {
	mu   sync.Mutex
	rows []eventRow
}

func (s *Store) Append(envelope *commonv1.EventEnvelope) error {
	if err := queue.ValidateEnvelope(envelope); err != nil {
		return err
	}
	payload := new(auditv1.AuditEvent)
	expectedType := string(payload.ProtoReflect().Descriptor().FullName())
	if envelope.GetEventType() != expectedType {
		return fmt.Errorf("unexpected audit event type %q", envelope.GetEventType())
	}
	if err := proto.Unmarshal(envelope.GetPayload(), payload); err != nil {
		return fmt.Errorf("unmarshal audit payload: %w", err)
	}
	if payload.GetActorPrincipalId() == "" || payload.GetAction() == "" || (payload.GetDecision() != "allowed" && payload.GetDecision() != "denied") {
		return errors.New("invalid redacted audit payload")
	}
	if len(payload.GetActorPrincipalId()) > 512 || len(payload.GetAction()) > 256 || len(envelope.GetSubject().GetResourceId()) > 1024 {
		return errors.New("audit identity exceeds safe durable bounds")
	}
	if payload.GetPolicyDigest() != "" && !validDigest(payload.GetPolicyDigest()) {
		return errors.New("invalid audit policy digest")
	}
	if envelope.GetClassification() == commonv1.DataClassification_DATA_CLASSIFICATION_PUBLIC {
		return errors.New("audit evidence cannot be classified public")
	}
	encoded, err := proto.MarshalOptions{Deterministic: true}.Marshal(envelope)
	if err != nil {
		return fmt.Errorf("marshal audit envelope: %w", err)
	}
	row := eventRow{
		eventID: envelope.GetEventId(), tenantID: envelope.GetTenantId(), actorID: payload.GetActorPrincipalId(),
		action: payload.GetAction(), subjectID: envelope.GetSubject().GetResourceId(), occurredAt: envelope.GetOccurredAt().AsTime().UTC(),
		payloadDigest: envelope.GetPayloadDigest(), envelopeBytes: encoded,
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.rows = append(s.rows, row)
	return nil
}

func (s *Store) Events(tenantID string) ([]*commonv1.EventEnvelope, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	result := make([]*commonv1.EventEnvelope, 0, len(s.rows))
	for _, row := range s.rows {
		if row.tenantID != tenantID {
			continue
		}
		envelope, err := queue.UnmarshalEnvelope(row.envelopeBytes)
		if err != nil {
			return nil, err
		}
		result = append(result, envelope)
	}
	return result, nil
}

func validDigest(value string) bool {
	if len(value) != len("sha256:")+64 || !strings.HasPrefix(value, "sha256:") || value != strings.ToLower(value) {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}
