package experiments

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"time"

	foundationaudit "github.com/mindclade/mindclade/libs/go/audit"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
)

type receipt struct {
	resourceType string
	resourceName string
	revision     int64
}

func (repository SQLRepository) validate() error {
	if repository.DB == nil || repository.Pagination == nil || repository.Events == nil {
		return errors.New("experiment SQL repository requires database, pagination codec, and event factory")
	}
	return nil
}

func randomID(prefix string) (string, error) {
	value := make([]byte, 18)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return prefix + base64.RawURLEncoding.EncodeToString(value), nil
}

func checkReceipt(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest string) (receipt, bool, error) {
	lock := fmt.Sprintf("%d:%s:%d:%s:%d:%s:%s:%s", len(identity.TenantID), identity.TenantID, len(identity.ProjectID), identity.ProjectID, len(identity.Principal), identity.Principal, action, key)
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, lock); err != nil {
		return receipt{}, false, err
	}
	var stored string
	var value receipt
	err := tx.QueryRowContext(ctx, `SELECT request_digest,resource_type,resource_name,resource_revision FROM experiment_command_receipts WHERE tenant_id=$1 AND project_id=$2 AND principal_id=$3 AND action=$4 AND idempotency_key=$5`, identity.TenantID, identity.ProjectID, identity.Principal, action, key).Scan(&stored, &value.resourceType, &value.resourceName, &value.revision)
	if errors.Is(err, sql.ErrNoRows) {
		return receipt{}, false, nil
	}
	if err != nil {
		return receipt{}, false, err
	}
	if subtle.ConstantTimeCompare([]byte(stored), []byte(digest)) != 1 {
		return receipt{}, false, ErrIdempotencyConflict
	}
	return value, true, nil
}

func recordMutation(ctx context.Context, tx *sql.Tx, identity Identity, action, key, digest, resourceType, resourceName string, revision int64, event *commonv1.EventEnvelope, at time.Time) error {
	if event == nil || event.GetSubject() == nil || revision < 1 {
		return ErrInvalidArgument
	}
	auditEvent, err := foundationaudit.NewEvent(identity.TenantID, identity.Principal, action, resourceName, "allowed", at.UTC(), nil)
	if err != nil {
		return err
	}
	auditBytes, err := pubsubx.MarshalEnvelope(auditEvent)
	if err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO audit_events(id,tenant_id,actor_id,action,subject_id,occurred_at,details_digest,event_version,payload_digest,envelope_bytes) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, auditEvent.GetEventId(), identity.TenantID, identity.Principal, action, resourceName, at.UTC(), digest, auditEvent.GetEventVersion(), auditEvent.GetPayloadDigest(), auditBytes); err != nil {
		return err
	}
	if err = pubsubx.InsertOutboxMessage(ctx, tx, event, at); err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO experiment_command_receipts(tenant_id,project_id,principal_id,action,idempotency_key,request_digest,resource_type,resource_name,resource_revision,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, identity.TenantID, identity.ProjectID, identity.Principal, action, key, digest, resourceType, resourceName, revision, at.UTC())
	return err
}

func storeMap(ctx context.Context, tx *sql.Tx, table, ownerColumn, keyColumn, valueColumn string, identity Identity, owner string, values map[string]string) error {
	// Identifiers are selected exclusively by repository-owned call sites.
	query := `INSERT INTO ` + table + `(tenant_id,project_id,` + ownerColumn + `,` + keyColumn + `,` + valueColumn + `) VALUES($1,$2,$3,$4,$5)` //nolint:gosec
	for _, key := range sortedMapKeys(values) {
		if _, err := tx.ExecContext(ctx, query, identity.TenantID, identity.ProjectID, owner, key, values[key]); err != nil {
			return err
		}
	}
	return nil
}

func compareDigest(canonical, supplied string) error {
	if subtle.ConstantTimeCompare([]byte(canonical), []byte(supplied)) != 1 {
		return ErrInvalidArgument
	}
	return nil
}
