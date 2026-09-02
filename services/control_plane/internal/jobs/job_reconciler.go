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
	operationsapp "github.com/mindclade/mindclade/services/control_plane/internal/operations"
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
// perform the transition. Domain-specific producers may also have created the
// scheduler Run in their acceptance transaction. The handler preserves that
// Run and creates the generic one only when the Job has none.
type JobRequestedHandler struct{}

func (JobRequestedHandler) HandleEvent(ctx context.Context, tx *sql.Tx, envelope *commonv1.EventEnvelope, payload proto.Message) error {
	requested, ok := payload.(*jobv1.JobRequested)
	if !ok || requested.GetJobId() == "" || !validEventDigest(requested.GetConfigurationDigest()) {
		return errors.New("JobRequested consumer requires the exact generated payload with job and configuration digest")
	}
	if envelope == nil || envelope.GetTenantId() == "" || envelope.GetProjectId() == "" || envelope.GetJobId() != requested.GetJobId() {
		return errors.New("JobRequested envelope scope does not match its payload")
	}
	if envelope.GetOccurredAt() == nil || envelope.GetOccurredAt().CheckValid() != nil {
		return errors.New("JobRequested envelope requires a valid occurrence time")
	}
	at := envelope.GetOccurredAt().AsTime().UTC()
	var projectID, operationID, state, configurationDigest string
	var version int64
	var inputRefID, configurationRefID sql.NullInt64
	err := tx.QueryRowContext(ctx, `SELECT project_id,operation_id,desired_state,version,configuration_digest,input_ref_id,configuration_ref_id FROM jobs WHERE tenant_id=$1 AND project_id=$2 AND id=$3 FOR UPDATE`, envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId()).Scan(&projectID, &operationID, &state, &version, &configurationDigest, &inputRefID, &configurationRefID)
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
		result, updateErr := tx.ExecContext(ctx, `UPDATE jobs SET desired_state='QUEUED',version=$5,etag=$6,updated_at=$7 WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND version=$4 AND desired_state='ACCEPTED'`, envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId(), version, nextVersion, operationsapp.ResourceETag(envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId(), nextVersion), at)
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
		state, version = "QUEUED", nextVersion
	case "QUEUED", "RUNNING":
		// Reconcile below.
	case "CANCELLING":
		// A cancellation committed before delivery wins. In particular, do not
		// manufacture new schedulable work after that boundary.
		return nil
	case "SUCCEEDED", "FAILED", "CANCELLED":
		return fmt.Errorf("JobRequested cannot reconcile terminal job state %s", state)
	default:
		return fmt.Errorf("JobRequested encountered unknown durable job state %q", state)
	}

	rows, err := tx.QueryContext(ctx, `SELECT id FROM runs WHERE tenant_id=$1 AND project_id=$2 AND job_id=$3 ORDER BY id LIMIT 2 FOR UPDATE`, envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId())
	if err != nil {
		return err
	}
	defer func() { _ = rows.Close() }()
	runIDs := make([]string, 0, 2)
	for rows.Next() {
		var runID string
		if err = rows.Scan(&runID); err != nil {
			return err
		}
		runIDs = append(runIDs, runID)
	}
	if err = rows.Err(); err != nil {
		return err
	}
	if err = rows.Close(); err != nil {
		return err
	}
	if len(runIDs) > 1 {
		return fmt.Errorf("JobRequested found multiple scheduler runs for job %q", requested.GetJobId())
	}
	if len(runIDs) == 0 {
		if state == "RUNNING" {
			return fmt.Errorf("JobRequested found RUNNING job %q without a scheduler run", requested.GetJobId())
		}
		runID := deterministicJobRunID(envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId())
		_, err = tx.ExecContext(ctx, `INSERT INTO runs (id,tenant_id,project_id,job_id,input_ref_id,configuration_ref_id,plan_ref_id,status,version,lease_epoch,error_detail_id,etag,created_at,started_at,completed_at,updated_at) VALUES ($1,$2,$3,$4,$5,$6,NULL,'READY',1,0,NULL,$7,$8,NULL,NULL,$8)`, runID, envelope.GetTenantId(), envelope.GetProjectId(), requested.GetJobId(), inputRefID, configurationRefID, operationsapp.ResourceETag(envelope.GetTenantId(), envelope.GetProjectId(), runID, 1), at)
		if err != nil {
			return err
		}
	}

	if operationID == "" {
		return errors.New("JobRequested durable job has no operation")
	}
	var operationState string
	if err = tx.QueryRowContext(ctx, `SELECT status FROM operations WHERE tenant_id=$1 AND project_id=$2 AND id=$3 AND job_id=$4 FOR UPDATE`, envelope.GetTenantId(), envelope.GetProjectId(), operationID, requested.GetJobId()).Scan(&operationState); errors.Is(err, sql.ErrNoRows) {
		return errors.New("JobRequested durable job has no matching operation")
	} else if err != nil {
		return err
	}
	if operationState != "PENDING" && operationState != "RUNNING" {
		return fmt.Errorf("JobRequested cannot reconcile operation state %s", operationState)
	}
	return nil
}

// deterministicJobRunID is the stable v1 projection of a canonical scoped
// Job identity. The explicit version/domain separator makes later schemes
// additive rather than silently changing the identity of already-requested
// work.
func deterministicJobRunID(tenantID, projectID, jobID string) string {
	digest := sha256.Sum256([]byte("mindclade.scheduler.run/v1\x00" + tenantID + "\x00" + projectID + "\x00" + jobID))
	return "runs/" + hex.EncodeToString(digest[:])
}

func validEventDigest(value string) bool {
	if len(value) != len("sha256:")+64 || !strings.HasPrefix(value, "sha256:") || strings.ToLower(value) != value {
		return false
	}
	_, err := hex.DecodeString(strings.TrimPrefix(value, "sha256:"))
	return err == nil
}
