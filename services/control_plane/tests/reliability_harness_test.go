package controlplane_test

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"

	"github.com/mindclade/mindclade/libs/go/inbox"
	"github.com/mindclade/mindclade/libs/go/outbox"
	"github.com/mindclade/mindclade/libs/go/pubsubx"
	artifactv1 "github.com/mindclade/mindclade/protocols/generated/go/artifact/v1"
	commonv1 "github.com/mindclade/mindclade/protocols/generated/go/common/v1"
	jobv1 "github.com/mindclade/mindclade/protocols/generated/go/job/v1"
	"github.com/mindclade/mindclade/services/control_plane/internal/jobs"
	"github.com/mindclade/mindclade/services/control_plane/internal/operations"
	"github.com/mindclade/mindclade/services/control_plane/internal/policies"
)

// reliabilityHarness gives every recovery scenario an isolated tenant while
// exercising the production SQL stores, transaction boundaries, and generated
// protobuf envelopes. It deliberately has no production credentials or cloud
// dependency; Pub/Sub delivery is represented by the same Publisher seam used
// by the production dispatcher.
type reliabilityHarness struct {
	t       *testing.T
	db      *sql.DB
	tenant  string
	project string
	now     time.Time
}

func newReliabilityHarness(t *testing.T, db *sql.DB, scenario string) *reliabilityHarness {
	t.Helper()
	suffix := fmt.Sprintf("%s-%d", scenario, time.Now().UTC().UnixNano())
	h := &reliabilityHarness{
		t: t, db: db, tenant: "tenant-reliability-" + suffix,
		project: "project-reliability", now: time.Now().UTC(),
	}
	t.Cleanup(func() {
		for _, table := range []string{
			"dead_letter_replay_receipts", "run_command_receipt_attempts", "run_command_receipts",
			"attempt_completion_history", "attempt_output_refs", "attempts", "run_output_refs", "runs",
			"inbox_delivery_failures", "inbox_messages", "dead_letter_messages", "outbox_messages",
			"audit_events", "idempotency_records", "operations", "jobs", "error_precondition_violations",
			"error_field_violations", "error_details", "artifacts", "artifact_references",
		} {
			if _, err := db.ExecContext(h.context(), "DELETE FROM "+table+" WHERE tenant_id=$1", h.tenant); err != nil { //nolint:gosec // Closed, reviewed table list; tenant remains a bound parameter.
				t.Errorf("clean reliability table %s: %v", table, err)
			}
		}
	})
	return h
}

func (*reliabilityHarness) context() context.Context { return context.Background() }

func (h *reliabilityHarness) envelope(id string) *commonv1.EventEnvelope {
	h.t.Helper()
	repository := operations.NewRepository()
	_, _, err := operations.Create(policies.DenyByDefault{}, repository, operations.CreateCommand{
		Principal: policies.Principal{
			ID: h.tenant + "-principal", TenantID: h.tenant,
			Actions: map[string]bool{operations.CreateAction: true},
		},
		IdempotencyKey:      "create-" + id,
		RequestDigest:       digestFor("1"),
		ConfigurationDigest: digestFor("2"),
		Operation: &jobv1.Operation{
			OperationId: "operation-" + id, TenantId: h.tenant, ProjectId: h.project,
			JobId: "job-" + id, Etag: "operation-etag-1",
		},
	})
	if err != nil {
		h.t.Fatalf("create reliability envelope: %v", err)
	}
	return repository.OutboxEnvelopes()[0]
}

func (h *reliabilityHarness) insertOutbox(envelope *commonv1.EventEnvelope, at time.Time) {
	h.t.Helper()
	encoded, err := pubsubx.MarshalEnvelope(envelope)
	if err != nil {
		h.t.Fatal(err)
	}
	aggregateType, aggregateID, err := pubsubx.AggregateIdentity(envelope)
	if err != nil {
		h.t.Fatal(err)
	}
	if _, err = h.db.ExecContext(h.context(), `
INSERT INTO outbox_messages (
  id,tenant_id,event_type,event_version,aggregate_type,aggregate_id,
  aggregate_sequence,payload_digest,envelope_bytes,next_attempt_at,created_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)`, envelope.GetEventId(), h.tenant,
		envelope.GetEventType(), envelope.GetEventVersion(), aggregateType, aggregateID,
		envelope.GetAggregateSequence(), envelope.GetPayloadDigest(), encoded, at.UTC()); err != nil {
		h.t.Fatalf("insert reliability outbox envelope: %v", err)
	}
}

func (h *reliabilityHarness) runPublishBeforeAckCrash() {
	envelope := h.envelope("publish-before-ack")
	h.insertOutbox(envelope, h.now)
	store := &failingAcknowledgeStore{delegate: outbox.SQLStore{DB: h.db}, remaining: 1}
	publisher := &recordingPublisher{}
	dispatchAt := h.now
	dispatcher := outbox.Dispatcher{
		Store: store, Publisher: publisher, Now: func() time.Time { return dispatchAt }, ClaimTTL: time.Second,
	}
	if delivered, err := dispatcher.DeliverBatch(h.context(), h.tenant, 1); delivered != 0 || err == nil {
		h.t.Fatalf("publish-before-ack crash: delivered=%d err=%v", delivered, err)
	}
	dispatchAt = h.now.Add(2 * time.Second)
	if delivered, err := dispatcher.DeliverBatch(h.context(), h.tenant, 1); delivered != 1 || err != nil {
		h.t.Fatalf("publish-before-ack recovery: delivered=%d err=%v", delivered, err)
	}
	if len(publisher.published) != 2 || !proto.Equal(publisher.published[0], publisher.published[1]) {
		h.t.Fatalf("crash recovery must republish the same immutable envelope: %v", publisher.published)
	}
}

