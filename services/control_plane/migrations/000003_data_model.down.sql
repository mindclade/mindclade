BEGIN;

DO $$
DECLARE
  table_name text;
  contains_rows boolean;
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'data/model down migration requires explicit local-empty authorization';
  END IF;
  FOREACH table_name IN ARRAY ARRAY[
    'datasets','dataset_labels','dataset_annotations','dataset_releases',
    'dataset_release_qualification_evidence','dataset_release_revocation_evidence',
    'models','model_labels','model_annotations','model_releases',
    'model_release_evaluation_evidence','model_release_transition_evidence',
    'data_model_command_receipts'
  ] LOOP
    EXECUTE format('LOCK TABLE %I IN ACCESS EXCLUSIVE MODE', table_name);
    EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I)', table_name) INTO contains_rows;
    IF contains_rows THEN
      RAISE EXCEPTION 'data/model down migration refuses non-empty durable table %', table_name;
    END IF;
  END LOOP;
END $$;

DROP TABLE IF EXISTS data_model_command_receipts;
DROP TABLE IF EXISTS model_release_transition_evidence;
DROP TABLE IF EXISTS model_release_evaluation_evidence;
DROP TRIGGER IF EXISTS model_release_immutable ON model_releases;
DROP FUNCTION IF EXISTS guard_model_release_immutable();
DROP TABLE IF EXISTS model_releases;
DROP TABLE IF EXISTS model_annotations;
DROP TABLE IF EXISTS model_labels;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS dataset_release_revocation_evidence;
DROP TABLE IF EXISTS dataset_release_qualification_evidence;
DROP TRIGGER IF EXISTS dataset_release_immutable ON dataset_releases;
DROP FUNCTION IF EXISTS guard_dataset_release_immutable();
DROP TABLE IF EXISTS dataset_releases;
DROP TABLE IF EXISTS dataset_annotations;
DROP TABLE IF EXISTS dataset_labels;
DROP TABLE IF EXISTS datasets;
DROP FUNCTION IF EXISTS reject_immutable_data_model_fact();

COMMIT;
