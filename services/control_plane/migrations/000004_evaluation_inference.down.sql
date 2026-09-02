BEGIN;

DO $$
DECLARE
  table_name text;
  contains_rows boolean;
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'evaluation/inference down migration requires explicit local-empty authorization';
  END IF;
  FOREACH table_name IN ARRAY ARRAY[
    'policy_snapshot_references','authorization_decisions','authorization_decision_policies',
    'authorization_decision_constraints','evaluation_runs','evaluation_run_datasets',
    'evaluation_run_policies','evaluation_results','evaluation_result_metrics',
    'evaluation_result_thresholds','evaluation_result_failure_counts','promotion_decisions',
    'promotion_decision_results','promotion_decision_rules','promotion_decision_exceptions',
    'promotion_exception_approvals','promotion_decision_authorizations','inference_requests',
    'inference_request_output_kinds','inference_request_policies','inference_results',
    'inference_result_candidates','inference_result_authorizations',
    'evaluation_inference_command_receipts'
  ] LOOP
    EXECUTE format('LOCK TABLE %I IN ACCESS EXCLUSIVE MODE', table_name);
    EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I)', table_name) INTO contains_rows;
    IF contains_rows THEN
      RAISE EXCEPTION 'evaluation/inference down migration refuses non-empty durable table %', table_name;
    END IF;
  END LOOP;
END $$;

DROP TABLE IF EXISTS evaluation_inference_command_receipts;
DROP TABLE IF EXISTS inference_result_authorizations;
DROP TABLE IF EXISTS inference_result_candidates;
DROP TABLE IF EXISTS inference_results;
DROP TABLE IF EXISTS inference_request_policies;
DROP TABLE IF EXISTS inference_request_output_kinds;
DROP TABLE IF EXISTS inference_requests;
DROP TABLE IF EXISTS promotion_decision_authorizations;
DROP TABLE IF EXISTS promotion_exception_approvals;
DROP TABLE IF EXISTS promotion_decision_exceptions;
DROP TABLE IF EXISTS promotion_decision_rules;
DROP TABLE IF EXISTS promotion_decision_results;
DROP TABLE IF EXISTS promotion_decisions;
DROP TABLE IF EXISTS evaluation_result_failure_counts;
DROP TABLE IF EXISTS evaluation_result_thresholds;
DROP TABLE IF EXISTS evaluation_result_metrics;
DROP TABLE IF EXISTS evaluation_results;
DROP TABLE IF EXISTS evaluation_run_policies;
DROP TABLE IF EXISTS evaluation_run_datasets;
DROP TABLE IF EXISTS evaluation_runs;
DROP TABLE IF EXISTS authorization_decision_constraints;
DROP TABLE IF EXISTS authorization_decision_policies;
DROP TABLE IF EXISTS authorization_decisions;
DROP TABLE IF EXISTS policy_snapshot_references;
DROP FUNCTION IF EXISTS reject_immutable_scientific_update();

COMMIT;