func (h *reliabilityHarness) runDuplicateAndInboxRollback() {
	envelope := h.envelope("inbox-atomicity")
	payload, err := pubsubx.UnmarshalRegisteredPayload(envelope)
	if err != nil {
		h.t.Fatal(err)
	}
	marker := digestFor("3")
	calls, fail := 0, true
	handler := inbox.TransactionalHandlerFunc(func(ctx context.Context, tx *sql.Tx, _ *commonv1.EventEnvelope, _ proto.Message) error {
		calls++
		if _, insertErr := tx.ExecContext(ctx, `INSERT INTO artifacts (digest,tenant_id,media_type,byte_size,created_at) VALUES ($1,$2,'application/octet-stream',1,now())`, marker, h.tenant); insertErr != nil {
			return insertErr
		}
		if fail {
			return errors.New("synthetic rollback")
		}
		return nil
	})
	if accepted, handleErr := inbox.AcceptAndHandleSQL(h.context(), h.db, "reliability-atomic-worker", envelope, payload, handler); accepted || handleErr == nil {
		h.t.Fatalf("failed inbox mutation must roll back: accepted=%v err=%v", accepted, handleErr)
	}
	var receipts, markers int
	if err = h.db.QueryRowContext(h.context(), `SELECT count(*) FROM inbox_messages WHERE tenant_id=$1 AND consumer='reliability-atomic-worker'`, h.tenant).Scan(&receipts); err != nil {
		h.t.Fatal(err)
	}
	if err = h.db.QueryRowContext(h.context(), `SELECT count(*) FROM artifacts WHERE tenant_id=$1 AND digest=$2`, h.tenant, marker).Scan(&markers); err != nil {
		h.t.Fatal(err)
	}
	if receipts != 0 || markers != 0 {
		h.t.Fatalf("rollback leaked receipt=%d marker=%d", receipts, markers)
	}
	fail = false
	if accepted, handleErr := inbox.AcceptAndHandleSQL(h.context(), h.db, "reliability-atomic-worker", envelope, payload, handler); !accepted || handleErr != nil {
		h.t.Fatalf("successful inbox mutation: accepted=%v err=%v", accepted, handleErr)
	}
	if accepted, handleErr := inbox.AcceptAndHandleSQL(h.context(), h.db, "reliability-atomic-worker", envelope, payload, handler); accepted || handleErr != nil || calls != 2 {
		h.t.Fatalf("duplicate delivery reran handler: accepted=%v calls=%d err=%v", accepted, calls, handleErr)
	}
}

func (h *reliabilityHarness) runReorderedSequenceGap() {
	first := h.envelope("sequence-gap")
	first.EventId = "first-" + first.GetEventId()
	first.DeduplicationKey = first.GetEventId()
	second := proto.Clone(first).(*commonv1.EventEnvelope)
	second.EventId = "second-" + second.GetEventId()
	second.DeduplicationKey = second.GetEventId()
	second.AggregateSequence = 2
	h.insertOutbox(second, h.now)
	publisher := &recordingPublisher{}
	dispatcher := outbox.Dispatcher{Store: outbox.SQLStore{DB: h.db}, Publisher: publisher, Now: func() time.Time { return h.now }, ClaimTTL: time.Minute}
	if delivered, err := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 0 || err != nil {
		h.t.Fatalf("aggregate gap must block successor: delivered=%d err=%v", delivered, err)
	}
	h.insertOutbox(first, h.now)
	for expected := uint64(1); expected <= 2; expected++ {
		if delivered, err := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 1 || err != nil {
			h.t.Fatalf("dispatch aggregate sequence %d: delivered=%d err=%v", expected, delivered, err)
		}
		if got := publisher.published[len(publisher.published)-1].GetAggregateSequence(); got != expected {
			h.t.Fatalf("published sequence=%d want=%d", got, expected)
		}
	}
}

