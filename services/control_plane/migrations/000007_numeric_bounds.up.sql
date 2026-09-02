BEGIN;

-- Protobuf uint32 values are stored as PostgreSQL bigint so that the complete
-- unsigned range is representable. Preserve that range at rest: readers fail
-- closed as a second line of defense, but invalid persisted state should be
-- rejected before it reaches a mapper.
ALTER TABLE workflow_definitions
  ADD CONSTRAINT chk_workflow_def_max_iterations_u32
  CHECK (maximum_iterations <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_workflow_def_max_fan_out_u32
  CHECK (maximum_fan_out <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_workflow_def_max_parallel_nodes_u32
  CHECK (maximum_parallel_nodes <= 4294967295) NOT VALID;

ALTER TABLE workflow_runs
  ADD CONSTRAINT chk_workflow_run_completed_nodes_u32
  CHECK (completed_node_count <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_workflow_run_iterations_u32
  CHECK (iteration_count <= 4294967295) NOT VALID;

ALTER TABLE workflow_transition_revisions
  ADD CONSTRAINT chk_workflow_rev_completed_nodes_u32
  CHECK (completed_node_count <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_workflow_rev_iterations_u32
  CHECK (iteration_count <= 4294967295) NOT VALID;

ALTER TABLE approval_requests
  ADD CONSTRAINT chk_approval_request_min_approvers_u32
  CHECK (minimum_independent_approvers <= 4294967295) NOT VALID;

ALTER TABLE agent_definitions
  ADD CONSTRAINT chk_agent_def_budget_iterations_u32
  CHECK (budget_maximum_iterations <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_agent_def_budget_tool_calls_u32
  CHECK (budget_maximum_tool_calls <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_agent_def_budget_branches_u32
  CHECK (budget_maximum_concurrent_branches <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_agent_def_limit_depth_u32
  CHECK (limit_maximum_depth <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_agent_def_limit_fan_out_u32
  CHECK (limit_maximum_fan_out <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_agent_def_limit_observations_u32
  CHECK (limit_maximum_observations_per_step <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_agent_def_limit_artifacts_u32
  CHECK (limit_maximum_artifact_references_per_call <= 4294967295) NOT VALID;

ALTER TABLE agent_runs
  ADD CONSTRAINT chk_agent_run_usage_iterations_u32
  CHECK (usage_iterations <= 4294967295) NOT VALID,
  ADD CONSTRAINT chk_agent_run_usage_tool_calls_u32
  CHECK (usage_tool_calls <= 4294967295) NOT VALID;

ALTER TABLE workflow_definitions
  VALIDATE CONSTRAINT chk_workflow_def_max_iterations_u32,
  VALIDATE CONSTRAINT chk_workflow_def_max_fan_out_u32,
  VALIDATE CONSTRAINT chk_workflow_def_max_parallel_nodes_u32;

ALTER TABLE workflow_runs
  VALIDATE CONSTRAINT chk_workflow_run_completed_nodes_u32,
  VALIDATE CONSTRAINT chk_workflow_run_iterations_u32;

ALTER TABLE workflow_transition_revisions
  VALIDATE CONSTRAINT chk_workflow_rev_completed_nodes_u32,
  VALIDATE CONSTRAINT chk_workflow_rev_iterations_u32;

ALTER TABLE approval_requests
  VALIDATE CONSTRAINT chk_approval_request_min_approvers_u32;

ALTER TABLE agent_definitions
  VALIDATE CONSTRAINT chk_agent_def_budget_iterations_u32,
  VALIDATE CONSTRAINT chk_agent_def_budget_tool_calls_u32,
  VALIDATE CONSTRAINT chk_agent_def_budget_branches_u32,
  VALIDATE CONSTRAINT chk_agent_def_limit_depth_u32,
  VALIDATE CONSTRAINT chk_agent_def_limit_fan_out_u32,
  VALIDATE CONSTRAINT chk_agent_def_limit_observations_u32,
  VALIDATE CONSTRAINT chk_agent_def_limit_artifacts_u32;

ALTER TABLE agent_runs
  VALIDATE CONSTRAINT chk_agent_run_usage_iterations_u32,
  VALIDATE CONSTRAINT chk_agent_run_usage_tool_calls_u32;

COMMIT;
