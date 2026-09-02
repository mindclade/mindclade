BEGIN;

DO $$
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'experiment vertical down migration requires explicit local-empty authorization';
  END IF;
END
$$;

LOCK TABLE
  experiment_command_receipts,
  experiment_trial_evidence,
  experiment_trials,
  experiment_studies,
  experiment_subjects,
  experiment_annotations,
  experiment_labels,
  experiments
IN ACCESS EXCLUSIVE MODE;

-- Migration ownership is required for ALTER TABLE. FORCE is removed only
-- inside this transaction so the owner can prove that no tenant retains
-- mutable state, immutable evidence, or idempotency receipts. Any failure
-- rolls the transaction back and restores FORCE RLS automatically.
ALTER TABLE experiment_command_receipts NO FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_trial_evidence NO FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_trials NO FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_studies NO FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_subjects NO FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_annotations NO FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_labels NO FORCE ROW LEVEL SECURITY;
ALTER TABLE experiments NO FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM experiment_command_receipts)
    OR EXISTS (SELECT 1 FROM experiment_trial_evidence)
    OR EXISTS (SELECT 1 FROM experiment_trials)
    OR EXISTS (SELECT 1 FROM experiment_studies)
    OR EXISTS (SELECT 1 FROM experiment_subjects)
    OR EXISTS (SELECT 1 FROM experiment_annotations)
    OR EXISTS (SELECT 1 FROM experiment_labels)
    OR EXISTS (SELECT 1 FROM experiments) THEN
    RAISE EXCEPTION 'cannot remove experiment vertical while durable state or immutable evidence exists';
  END IF;
END
$$;

DROP TABLE experiment_command_receipts;
DROP TABLE experiment_trial_evidence;
DROP TABLE experiment_trials;
DROP TABLE experiment_studies;
DROP TABLE experiment_subjects;
DROP TABLE experiment_annotations;
DROP TABLE experiment_labels;
DROP TABLE experiments;
DROP FUNCTION reject_experiment_immutable_fact();
DROP FUNCTION guard_experiment_trial_immutable();
DROP FUNCTION guard_experiment_study_immutable();
DROP FUNCTION guard_experiment_inputs_immutable();

COMMIT;