func (h *reliabilityHarness) runPoisonAndInboxReplay() {
	envelope := h.envelope("inbox-replay")
	encoded, err := pubsubx.MarshalEnvelope(envelope)
	if err != nil {
		h.t.Fatal(err)
	}
	attributes, err := pubsubx.TransportAttributes(envelope)
	if err != nil {
		h.t.Fatal(err)
	}
	orderingKey, err := pubsubx.OrderingKey(envelope)
	if err != nil {
		h.t.Fatal(err)
	}
	const consumer = "reliability-replay-worker"
	poison := inbox.Processor{
		DB: h.db, Consumer: consumer,
		AcceptedEvents: map[string]uint32{envelope.GetEventType(): envelope.GetEventVersion()},
		MaxAttempts:    1, QuarantineTenantID: h.tenant,
		Handler: inbox.TransactionalHandlerFunc(func(context.Context, *sql.Tx, *commonv1.EventEnvelope, proto.Message) error {
			return errors.New("synthetic poison event")
		}),
	}
	if disposition, processErr := poison.ProcessDelivery(h.context(), encoded, attributes, orderingKey); disposition != inbox.DeliveryAck || processErr == nil {
		h.t.Fatalf("poison delivery must be quarantined and acknowledged: disposition=%v err=%v", disposition, processErr)
	}
	id := pubsubx.InboxDeadLetterID(h.tenant, consumer, envelope.GetEventId())
	store := pubsubx.DeadLetterSQLStore{DB: h.db}
	command := pubsubx.ReplayCommand{
		TenantID: h.tenant, DeadLetterID: id, IdempotencyKey: "replay-inbox",
		RequestDigest: digestFor("4"), RequestedBy: "reliability-operator", RequestedAt: h.now,
	}
	requested, err := store.RequestReplay(h.context(), command)
	if err != nil || requested.IdempotentReplay || requested.ReplayGeneration != 1 || requested.DeadLetter.ReplayState != pubsubx.ReplayStatePending {
		h.t.Fatalf("request inbox replay: result=%v err=%v", requested, err)
	}
	if _, err = store.RequestReplay(h.context(), pubsubx.ReplayCommand{TenantID: "another-tenant", DeadLetterID: id, IdempotencyKey: "cross-tenant", RequestDigest: digestFor("5"), RequestedBy: "reliability-operator", RequestedAt: h.now}); !errors.Is(err, pubsubx.ErrDeadLetterNotFound) {
		h.t.Fatalf("cross-tenant replay lookup must fail closed: %v", err)
	}
	publisher := &recordingPublisher{}
	replayAt := h.now
	ackStore := &failingReplayAcknowledgeStore{delegate: store, remaining: 1}
	replayer := pubsubx.ReplayDispatcher{Store: ackStore, Publisher: publisher, Now: func() time.Time { return replayAt }, ClaimTTL: time.Second}
	if published, replayErr := replayer.DeliverBatch(h.context(), h.tenant, 1); published != 0 || replayErr == nil || len(publisher.published) != 1 {
		h.t.Fatalf("crash before replay acknowledgement: published=%d events=%d err=%v", published, len(publisher.published), replayErr)
	}
	replayAt = h.now.Add(2 * time.Second)
	if published, replayErr := replayer.DeliverBatch(h.context(), h.tenant, 1); published != 1 || replayErr != nil || len(publisher.published) != 2 {
		h.t.Fatalf("recover expired replay claim: published=%d events=%d err=%v", published, len(publisher.published), replayErr)
	}
	if !proto.Equal(publisher.published[0], publisher.published[1]) {
		h.t.Fatal("replay crash recovery must republish the same immutable envelope")
	}
	calls := 0
	success := inbox.Processor{
		DB: h.db, Consumer: consumer,
		AcceptedEvents: map[string]uint32{envelope.GetEventType(): envelope.GetEventVersion()},
		MaxAttempts:    1, QuarantineTenantID: h.tenant,
		Handler: inbox.TransactionalHandlerFunc(func(context.Context, *sql.Tx, *commonv1.EventEnvelope, proto.Message) error {
			calls++
			return nil
		}),
	}
	if disposition, processErr := success.ProcessDelivery(h.context(), encoded, attributes, orderingKey); disposition != inbox.DeliveryAck || processErr != nil {
		h.t.Fatalf("consume inbox replay: disposition=%v err=%v", disposition, processErr)
	}
	if disposition, processErr := success.ProcessDelivery(h.context(), encoded, attributes, orderingKey); disposition != inbox.DeliveryAck || processErr != nil || calls != 1 {
		h.t.Fatalf("replayed duplicate must be deduplicated: disposition=%v calls=%d err=%v", disposition, calls, processErr)
	}
	var state pubsubx.ReplayState
	if err = h.db.QueryRowContext(h.context(), `SELECT replay_state FROM dead_letter_messages WHERE tenant_id=$1 AND id=$2`, h.tenant, id).Scan(&state); err != nil || state != pubsubx.ReplayStateReplayed {
		h.t.Fatalf("terminal inbox replay state=%s err=%v", state, err)
	}
	if repeated, replayErr := store.RequestReplay(h.context(), command); replayErr != nil || !repeated.IdempotentReplay || repeated.ReplayGeneration != 1 {
		h.t.Fatalf("idempotent replay request: result=%v err=%v", repeated, replayErr)
	}
	changed := command
	changed.RequestDigest = digestFor("6")
	if _, replayErr := store.RequestReplay(h.context(), changed); !errors.Is(replayErr, pubsubx.ErrReplayConflict) {
		h.t.Fatalf("changed replay request must conflict: %v", replayErr)
	}
	command.IdempotencyKey = "replay-inbox-again"
	if _, replayErr := store.RequestReplay(h.context(), command); !errors.Is(replayErr, pubsubx.ErrAlreadyReplayed) {
		h.t.Fatalf("new replay after terminal success must be rejected: %v", replayErr)
	}
}

