package jobs

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"

	"google.golang.org/protobuf/proto"

	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
)

type LeaseObserver interface {
	Observe(context.Context, *jobv1.Attempt) (string, error)
}

type Reconciler struct{ Observer LeaseObserver }

// Reconcile observes external workload state; it does not provide a DB capability to workers.
func (r Reconciler) Reconcile(ctx context.Context, attempt *jobv1.Attempt) (string, error) {
	return r.Observer.Observe(ctx, attempt)
}

// JobRequestedHandler is the first production Pub/Sub consumer. The inbox
// layer invokes it inside the same tenant-scoped transaction as the durable
// receipt, so a crash cannot commit only one side of the reconciliation.
//
// Current producers already transition ACCEPTED to QUEUED in the command
// transaction. QUEUED (or a later non-terminal state) is therefore a valid
// idempotent observation; an older producer may still require this handler to
// perform the transition.
type JobRequestedHandler struct{}

func (JobRequestedHandler) HandleEvent(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, payload proto.Message) error {
	requested, ok := payload.(*jobv1.JobRequested)
	if !ok || requested.GetJobId() == "" || !validEventDigest(requested.GetConfigurationDigest()) {
		return errors.New("JobRequested consumer requires the exact generated payload with job and configuration digest")
	}
	if envelope == nil || envelope.GetTenantId() == "" || envelope.GetProjectId() == "" || envelope.GetJobId() != requested.GetJobId() {
		return errors.New("JobRequested envelope scope does not match its payload")
	}
	var projectID, state, configurationDigest string
	var version int64
	err := tx.QueryRowContext(ctx, `SELECT project_id,desired_state,version,configuration_digest FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId()).Scan(&projectID, &state, &version, &configurationDigest)
	if errors.Is(err, sql.ErrNoRows) {
		return fmt.Errorf("JobRequested references unknown job %q", requested.GetJobId())
	}
	if err != nil {
		return err
	}
	if projectID != envelope.GetProjectId() {
		return errors.New("JobRequested project does not match durable job scope")
	}
	if configurationDigest != requested.GetConfigurationDigest() {
		return errors.New("JobRequested configuration digest does not match durable job")
	}
	switch state {
	case "ACCEPTED":
		nextVersion := version + 1
		result, updateErr := tx.ExecContext(ctx, `UPDATE jobs SET desired_state='QUEUED',version=$5,etag=$6,updated_at=now() WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4 AND desired_state='ACCEPTED'`, envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId(), version, nextVersion, eventResourceETag(requested.GetJobId(), nextVersion))
		if updateErr != nil {
			return updateErr
		}
		updated, updateErr := result.RowsAffected()
		if updateErr != nil {
			return updateErr
		}
		if updated != 1 {
			return errors.New("JobRequested lost its locked job transition")
		}
		return nil
	case "QUEUED", "RUNNING", "CANCELLING":
		return nil
	case "SUCCEEDED", "FAILED", "CANCELLED":
		return fmt.Errorf("JobRequested cannot reconcile terminal job state %s", state)
	default:
		return fmt.Errorf("JobRequested encountered unknown durable job state %q", state)
	}
}

func eventResourceETag(name string, revision int64) string {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d", name, revision)))
	return "sha256:" + hex.EncodeToString(digest[:])
}

func validEventDigest(value string) bool {
	if len(value) != len("sha256:")+64 || !strings.HasPrefix(value, "sha256:") || strings.ToLower(value) != value {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}
