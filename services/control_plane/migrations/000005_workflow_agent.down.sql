BEGIN;

DO $$
DECLARE
  table_name text;
  contains_rows boolean;
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'workflow/agent down migration requires explicit local-empty authorization';
  END IF;
  FOREACH table_name IN ARRAY ARRAY[
    'workflow_definitions','workflow_definition_tools','workflow_definition_policies',
    'workflow_runs','workflow_run_active_nodes','workflow_transition_revisions',
    'workflow_transition_active_nodes','approval_requests','approval_request_input_artifacts',
    'approval_request_policy_decisions','approval_receipts','approval_receipt_input_artifacts',
    'approval_receipt_consumptions','agent_definitions','agent_definition_non_goals',
    'agent_definition_tools','agent_definition_policies','agent_runs','agent_run_policies',
    'agent_steps','agent_step_policy_decisions','agent_step_observations','agent_step_decisions',
    'agent_decision_evidence','agent_tool_calls','agent_tool_call_approvals',
    'agent_tool_call_inputs','agent_tool_receipts','agent_tool_receipt_approvals',
    'agent_tool_receipt_outputs','workflow_agent_command_receipts'
  ] LOOP
    EXECUTE format('LOCK TABLE %I IN ACCESS EXCLUSIVE MODE', table_name);
    EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I)', table_name) INTO contains_rows;
    IF contains_rows THEN
      RAISE EXCEPTION 'workflow/agent down migration refuses non-empty durable table %', table_name;
    END IF;
  END LOOP;
END $$;

DROP TABLE IF EXISTS workflow_agent_command_receipts;
DROP TABLE IF EXISTS agent_tool_receipt_outputs;
DROP TABLE IF EXISTS agent_tool_receipt_approvals;
DROP TABLE IF EXISTS agent_tool_receipts;
DROP TABLE IF EXISTS agent_tool_call_inputs;
DROP TABLE IF EXISTS agent_tool_call_approvals;
DROP TABLE IF EXISTS agent_tool_calls;
DROP TABLE IF EXISTS agent_decision_evidence;
DROP TABLE IF EXISTS agent_step_decisions;
DROP TABLE IF EXISTS agent_step_observations;
DROP TABLE IF EXISTS agent_step_policy_decisions;
DROP TABLE IF EXISTS agent_steps;
DROP TABLE IF EXISTS agent_run_policies;
DROP TABLE IF EXISTS agent_runs;
DROP TABLE IF EXISTS agent_definition_policies;
DROP TABLE IF EXISTS agent_definition_tools;
DROP TABLE IF EXISTS agent_definition_non_goals;
DROP TABLE IF EXISTS agent_definitions;
DROP TABLE IF EXISTS approval_receipt_consumptions;
DROP TABLE IF EXISTS approval_receipt_input_artifacts;
DROP TABLE IF EXISTS approval_receipts;
DROP TABLE IF EXISTS approval_request_policy_decisions;
DROP TABLE IF EXISTS approval_request_input_artifacts;
DROP TABLE IF EXISTS approval_requests;
DROP TABLE IF EXISTS workflow_transition_active_nodes;
DROP TABLE IF EXISTS workflow_transition_revisions;
DROP TABLE IF EXISTS workflow_run_active_nodes;
DROP TABLE IF EXISTS workflow_runs;
DROP TABLE IF EXISTS workflow_definition_policies;
DROP TABLE IF EXISTS workflow_definition_tools;
DROP TABLE IF EXISTS workflow_definitions;
DROP FUNCTION IF EXISTS reject_workflow_agent_immutable_change();

COMMIT;