func (h *reliabilityHarness) runOutboxQuarantineReplay() {
	envelope := h.envelope("outbox-replay")
	h.insertOutbox(envelope, h.now)
	store := outbox.SQLStore{DB: h.db}
	failing := outbox.Dispatcher{
		Store: store, Publisher: &recordingPublisher{failures: 1}, Now: func() time.Time { return h.now },
		ClaimTTL: time.Minute, MaxAttempts: 1,
	}
	if delivered, err := failing.DeliverBatch(h.context(), h.tenant, 1); delivered != 0 || err == nil {
		h.t.Fatalf("exhausted outbox delivery must quarantine: delivered=%d err=%v", delivered, err)
	}
	replayStore := pubsubx.DeadLetterSQLStore{DB: h.db}
	command := pubsubx.ReplayCommand{
		TenantID: h.tenant, DeadLetterID: "outbox:" + envelope.GetEventId(), IdempotencyKey: "replay-outbox",
		RequestDigest: digestFor("7"), RequestedBy: "reliability-operator", RequestedAt: h.now.Add(time.Second),
	}
	if result, err := replayStore.RequestReplay(h.context(), command); err != nil || result.IdempotentReplay || result.ReplayGeneration != 1 || result.DeadLetter.ReplayState != pubsubx.ReplayStatePending {
		h.t.Fatalf("request outbox replay: result=%v err=%v", result, err)
	}
	publisher := &recordingPublisher{}
	replayedAt := h.now.Add(2 * time.Second)
	dispatcher := outbox.Dispatcher{Store: store, Publisher: publisher, Now: func() time.Time { return replayedAt }, ClaimTTL: time.Minute}
	if delivered, err := dispatcher.DeliverBatch(h.context(), h.tenant, 1); delivered != 1 || err != nil || len(publisher.published) != 1 {
		h.t.Fatalf("deliver outbox replay: delivered=%d published=%d err=%v", delivered, len(publisher.published), err)
	}
	var state pubsubx.ReplayState
	if err := h.db.QueryRowContext(h.context(), `SELECT replay_state FROM dead_letter_messages WHERE tenant_id=$1 AND id=$2`, h.tenant, command.DeadLetterID).Scan(&state); err != nil || state != pubsubx.ReplayStateReplayed {
		h.t.Fatalf("terminal outbox replay state=%s err=%v", state, err)
	}
}

func (h *reliabilityHarness) runExpiredFence() {
	repository, lease := h.leasedRun("expired-fence")
	requested := proto.Clone(lease.Attempt).(*jobv1.Attempt)
	requested.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	at := lease.Attempt.GetLeaseExpiresAt().AsTime().Add(time.Nanosecond)
	_, err := repository.CompleteAttemptSQL(h.context(), jobs.CompleteAttemptCommand{
		Credentials: jobs.LeaseCredentials{
			TenantID: h.tenant, ProjectID: h.project, AttemptID: lease.Attempt.GetAttemptId(),
			WorkerID: lease.Attempt.GetWorkerId(), Token: lease.token, Epoch: lease.Attempt.GetLeaseEpoch(),
		},
		Attempt: requested, UpdateMask: []string{"state"}, ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Now: at,
		Command: h.runCommand("run.commit_attempt", "expired-completion", lease.Attempt.GetWorkerId(), "8", at),
	})
	if !errors.Is(err, jobs.ErrLeaseExpired) {
		h.t.Fatalf("expired fence completion error=%v", err)
	}
	var accepted bool
	if queryErr := h.db.QueryRowContext(h.context(), `SELECT accepted FROM attempt_completion_history WHERE tenant_id=$1 AND project_id=$2 AND attempt_id=$3 ORDER BY recorded_at DESC LIMIT 1`, h.tenant, h.project, lease.Attempt.GetAttemptId()).Scan(&accepted); queryErr != nil || accepted {
		h.t.Fatalf("expired completion evidence accepted=%v err=%v", accepted, queryErr)
	}
}

func (h *reliabilityHarness) runLeaseExpiryDelivery() {
	repository, lease := h.leasedRun("lease-expiry-delivery")
	expiredAt := lease.Attempt.GetLeaseExpiresAt().AsTime().Add(time.Nanosecond)
	command := h.runCommand("run.expire_leases", "expire-leases", "scheduler-expiry", "f", expiredAt)
	expired, err := repository.ExpireLeasesSQL(h.context(), jobs.ExpireLeasesCommand{
		TenantID: h.tenant, Limit: 10, Now: expiredAt, Command: command,
	})
	if err != nil || expired.Replay || len(expired.Attempts) != 1 {
		h.t.Fatalf("expire current lease: result=%v err=%v", expired, err)
	}
	attempt := expired.Attempts[0]
	run, err := repository.GetRunSQL(h.context(), h.tenant, h.project, attempt.GetRunId())
	if err != nil {
		h.t.Fatal(err)
	}
	if attempt.GetState() != jobv1.AttemptState_ATTEMPT_STATE_TIMED_OUT ||
		run.GetState() != jobv1.RunState_RUN_STATE_READY {
		h.t.Fatalf("expired lease state was incomplete: attempt=%v run=%v", attempt, run)
	}
	replayed, err := repository.ExpireLeasesSQL(h.context(), jobs.ExpireLeasesCommand{
		TenantID: h.tenant, Limit: 10, Now: expiredAt, Command: command,
	})
	if err != nil || !replayed.Replay || len(replayed.Attempts) != 1 || !proto.Equal(replayed.Attempts[0], attempt) {
		h.t.Fatalf("expiry replay changed durable result: result=%v err=%v", replayed, err)
	}

	publisher := &recordingPublisher{}
	dispatcher := outbox.Dispatcher{
		Store: outbox.SQLStore{DB: h.db}, Publisher: publisher,
		Now: func() time.Time { return expiredAt.Add(time.Second) }, ClaimTTL: time.Minute,
	}
	for expected := uint64(1); expected <= 2; expected++ {
		if delivered, dispatchErr := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 1 || dispatchErr != nil {
			h.t.Fatalf("dispatch expiry lifecycle sequence %d: delivered=%d err=%v", expected, delivered, dispatchErr)
		}
		envelope := publisher.published[len(publisher.published)-1]
		if envelope.GetAggregateSequence() != expected {
			h.t.Fatalf("expiry lifecycle sequence=%d want=%d", envelope.GetAggregateSequence(), expected)
		}
		if expected == 2 {
			payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
			fact, ok := payload.(*jobv1.AttemptCompleted)
			if decodeErr != nil || !ok || !proto.Equal(fact.GetAttempt(), attempt) || fact.GetRun().GetState() != jobv1.RunState_RUN_STATE_READY {
				h.t.Fatalf("invalid delivered expiry fact: payload=%T %v err=%v", payload, payload, decodeErr)
			}
		}
	}
}

