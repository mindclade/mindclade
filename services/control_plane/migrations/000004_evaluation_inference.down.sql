BEGIN;

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
