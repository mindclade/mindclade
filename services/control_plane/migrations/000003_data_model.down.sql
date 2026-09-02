BEGIN;

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
