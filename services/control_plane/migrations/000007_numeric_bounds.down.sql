BEGIN;

DO $$
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'numeric-bounds down migration requires explicit development/preproduction authorization';
  END IF;
END $$;

ALTER TABLE agent_runs
  DROP CONSTRAINT IF EXISTS chk_agent_run_usage_tool_calls_u32,
  DROP CONSTRAINT IF EXISTS chk_agent_run_usage_iterations_u32;

ALTER TABLE agent_definitions
  DROP CONSTRAINT IF EXISTS chk_agent_def_limit_artifacts_u32,
  DROP CONSTRAINT IF EXISTS chk_agent_def_limit_observations_u32,
  DROP CONSTRAINT IF EXISTS chk_agent_def_limit_fan_out_u32,
  DROP CONSTRAINT IF EXISTS chk_agent_def_limit_depth_u32,
  DROP CONSTRAINT IF EXISTS chk_agent_def_budget_branches_u32,
  DROP CONSTRAINT IF EXISTS chk_agent_def_budget_tool_calls_u32,
  DROP CONSTRAINT IF EXISTS chk_agent_def_budget_iterations_u32;

ALTER TABLE approval_requests
  DROP CONSTRAINT IF EXISTS chk_approval_request_min_approvers_u32;

ALTER TABLE workflow_transition_revisions
  DROP CONSTRAINT IF EXISTS chk_workflow_rev_iterations_u32,
  DROP CONSTRAINT IF EXISTS chk_workflow_rev_completed_nodes_u32;

ALTER TABLE workflow_runs
  DROP CONSTRAINT IF EXISTS chk_workflow_run_iterations_u32,
  DROP CONSTRAINT IF EXISTS chk_workflow_run_completed_nodes_u32;

ALTER TABLE workflow_definitions
  DROP CONSTRAINT IF EXISTS chk_workflow_def_max_parallel_nodes_u32,
  DROP CONSTRAINT IF EXISTS chk_workflow_def_max_fan_out_u32,
  DROP CONSTRAINT IF EXISTS chk_workflow_def_max_iterations_u32;

COMMIT;