func (h *reliabilityHarness) runAttemptCancellationDelivery() {
	repository, lease := h.leasedRun("attempt-cancellation-delivery")
	cancelledAt := h.now.Add(time.Second)
	reason := "operator requested bounded shutdown"
	command := h.runCommand("run.cancel_attempt", "cancel-attempt", lease.Attempt.GetWorkerId(), "1", cancelledAt)
	cancelled, err := repository.CancelAttemptSQL(h.context(), jobs.CancelAttemptCommand{
		Credentials: jobs.LeaseCredentials{
			TenantID: h.tenant, ProjectID: h.project, AttemptID: lease.Attempt.GetAttemptId(),
			WorkerID: lease.Attempt.GetWorkerId(), Token: lease.token, Epoch: lease.Attempt.GetLeaseEpoch(),
		},
		ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Reason: reason, Now: cancelledAt, Command: command,
	})
	if err != nil || cancelled.Replay {
		h.t.Fatalf("cancel current attempt: result=%v err=%v", cancelled, err)
	}
	if cancelled.Attempt.GetState() != jobv1.AttemptState_ATTEMPT_STATE_CANCELLED ||
		cancelled.Run.GetState() != jobv1.RunState_RUN_STATE_CANCELLED ||
		cancelled.Attempt.GetError().GetCode() != commonv1.ErrorCode_ERROR_CODE_CANCELLED ||
		cancelled.Attempt.GetError().GetMessage() != reason || !proto.Equal(cancelled.Attempt.GetError(), cancelled.Run.GetError()) {
		h.t.Fatalf("cancellation reason was not preserved in terminal resources: %v", cancelled)
	}
	replayed, err := repository.CancelAttemptSQL(h.context(), jobs.CancelAttemptCommand{
		Credentials: jobs.LeaseCredentials{
			TenantID: h.tenant, ProjectID: h.project, AttemptID: lease.Attempt.GetAttemptId(),
			WorkerID: lease.Attempt.GetWorkerId(), Token: lease.token, Epoch: lease.Attempt.GetLeaseEpoch(),
		},
		ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Reason: reason, Now: cancelledAt, Command: command,
	})
	if err != nil || !replayed.Replay || !proto.Equal(replayed.Attempt, cancelled.Attempt) || !proto.Equal(replayed.Run, cancelled.Run) {
		h.t.Fatalf("cancellation replay changed durable result: result=%v err=%v", replayed, err)
	}

	publisher := &recordingPublisher{}
	dispatcher := outbox.Dispatcher{
		Store: outbox.SQLStore{DB: h.db}, Publisher: publisher,
		Now: func() time.Time { return cancelledAt.Add(time.Second) }, ClaimTTL: time.Minute,
	}
	for expected := uint64(1); expected <= 2; expected++ {
		if delivered, dispatchErr := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 1 || dispatchErr != nil {
			h.t.Fatalf("dispatch cancellation lifecycle sequence %d: delivered=%d err=%v", expected, delivered, dispatchErr)
		}
		envelope := publisher.published[len(publisher.published)-1]
		if envelope.GetAggregateSequence() != expected {
			h.t.Fatalf("cancellation lifecycle sequence=%d want=%d", envelope.GetAggregateSequence(), expected)
		}
		if expected == 2 {
			payload, decodeErr := pubsubx.UnmarshalRegisteredPayload(envelope)
			fact, ok := payload.(*jobv1.AttemptCompleted)
			if decodeErr != nil || !ok || fact.GetAttempt().GetError().GetMessage() != reason || !proto.Equal(fact.GetAttempt(), cancelled.Attempt) || !proto.Equal(fact.GetRun(), cancelled.Run) {
				h.t.Fatalf("invalid delivered cancellation fact: payload=%T %v err=%v", payload, payload, decodeErr)
			}
		}
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 0 || dispatchErr != nil {
		h.t.Fatalf("idempotent cancellation replay emitted another event: delivered=%d err=%v", delivered, dispatchErr)
	}
}

func (h *reliabilityHarness) runHeartbeatThenCompletionDelivery() {
	repository, lease := h.leasedRun("heartbeat-completion")
	credentials := jobs.LeaseCredentials{
		TenantID: h.tenant, ProjectID: h.project, AttemptID: lease.Attempt.GetAttemptId(),
		WorkerID: lease.Attempt.GetWorkerId(), Token: lease.token, Epoch: lease.Attempt.GetLeaseEpoch(),
	}
	heartbeatAt := h.now.Add(time.Second)
	heartbeat, err := repository.HeartbeatLeaseSQL(h.context(), jobs.RenewLeaseCommand{
		Credentials: credentials, ExpectedResourceVersion: lease.Attempt.GetResourceVersion(),
		Duration: jobs.MinimumLeaseDuration, Now: heartbeatAt,
		Command: h.runCommand("run.heartbeat", "heartbeat-before-completion", lease.Attempt.GetWorkerId(), "d", heartbeatAt),
	})
	if err != nil {
		h.t.Fatalf("heartbeat reliability lease: %v", err)
	}
	requested := proto.Clone(heartbeat.Attempt).(*jobv1.Attempt)
	requested.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	completedAt := heartbeatAt.Add(time.Second)
	completed, err := repository.CompleteAttemptSQL(h.context(), jobs.CompleteAttemptCommand{
		Credentials: credentials, Attempt: requested, UpdateMask: []string{"state"},
		ExpectedResourceVersion: heartbeat.Attempt.GetResourceVersion(), Now: completedAt,
		Command: h.runCommand("run.commit_attempt", "complete-after-heartbeat", lease.Attempt.GetWorkerId(), "e", completedAt),
	})
	if err != nil {
		h.t.Fatalf("complete heartbeat-renewed attempt: %v", err)
	}
	if completed.Attempt.GetResourceVersion() <= 2 {
		h.t.Fatalf("heartbeat and completion did not advance authoritative revision: %d", completed.Attempt.GetResourceVersion())
	}

	publisher := &recordingPublisher{}
	dispatcher := outbox.Dispatcher{
		Store: outbox.SQLStore{DB: h.db}, Publisher: publisher,
		Now: func() time.Time { return completedAt.Add(time.Second) }, ClaimTTL: time.Minute,
	}
	for expected := uint64(1); expected <= 2; expected++ {
		if delivered, dispatchErr := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 1 || dispatchErr != nil {
			h.t.Fatalf("dispatch heartbeat/completion sequence %d: delivered=%d err=%v", expected, delivered, dispatchErr)
		}
		published := publisher.published[len(publisher.published)-1]
		if published.GetAggregateSequence() != expected {
			h.t.Fatalf("heartbeat/completion sequence=%d want=%d", published.GetAggregateSequence(), expected)
		}
		if expected == 2 && published.GetSubject().GetResourceVersion() != completed.Attempt.GetResourceVersion() {
			h.t.Fatalf("completion lost resource revision: subject=%d attempt=%d", published.GetSubject().GetResourceVersion(), completed.Attempt.GetResourceVersion())
		}
	}
}

func (h *reliabilityHarness) runJobCancellationDelivery() {
	repository := jobs.SQLRepository{DB: h.db}
	configuration := &artifactv1.ArtifactRef{
		Digest: digestFor("d"), IntegrityDigest: digestFor("d"), MediaType: "application/json",
		SizeBytes: 1, ArtifactKind: "configuration", SchemaId: "reliability", SchemaVersion: "1",
	}
	jobID := "job-cancellation-delivery"
	operationID := "operation-cancellation-delivery"
	requested, err := repository.RequestJobSQL(h.context(), &jobv1.Job{
		JobId: jobID, TenantId: h.tenant, ProjectId: h.project,
		Configuration: configuration, Etag: "job-etag-1",
	}, &jobv1.Operation{
		OperationId: operationID, TenantId: h.tenant, ProjectId: h.project,
		JobId: jobID, Etag: "operation-etag-1",
	}, jobs.JobCommandMetadata{
		TenantID: h.tenant, ProjectID: h.project, PrincipalID: "reliability-principal",
		IdempotencyKey: "request-cancellation-delivery", RequestDigest: digestFor("e"), ObservedAt: h.now,
	})
	if err != nil || requested.Replay {
		h.t.Fatalf("request cancellation-delivery job: result=%v err=%v", requested, err)
	}
	cancelCommand := jobs.JobCommandMetadata{
		TenantID: h.tenant, ProjectID: h.project, PrincipalID: "reliability-principal",
		IdempotencyKey: "cancel-cancellation-delivery", RequestDigest: digestFor("f"), ObservedAt: h.now.Add(time.Second),
	}
	cancelled, err := repository.CancelJobSQL(h.context(), requested.Job.GetJobId(), requested.Job.GetEtag(), "operator request", cancelCommand)
	if err != nil || cancelled.Replay {
		h.t.Fatalf("cancel job: result=%v err=%v", cancelled, err)
	}

	publisher := &recordingPublisher{}
	dispatcher := outbox.Dispatcher{
		Store: outbox.SQLStore{DB: h.db}, Publisher: publisher,
		Now: func() time.Time { return h.now.Add(2 * time.Second) }, ClaimTTL: time.Minute,
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 2 || dispatchErr != nil {
		h.t.Fatalf("dispatch job request and cancellation audit: delivered=%d err=%v", delivered, dispatchErr)
	}
	eventTypes := map[string]int{}
	for _, envelope := range publisher.published {
		eventTypes[envelope.GetEventType()]++
		if envelope.GetEventType() != "mindclade.events.audit.v1.AuditEvent" {
			continue
		}
		if envelope.GetAggregateSequence() != 1 || envelope.GetSubject().GetResourceVersion() != cancelled.Job.GetResourceVersion() ||
			envelope.GetSubject().GetResourceType() != "job_cancellation_audit" {
			h.t.Fatalf("cancellation audit was not a deliverable standalone aggregate: %v", envelope)
		}
	}
	if eventTypes["mindclade.events.job.v1.JobRequested"] != 1 || eventTypes["mindclade.events.audit.v1.AuditEvent"] != 1 {
		h.t.Fatalf("published event types=%v", eventTypes)
	}
	replayed, err := repository.CancelJobSQL(h.context(), requested.Job.GetJobId(), requested.Job.GetEtag(), "operator request", cancelCommand)
	if err != nil || !replayed.Replay {
		h.t.Fatalf("replay exact cancellation: result=%v err=%v", replayed, err)
	}
	if delivered, dispatchErr := dispatcher.DeliverBatch(h.context(), h.tenant, 10); delivered != 0 || dispatchErr != nil {
		h.t.Fatalf("idempotent replay emitted another event: delivered=%d err=%v", delivered, dispatchErr)
	}
}

func (h *reliabilityHarness) runCancellationRace() {
	repository, lease := h.leasedRun("cancellation-race")
	at := h.now.Add(time.Second)
	credentials := jobs.LeaseCredentials{
		TenantID: h.tenant, ProjectID: h.project, AttemptID: lease.Attempt.GetAttemptId(),
		WorkerID: lease.Attempt.GetWorkerId(), Token: lease.token, Epoch: lease.Attempt.GetLeaseEpoch(),
	}
	requested := proto.Clone(lease.Attempt).(*jobv1.Attempt)
	requested.State = jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED
	start := make(chan struct{})
	results := make(chan error, 2)
	var wait sync.WaitGroup
	wait.Add(2)
	go func() {
		defer wait.Done()
		<-start
		_, err := repository.CancelAttemptSQL(h.context(), jobs.CancelAttemptCommand{
			Credentials: credentials, ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Now: at,
			Command: h.runCommand("run.cancel_attempt", "race-cancel", lease.Attempt.GetWorkerId(), "9", at),
		})
		results <- err
	}()
	go func() {
		defer wait.Done()
		<-start
		_, err := repository.CompleteAttemptSQL(h.context(), jobs.CompleteAttemptCommand{
			Credentials: credentials, Attempt: requested, UpdateMask: []string{"state"},
			ExpectedResourceVersion: lease.Attempt.GetResourceVersion(), Now: at,
			Command: h.runCommand("run.commit_attempt", "race-complete", lease.Attempt.GetWorkerId(), "a", at),
		})
		results <- err
	}()
	close(start)
	wait.Wait()
	close(results)
	successes := 0
	for err := range results {
		if err == nil {
			successes++
			continue
		}
		if !errors.Is(err, jobs.ErrTerminalMutation) && !errors.Is(err, jobs.ErrStaleCompletion) && !errors.Is(err, jobs.ErrVersionConflict) {
			h.t.Fatalf("unexpected cancellation-race loser: %v", err)
		}
	}
	if successes != 1 {
		h.t.Fatalf("cancellation race winners=%d want=1", successes)
	}
	run, err := repository.GetRunSQL(h.context(), h.tenant, h.project, lease.Attempt.GetRunId())
	if err != nil {
		h.t.Fatal(err)
	}
	attempt, err := repository.GetAttemptSQL(h.context(), h.tenant, h.project, lease.Attempt.GetAttemptId())
	if err != nil {
		h.t.Fatal(err)
	}
	coherent := (run.GetState() == jobv1.RunState_RUN_STATE_CANCELLED && attempt.GetState() == jobv1.AttemptState_ATTEMPT_STATE_CANCELLED) ||
		(run.GetState() == jobv1.RunState_RUN_STATE_SUCCEEDED && attempt.GetState() == jobv1.AttemptState_ATTEMPT_STATE_SUCCEEDED)
	if !coherent {
		h.t.Fatalf("cancellation race produced incoherent run=%s attempt=%s", run.GetState(), attempt.GetState())
	}
}

type leasedAttempt struct {
	*jobs.LeaseMutationResult
	token string
}

func (h *reliabilityHarness) leasedRun(id string) (jobs.SQLRepository, leasedAttempt) {
	h.t.Helper()
	repository := jobs.SQLRepository{DB: h.db}
	configuration := &artifactv1.ArtifactRef{
		Digest: digestFor("b"), IntegrityDigest: digestFor("b"), MediaType: "application/json",
		SizeBytes: 1, ArtifactKind: "configuration", SchemaId: "reliability", SchemaVersion: "1",
	}
	jobID, runID := "job-"+id, "run-"+id
	if _, err := repository.CreateJobSQL(h.context(), &jobv1.Job{JobId: jobID, TenantId: h.tenant, ProjectId: h.project, Configuration: configuration, Etag: "job-etag-1"}); err != nil {
		h.t.Fatalf("create reliability job: %v", err)
	}
	if _, err := repository.CreateRunSQL(h.context(), &jobv1.Run{RunId: runID, JobId: jobID, TenantId: h.tenant, ProjectId: h.project, Configuration: configuration, Etag: "run-etag-1"}); err != nil {
		h.t.Fatalf("create reliability run: %v", err)
	}
	token := "reliability-lease-token-" + strings.Repeat("x", 32)
	worker := "worker-" + id
	lease, err := repository.AcquireLeaseSQL(h.context(), jobs.AcquireLeaseCommand{
		TenantID: h.tenant, RunID: runID, AttemptID: "attempt-" + id, WorkerID: worker,
		Token: token, TokenKeyID: "reliability-key", Duration: jobs.MinimumLeaseDuration, Now: h.now,
		Command: h.runCommand("run.acquire_lease", "acquire-"+id, worker, "c", h.now),
	})
	if err != nil {
		h.t.Fatalf("acquire reliability lease: %v", err)
	}
	return repository, leasedAttempt{LeaseMutationResult: lease, token: token}
}

func (h *reliabilityHarness) runCommand(action, key, worker, digestSeed string, at time.Time) jobs.RunCommandMetadata {
	return jobs.RunCommandMetadata{
		TenantID: h.tenant, ProjectID: h.project, PrincipalID: "reliability-principal", WorkerID: worker,
		Action: action, IdempotencyKey: key, RequestDigest: digestFor(digestSeed), ObservedAt: at,
	}
}

type failingAcknowledgeStore struct {
	delegate  outbox.DeliveryStore
	remaining int
}

type failingReplayAcknowledgeStore struct {
	delegate  pubsubx.DeadLetterReplayStore
	remaining int
}

func (s *failingReplayAcknowledgeStore) ClaimInboxReplays(ctx context.Context, tenantID string, limit int, now time.Time, ttl time.Duration) ([]pubsubx.DeadLetter, error) {
	return s.delegate.ClaimInboxReplays(ctx, tenantID, limit, now, ttl)
}

func (s *failingReplayAcknowledgeStore) AcknowledgeInboxPublished(ctx context.Context, tenantID, id string, epoch uint64, at time.Time) (bool, error) {
	if s.remaining > 0 {
		s.remaining--
		return false, errors.New("synthetic crash before replay acknowledgement")
	}
	return s.delegate.AcknowledgeInboxPublished(ctx, tenantID, id, epoch, at)
}

func (s *failingReplayAcknowledgeStore) RetryInboxReplay(ctx context.Context, tenantID, id string, epoch uint64, next time.Time, cause error) (bool, error) {
	return s.delegate.RetryInboxReplay(ctx, tenantID, id, epoch, next, cause)
}

func (s *failingReplayAcknowledgeStore) QuarantineInboxReplay(ctx context.Context, tenantID, id string, epoch uint64, at time.Time, cause error) (bool, error) {
	return s.delegate.QuarantineInboxReplay(ctx, tenantID, id, epoch, at, cause)
}

func (s *failingAcknowledgeStore) Claim(ctx context.Context, tenantID string, limit int, now time.Time, ttl time.Duration) ([]outbox.DeliveryRecord, error) {
	return s.delegate.Claim(ctx, tenantID, limit, now, ttl)
}

func (s *failingAcknowledgeStore) Acknowledge(ctx context.Context, tenantID, id string, epoch uint64, at time.Time) (bool, error) {
	if s.remaining > 0 {
		s.remaining--
		return false, errors.New("synthetic crash before outbox acknowledgement")
	}
	return s.delegate.Acknowledge(ctx, tenantID, id, epoch, at)
}

func (s *failingAcknowledgeStore) Retry(ctx context.Context, tenantID, id string, epoch uint64, next time.Time, cause error) (bool, error) {
	return s.delegate.Retry(ctx, tenantID, id, epoch, next, cause)
}

func (s *failingAcknowledgeStore) Quarantine(ctx context.Context, tenantID, id string, epoch uint64, at time.Time, cause error) (bool, error) {
	return s.delegate.Quarantine(ctx, tenantID, id, epoch, at, cause)
}

func digestFor(seed string) string {
	return "sha256:" + strings.Repeat(seed, 64)
}

func TestPostgresReliabilityHarness(t *testing.T) {
	db := postgresDB(t)
	if db == nil {
		t.Skip("PostgreSQL reliability harness requires MINDCLADE_TEST_POSTGRES_DSN")
	}
	tests := []struct {
		name string
		run  func(*reliabilityHarness)
	}{
		{name: "publish-before-ack crash", run: (*reliabilityHarness).runPublishBeforeAckCrash},
		{name: "duplicate delivery and inbox rollback", run: (*reliabilityHarness).runDuplicateAndInboxRollback},
		{name: "reordered events and sequence gap", run: (*reliabilityHarness).runReorderedSequenceGap},
		{name: "poison event and inbox DLQ replay", run: (*reliabilityHarness).runPoisonAndInboxReplay},
		{name: "outbox quarantine and DLQ replay", run: (*reliabilityHarness).runOutboxQuarantineReplay},
		{name: "heartbeat then completion delivery", run: (*reliabilityHarness).runHeartbeatThenCompletionDelivery},
		{name: "job cancellation audit delivery", run: (*reliabilityHarness).runJobCancellationDelivery},
		{name: "expired fence", run: (*reliabilityHarness).runExpiredFence},
		{name: "lease expiry event delivery", run: (*reliabilityHarness).runLeaseExpiryDelivery},
		{name: "attempt cancellation event delivery", run: (*reliabilityHarness).runAttemptCancellationDelivery},
		{name: "cancellation race", run: (*reliabilityHarness).runCancellationRace},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			test.run(newReliabilityHarness(t, db, strings.ReplaceAll(test.name, " ", "-")))
		})
	}
}
