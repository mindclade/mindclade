BEGIN;

DO $$
DECLARE
  table_name text;
  contains_rows boolean;
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'down migration requires explicit local-empty authorization';
  END IF;
  FOREACH table_name IN ARRAY ARRAY[
    'artifact_references','resource_references','error_details','error_field_violations',
    'error_precondition_violations','jobs','operations','operation_revisions',
    'training_progress_snapshots','training_runs','training_run_labels','training_checkpoints',
    'runs','run_output_refs','attempts','attempt_output_refs','attempt_completion_history',
    'run_command_receipts','run_command_receipt_attempts','artifacts','idempotency_records',
    'audit_events','outbox_messages','inbox_messages','inbox_delivery_failures','dead_letter_messages'
  ] LOOP
    EXECUTE format('LOCK TABLE %I IN ACCESS EXCLUSIVE MODE', table_name);
    -- FORCE RLS applies to a table owner. Disable it only inside this
    -- transaction so the emptiness proof cannot mistake hidden rows for an
    -- empty database; any exception rolls this DDL back atomically.
    EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I)', table_name) INTO contains_rows;
    IF contains_rows THEN
      RAISE EXCEPTION 'down migration refuses non-empty durable table %', table_name;
    END IF;
  END LOOP;
END $$;

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
