DO $$
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'down migration requires explicit local-empty authorization';
  END IF;
  IF EXISTS (SELECT 1 FROM operations) OR EXISTS (SELECT 1 FROM operation_revisions) OR EXISTS (SELECT 1 FROM jobs) OR EXISTS (SELECT 1 FROM runs)
    OR EXISTS (SELECT 1 FROM training_runs) OR EXISTS (SELECT 1 FROM training_checkpoints)
    OR EXISTS (SELECT 1 FROM attempts) OR EXISTS (SELECT 1 FROM run_command_receipts)
    OR EXISTS (SELECT 1 FROM artifacts) OR EXISTS (SELECT 1 FROM idempotency_records)
    OR EXISTS (SELECT 1 FROM audit_events) OR EXISTS (SELECT 1 FROM outbox_messages) OR EXISTS (SELECT 1 FROM inbox_messages)
    OR EXISTS (SELECT 1 FROM inbox_delivery_failures)
    OR EXISTS (SELECT 1 FROM dead_letter_messages) THEN
    RAISE EXCEPTION 'down migration refuses non-empty durable tables';
  END IF;
END $$;

BEGIN;
DROP TABLE IF EXISTS dead_letter_messages;
DROP TABLE IF EXISTS inbox_delivery_failures;
DROP TABLE IF EXISTS inbox_messages;
DROP TABLE IF EXISTS outbox_messages;
DROP TABLE IF EXISTS audit_events;
DROP TABLE IF EXISTS idempotency_records;
DROP TABLE IF EXISTS artifacts;
DROP TABLE IF EXISTS training_checkpoints;
DROP TABLE IF EXISTS training_run_labels;
DROP TABLE IF EXISTS training_runs;
DROP TABLE IF EXISTS training_progress_snapshots;
DROP TABLE IF EXISTS run_command_receipt_attempts;
DROP TABLE IF EXISTS run_command_receipts;
DROP TABLE IF EXISTS attempt_completion_history;
DROP TABLE IF EXISTS attempt_output_refs;
DROP TABLE IF EXISTS attempts;
DROP TABLE IF EXISTS run_output_refs;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS operation_revisions;
DROP TABLE IF EXISTS operations;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS error_precondition_violations;
DROP TABLE IF EXISTS error_field_violations;
DROP TABLE IF EXISTS error_details;
DROP TABLE IF EXISTS resource_references;
DROP TABLE IF EXISTS artifact_references;
COMMIT;
