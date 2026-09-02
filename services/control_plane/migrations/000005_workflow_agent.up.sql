BEGIN;

-- Workflow and agent resources are mutable aggregate state and are therefore
-- stored as normalized columns and child rows.  Immutable transition, approval,
-- step, and tool execution evidence is also normalized; only the transactional
-- outbox/audit tables contain serialized protobuf envelopes.

CREATE TABLE workflow_definitions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  display_name text NOT NULL,
  semantic_version text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  definition_ref_id bigint NOT NULL,
  resolved_graph_digest text NOT NULL CHECK (resolved_graph_digest ~ '^sha256:[0-9a-f]{64}$'),
  maximum_iterations bigint NOT NULL CHECK (maximum_iterations > 0),
  maximum_fan_out bigint NOT NULL CHECK (maximum_fan_out > 0),
  maximum_parallel_nodes bigint NOT NULL CHECK (maximum_parallel_nodes > 0),
  maximum_wall_time_seconds bigint NOT NULL CHECK (maximum_wall_time_seconds >= 0),
  maximum_wall_time_nanos integer NOT NULL CHECK (maximum_wall_time_nanos BETWEEN 0 AND 999999999),
  input_schema_ref_id bigint,
  output_schema_ref_id bigint,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  delete_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  FOREIGN KEY (tenant_id, definition_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, input_schema_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, output_schema_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND display_name <> '' AND semantic_version <> ''),
  CHECK (maximum_wall_time_seconds > 0 OR maximum_wall_time_nanos > 0),
  CHECK (update_time >= create_time),
  CHECK (delete_time IS NULL OR delete_time >= update_time)
);

CREATE TABLE workflow_definition_tools (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  definition_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  resource_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, definition_name, ordinal),
  UNIQUE (tenant_id, project_id, definition_name, resource_ref_id),
  FOREIGN KEY (tenant_id, project_id, definition_name)
    REFERENCES workflow_definitions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, resource_ref_id) REFERENCES resource_references(tenant_id, id)
);

CREATE TABLE workflow_definition_policies (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  definition_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, definition_name, ordinal),
  UNIQUE (tenant_id, project_id, definition_name, policy_snapshot_id),
  FOREIGN KEY (tenant_id, project_id, definition_name)
    REFERENCES workflow_definitions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE workflow_runs (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  definition_ref_id bigint NOT NULL,
  definition_digest text NOT NULL CHECK (definition_digest ~ '^sha256:[0-9a-f]{64}$'),
  agent_run_ref_id bigint,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 15),
  completed_node_count bigint NOT NULL CHECK (completed_node_count >= 0),
  iteration_count bigint NOT NULL CHECK (iteration_count >= 0),
  transition_sequence bigint NOT NULL CHECK (transition_sequence >= 0),
  attempt_id text NOT NULL DEFAULT '',
  lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
  input_ref_id bigint,
  output_ref_id bigint,
  replay_state_ref_id bigint,
  admission_decision_id bigint,
  decision_log_ref_id bigint,
  failure_detail_id bigint,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  end_time timestamptz,
  operation_id text NOT NULL,
  job_id text NOT NULL,
  scheduler_run_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, operation_id),
  FOREIGN KEY (tenant_id, definition_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, agent_run_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, input_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, output_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, replay_state_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, admission_decision_id) REFERENCES authorization_decisions(tenant_id, id),
  FOREIGN KEY (tenant_id, decision_log_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, failure_detail_id) REFERENCES error_details(tenant_id, id),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, scheduler_run_id) REFERENCES runs(tenant_id, project_id, id),
  CHECK (name <> '' AND uid <> ''),
  CHECK ((attempt_id = '') = (lease_epoch = 0)),
  CHECK (update_time >= create_time),
  CHECK (end_time IS NULL OR end_time >= create_time)
);

CREATE TABLE workflow_run_active_nodes (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  workflow_run_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  node_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, workflow_run_name, ordinal),
  UNIQUE (tenant_id, project_id, workflow_run_name, node_id),
  FOREIGN KEY (tenant_id, project_id, workflow_run_name)
    REFERENCES workflow_runs(tenant_id, project_id, name) ON DELETE CASCADE,
  CHECK (node_id <> '')
);

-- Each committed worker transition is a durable normalized watch snapshot.
CREATE TABLE workflow_transition_revisions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  workflow_run_name text NOT NULL,
  transition_sequence bigint NOT NULL CHECK (transition_sequence > 0),
  revision bigint NOT NULL CHECK (revision > 1),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 15),
  completed_node_count bigint NOT NULL CHECK (completed_node_count >= 0),
  iteration_count bigint NOT NULL CHECK (iteration_count >= 0),
  attempt_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  output_ref_id bigint,
  replay_state_ref_id bigint,
  decision_log_ref_id bigint,
  failure_detail_id bigint,
  update_time timestamptz NOT NULL,
  end_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, workflow_run_name, transition_sequence),
  UNIQUE (tenant_id, project_id, workflow_run_name, revision),
  FOREIGN KEY (tenant_id, project_id, workflow_run_name)
    REFERENCES workflow_runs(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, output_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, replay_state_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, decision_log_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, failure_detail_id) REFERENCES error_details(tenant_id, id)
);

CREATE TABLE workflow_transition_active_nodes (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  workflow_run_name text NOT NULL,
  transition_sequence bigint NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  node_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, workflow_run_name, transition_sequence, ordinal),
  UNIQUE (tenant_id, project_id, workflow_run_name, transition_sequence, node_id),
  FOREIGN KEY (tenant_id, project_id, workflow_run_name, transition_sequence)
    REFERENCES workflow_transition_revisions(tenant_id, project_id, workflow_run_name, transition_sequence)
    ON DELETE CASCADE,
  CHECK (node_id <> '')
);

CREATE TABLE approval_requests (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  context_request_id text NOT NULL,
  context_idempotency_key text NOT NULL,
  context_principal_id text NOT NULL,
  context_trace_id text NOT NULL DEFAULT '',
  context_deadline timestamptz,
  context_canonical_request_digest text NOT NULL CHECK (context_canonical_request_digest ~ '^sha256:[0-9a-f]{64}$'),
  context_correlation_id text NOT NULL DEFAULT '',
  context_causation_id text NOT NULL DEFAULT '',
  context_cancellation_token_id text NOT NULL DEFAULT '',
  binding_action text NOT NULL,
  binding_intent_digest text NOT NULL CHECK (binding_intent_digest ~ '^sha256:[0-9a-f]{64}$'),
  binding_parameters_digest text NOT NULL CHECK (binding_parameters_digest ~ '^sha256:[0-9a-f]{64}$'),
  binding_agent_run_name text NOT NULL DEFAULT '',
  binding_agent_step_name text NOT NULL DEFAULT '',
  binding_tool_ref_id bigint,
  binding_tool_version text NOT NULL DEFAULT '',
  binding_policy_snapshot_id bigint NOT NULL,
  binding_risk_class text NOT NULL,
  binding_digest text NOT NULL CHECK (binding_digest ~ '^sha256:[0-9a-f]{64}$'),
  requested_by_principal_ref text NOT NULL,
  minimum_independent_approvers bigint NOT NULL CHECK (minimum_independent_approvers > 0),
  reuse_policy integer NOT NULL CHECK (reuse_policy BETWEEN 1 AND 2),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 6),
  requested_at timestamptz NOT NULL,
  expire_time timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, binding_digest, requested_by_principal_ref, context_idempotency_key),
  FOREIGN KEY (tenant_id, binding_tool_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, binding_policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND context_request_id <> '' AND context_idempotency_key <> ''),
  CHECK (context_principal_id <> '' AND requested_by_principal_ref <> ''),
  CHECK (binding_action <> '' AND binding_risk_class <> ''),
  CHECK ((binding_tool_ref_id IS NULL) = (binding_tool_version = '')),
  CHECK (expire_time > requested_at),
  CHECK (context_deadline IS NULL OR context_deadline > requested_at)
);

CREATE TABLE approval_request_input_artifacts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  approval_request_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, approval_request_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, approval_request_name)
    REFERENCES approval_requests(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE approval_request_policy_decisions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  approval_request_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  authorization_decision_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, approval_request_name, ordinal),
  UNIQUE (tenant_id, project_id, approval_request_name, authorization_decision_id),
  FOREIGN KEY (tenant_id, project_id, approval_request_name)
    REFERENCES approval_requests(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, authorization_decision_id) REFERENCES authorization_decisions(tenant_id, id)
);

CREATE TABLE approval_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  context_request_id text NOT NULL,
  context_idempotency_key text NOT NULL,
  context_principal_id text NOT NULL,
  context_trace_id text NOT NULL DEFAULT '',
  context_deadline timestamptz,
  context_canonical_request_digest text NOT NULL CHECK (context_canonical_request_digest ~ '^sha256:[0-9a-f]{64}$'),
  context_correlation_id text NOT NULL DEFAULT '',
  context_causation_id text NOT NULL DEFAULT '',
  context_cancellation_token_id text NOT NULL DEFAULT '',
  request_ref_id bigint NOT NULL,
  binding_action text NOT NULL,
  binding_intent_digest text NOT NULL CHECK (binding_intent_digest ~ '^sha256:[0-9a-f]{64}$'),
  binding_parameters_digest text NOT NULL CHECK (binding_parameters_digest ~ '^sha256:[0-9a-f]{64}$'),
  binding_agent_run_name text NOT NULL DEFAULT '',
  binding_agent_step_name text NOT NULL DEFAULT '',
  binding_tool_ref_id bigint,
  binding_tool_version text NOT NULL DEFAULT '',
  binding_policy_snapshot_id bigint NOT NULL,
  binding_risk_class text NOT NULL,
  binding_digest text NOT NULL CHECK (binding_digest ~ '^sha256:[0-9a-f]{64}$'),
  decision integer NOT NULL CHECK (decision BETWEEN 1 AND 2),
  approver_principal_ref text NOT NULL,
  approver_authority_ref_id bigint NOT NULL,
  reason_code text NOT NULL,
  safe_reason text NOT NULL DEFAULT '',
  reuse_policy integer NOT NULL CHECK (reuse_policy BETWEEN 1 AND 2),
  decided_at timestamptz NOT NULL,
  expire_time timestamptz NOT NULL,
  signer_identity text NOT NULL,
  receipt_digest text NOT NULL CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, receipt_digest),
  UNIQUE (tenant_id, project_id, request_ref_id, approver_principal_ref),
  FOREIGN KEY (tenant_id, request_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, binding_tool_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, binding_policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id),
  FOREIGN KEY (tenant_id, approver_authority_ref_id) REFERENCES resource_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND context_request_id <> '' AND context_idempotency_key <> ''),
  CHECK (context_principal_id <> '' AND approver_principal_ref <> '' AND signer_identity <> ''),
  CHECK (binding_action <> '' AND binding_risk_class <> '' AND reason_code <> ''),
  CHECK ((binding_tool_ref_id IS NULL) = (binding_tool_version = '')),
  CHECK (expire_time > decided_at),
  CHECK (context_deadline IS NULL OR context_deadline > decided_at)
);

CREATE TABLE approval_receipt_input_artifacts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  approval_receipt_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, approval_receipt_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, approval_receipt_name)
    REFERENCES approval_receipts(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

-- Consumption is a separate immutable fact so the signed receipt body remains
-- immutable. SINGLE_USE is enforced under a receipt row lock; SAME_INTENT may
-- append distinct call IDs until expiry, while the resource projection exposes
-- the latest consumption.
CREATE TABLE approval_receipt_consumptions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  approval_receipt_name text NOT NULL,
  consumed_at timestamptz NOT NULL,
  consumed_by_call_id text NOT NULL,
  consumed_by_principal_ref text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, approval_receipt_name, consumed_by_call_id),
  FOREIGN KEY (tenant_id, project_id, approval_receipt_name)
    REFERENCES approval_receipts(tenant_id, project_id, name),
  CHECK (consumed_by_call_id <> '' AND consumed_by_principal_ref <> '')
);

CREATE TABLE agent_definitions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  display_name text NOT NULL,
  semantic_version text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  purpose text NOT NULL,
  definition_ref_id bigint NOT NULL,
  workflow_definition_ref_id bigint NOT NULL,
  input_schema_ref_id bigint,
  output_schema_ref_id bigint,
  model_capability text NOT NULL,
  evaluation_suite_ref_id bigint NOT NULL,
  budget_maximum_model_tokens bigint NOT NULL CHECK (budget_maximum_model_tokens > 0),
  budget_maximum_iterations bigint NOT NULL CHECK (budget_maximum_iterations > 0),
  budget_maximum_tool_calls bigint NOT NULL CHECK (budget_maximum_tool_calls > 0),
  budget_maximum_concurrent_branches bigint NOT NULL CHECK (budget_maximum_concurrent_branches > 0),
  budget_maximum_storage_bytes bigint NOT NULL CHECK (budget_maximum_storage_bytes > 0),
  budget_maximum_external_spend_micros bigint NOT NULL CHECK (budget_maximum_external_spend_micros >= 0),
  budget_maximum_wall_time_seconds bigint NOT NULL CHECK (budget_maximum_wall_time_seconds >= 0),
  budget_maximum_wall_time_nanos integer NOT NULL CHECK (budget_maximum_wall_time_nanos BETWEEN 0 AND 999999999),
  budget_maximum_accelerator_time_seconds bigint NOT NULL CHECK (budget_maximum_accelerator_time_seconds >= 0),
  budget_maximum_accelerator_time_nanos integer NOT NULL CHECK (budget_maximum_accelerator_time_nanos BETWEEN 0 AND 999999999),
  budget_maximum_cpu_time_seconds bigint NOT NULL CHECK (budget_maximum_cpu_time_seconds >= 0),
  budget_maximum_cpu_time_nanos integer NOT NULL CHECK (budget_maximum_cpu_time_nanos BETWEEN 0 AND 999999999),
  limit_maximum_depth bigint NOT NULL CHECK (limit_maximum_depth > 0),
  limit_maximum_fan_out bigint NOT NULL CHECK (limit_maximum_fan_out > 0),
  limit_maximum_observations_per_step bigint NOT NULL CHECK (limit_maximum_observations_per_step > 0),
  limit_maximum_artifact_references_per_call bigint NOT NULL CHECK (limit_maximum_artifact_references_per_call > 0),
  qualification_level text NOT NULL,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  delete_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  FOREIGN KEY (tenant_id, definition_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, workflow_definition_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, input_schema_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, output_schema_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, evaluation_suite_ref_id) REFERENCES resource_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND display_name <> '' AND semantic_version <> ''),
  CHECK (purpose <> '' AND model_capability <> '' AND qualification_level <> ''),
  CHECK (budget_maximum_wall_time_seconds > 0 OR budget_maximum_wall_time_nanos > 0),
  CHECK (update_time >= create_time),
  CHECK (delete_time IS NULL OR delete_time >= update_time)
);

CREATE TABLE agent_definition_non_goals (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  definition_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  non_goal text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, definition_name, ordinal),
  UNIQUE (tenant_id, project_id, definition_name, non_goal),
  FOREIGN KEY (tenant_id, project_id, definition_name)
    REFERENCES agent_definitions(tenant_id, project_id, name) ON DELETE CASCADE,
  CHECK (non_goal <> '')
);

CREATE TABLE agent_definition_tools (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  definition_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  resource_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, definition_name, ordinal),
  UNIQUE (tenant_id, project_id, definition_name, resource_ref_id),
  FOREIGN KEY (tenant_id, project_id, definition_name)
    REFERENCES agent_definitions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, resource_ref_id) REFERENCES resource_references(tenant_id, id)
);

CREATE TABLE agent_definition_policies (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  definition_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, definition_name, ordinal),
  UNIQUE (tenant_id, project_id, definition_name, policy_snapshot_id),
  FOREIGN KEY (tenant_id, project_id, definition_name)
    REFERENCES agent_definitions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE agent_runs (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  definition_ref_id bigint NOT NULL,
  definition_digest text NOT NULL CHECK (definition_digest ~ '^sha256:[0-9a-f]{64}$'),
  workflow_run_ref_id bigint,
  input_ref_id bigint,
  model_provider_manifest_ref_id bigint NOT NULL,
  budget_reservation_ref_id bigint NOT NULL,
  usage_model_tokens bigint NOT NULL CHECK (usage_model_tokens >= 0),
  usage_iterations bigint NOT NULL CHECK (usage_iterations >= 0),
  usage_tool_calls bigint NOT NULL CHECK (usage_tool_calls >= 0),
  usage_storage_bytes bigint NOT NULL CHECK (usage_storage_bytes >= 0),
  usage_external_spend_micros bigint NOT NULL CHECK (usage_external_spend_micros >= 0),
  usage_accelerator_milliseconds bigint NOT NULL CHECK (usage_accelerator_milliseconds >= 0),
  usage_cpu_milliseconds bigint NOT NULL CHECK (usage_cpu_milliseconds >= 0),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 14),
  active_step_name text NOT NULL DEFAULT '',
  next_step_sequence bigint NOT NULL CHECK (next_step_sequence > 0),
  attempt_id text NOT NULL DEFAULT '',
  lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
  cancellation_requested boolean NOT NULL DEFAULT false,
  run_manifest_ref_id bigint,
  output_ref_id bigint,
  failure_detail_id bigint,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  end_time timestamptz,
  operation_id text NOT NULL,
  job_id text NOT NULL,
  scheduler_run_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, operation_id),
  FOREIGN KEY (tenant_id, definition_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, workflow_run_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, input_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, model_provider_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, budget_reservation_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, run_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, output_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, failure_detail_id) REFERENCES error_details(tenant_id, id),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, scheduler_run_id) REFERENCES runs(tenant_id, project_id, id),
  CHECK (name <> '' AND uid <> ''),
  CHECK ((attempt_id = '') = (lease_epoch = 0)),
  CHECK (update_time >= create_time),
  CHECK (end_time IS NULL OR end_time >= create_time)
);

CREATE TABLE agent_run_policies (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_run_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, agent_run_name, ordinal),
  UNIQUE (tenant_id, project_id, agent_run_name, policy_snapshot_id),
  FOREIGN KEY (tenant_id, project_id, agent_run_name)
    REFERENCES agent_runs(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE agent_steps (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  agent_run_name text NOT NULL,
  run_ref_id bigint NOT NULL,
  sequence bigint NOT NULL CHECK (sequence > 0),
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  kind integer NOT NULL CHECK (kind BETWEEN 1 AND 6),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 8),
  attempt_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  output_ref_id bigint,
  failure_detail_id bigint,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  end_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, agent_run_name, sequence),
  FOREIGN KEY (tenant_id, project_id, agent_run_name)
    REFERENCES agent_runs(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, run_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, output_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, failure_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND attempt_id <> ''),
  CHECK (update_time >= create_time),
  CHECK (end_time IS NULL OR end_time >= create_time)
);

CREATE TABLE agent_step_policy_decisions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_step_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  authorization_decision_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, agent_step_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_steps(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, authorization_decision_id) REFERENCES authorization_decisions(tenant_id, id)
);

CREATE TABLE agent_step_observations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_step_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, agent_step_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_steps(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE agent_step_decisions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_step_name text NOT NULL,
  decision_id text NOT NULL,
  decision_type text NOT NULL,
  rationale_summary text NOT NULL,
  next_action_kind text NOT NULL CHECK (next_action_kind IN ('NONE','TOOL','DOMAIN_JOB','APPROVAL','WAIT','TERMINAL')),
  domain_job_ref_id bigint,
  approval_request_ref_id bigint,
  wait_maximum_duration_seconds bigint,
  wait_maximum_duration_nanos integer,
  wait_correlation_ref text NOT NULL DEFAULT '',
  terminal_result_ref_id bigint,
  replay_digest text NOT NULL CHECK (replay_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, agent_step_name),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_steps(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, domain_job_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, approval_request_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, terminal_result_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (decision_id <> '' AND decision_type <> ''),
  CHECK (wait_maximum_duration_nanos IS NULL OR wait_maximum_duration_nanos BETWEEN 0 AND 999999999),
  CHECK ((next_action_kind = 'DOMAIN_JOB') = (domain_job_ref_id IS NOT NULL)),
  CHECK ((next_action_kind = 'APPROVAL') = (approval_request_ref_id IS NOT NULL)),
  CHECK ((next_action_kind = 'WAIT') = (wait_maximum_duration_seconds IS NOT NULL)),
  CHECK ((next_action_kind = 'TERMINAL') = (terminal_result_ref_id IS NOT NULL))
);

CREATE TABLE agent_decision_evidence (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_step_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, agent_step_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_step_decisions(tenant_id, project_id, agent_step_name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE agent_tool_calls (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_step_name text NOT NULL,
  context_request_id text NOT NULL,
  context_idempotency_key text NOT NULL,
  context_principal_id text NOT NULL,
  context_trace_id text NOT NULL DEFAULT '',
  context_deadline timestamptz,
  context_canonical_request_digest text NOT NULL CHECK (context_canonical_request_digest ~ '^sha256:[0-9a-f]{64}$'),
  context_correlation_id text NOT NULL DEFAULT '',
  context_causation_id text NOT NULL DEFAULT '',
  context_cancellation_token_id text NOT NULL DEFAULT '',
  call_id text NOT NULL,
  agent_run_name text NOT NULL,
  declared_agent_step_name text NOT NULL,
  tool_ref_id bigint NOT NULL,
  tool_version text NOT NULL,
  authorization_decision_id bigint NOT NULL,
  input_digest text NOT NULL CHECK (input_digest ~ '^sha256:[0-9a-f]{64}$'),
  parameters_ref_id bigint,
  deadline timestamptz NOT NULL,
  budget_reservation_ref_id bigint NOT NULL,
  expected_output_schema_ref_id bigint NOT NULL,
  side_effect_class text NOT NULL,
  output_classification text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, agent_step_name),
  UNIQUE (tenant_id, project_id, agent_run_name, call_id),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_step_decisions(tenant_id, project_id, agent_step_name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, tool_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, authorization_decision_id) REFERENCES authorization_decisions(tenant_id, id),
  FOREIGN KEY (tenant_id, parameters_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, budget_reservation_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, expected_output_schema_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (context_request_id <> '' AND context_idempotency_key <> '' AND context_principal_id <> ''),
  CHECK (call_id <> '' AND agent_run_name <> '' AND declared_agent_step_name = agent_step_name),
  CHECK (tool_version <> '' AND side_effect_class <> '' AND output_classification <> '')
);

CREATE TABLE agent_tool_call_approvals (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_step_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  approval_receipt_name text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, agent_step_name, ordinal),
  UNIQUE (tenant_id, project_id, agent_step_name, approval_receipt_name),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_tool_calls(tenant_id, project_id, agent_step_name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, project_id, approval_receipt_name)
    REFERENCES approval_receipts(tenant_id, project_id, name)
);

CREATE TABLE agent_tool_call_inputs (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  agent_step_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, agent_step_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_tool_calls(tenant_id, project_id, agent_step_name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE agent_tool_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  call_id text NOT NULL,
  agent_run_name text NOT NULL,
  agent_step_name text NOT NULL,
  tool_ref_id bigint NOT NULL,
  tool_version text NOT NULL,
  attempt_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  authorization_decision_id bigint NOT NULL,
  idempotency_key text NOT NULL,
  input_digest text NOT NULL CHECK (input_digest ~ '^sha256:[0-9a-f]{64}$'),
  expected_output_schema_digest text NOT NULL CHECK (expected_output_schema_digest ~ '^sha256:[0-9a-f]{64}$'),
  outcome integer NOT NULL CHECK (outcome BETWEEN 1 AND 6),
  side_effect_state integer NOT NULL CHECK (side_effect_state BETWEEN 1 AND 6),
  output_digest text NOT NULL CHECK (output_digest ~ '^sha256:[0-9a-f]{64}$'),
  reconciliation_evidence_ref_id bigint,
  failure_detail_id bigint,
  usage_input_bytes bigint NOT NULL CHECK (usage_input_bytes >= 0),
  usage_output_bytes bigint NOT NULL CHECK (usage_output_bytes >= 0),
  usage_cpu_milliseconds bigint NOT NULL CHECK (usage_cpu_milliseconds >= 0),
  usage_accelerator_milliseconds bigint NOT NULL CHECK (usage_accelerator_milliseconds >= 0),
  usage_external_spend_micros bigint NOT NULL CHECK (usage_external_spend_micros >= 0),
  started_at timestamptz NOT NULL,
  completed_at timestamptz NOT NULL,
  executor_identity text NOT NULL,
  source_revision text NOT NULL,
  receipt_digest text NOT NULL CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, call_id),
  UNIQUE (tenant_id, project_id, receipt_digest),
  UNIQUE (tenant_id, project_id, idempotency_key),
  FOREIGN KEY (tenant_id, project_id, agent_run_name)
    REFERENCES agent_runs(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, project_id, agent_step_name)
    REFERENCES agent_steps(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, tool_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, authorization_decision_id) REFERENCES authorization_decisions(tenant_id, id),
  FOREIGN KEY (tenant_id, reconciliation_evidence_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, failure_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND call_id <> '' AND agent_run_name <> '' AND agent_step_name <> ''),
  CHECK (tool_version <> '' AND attempt_id <> '' AND idempotency_key <> ''),
  CHECK (executor_identity <> '' AND source_revision <> ''),
  CHECK (completed_at >= started_at)
);

CREATE TABLE agent_tool_receipt_approvals (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  tool_receipt_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  resource_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, tool_receipt_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, tool_receipt_name)
    REFERENCES agent_tool_receipts(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, resource_ref_id) REFERENCES resource_references(tenant_id, id)
);

CREATE TABLE agent_tool_receipt_outputs (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  tool_receipt_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, tool_receipt_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, tool_receipt_name)
    REFERENCES agent_tool_receipts(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE workflow_agent_command_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  principal_id text NOT NULL,
  action text NOT NULL CHECK (action IN (
    'workflow.definition.create','workflow.definition.update','workflow.run.start',
    'workflow.run.cancel','workflow.run.commit_transition','approval.request',
    'approval.decide','approval.consume','agent.definition.create','agent.definition.update',
    'agent.run.start','agent.run.cancel','agent.step.commit','agent.tool_receipt.commit'
  )),
  idempotency_key text NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text,
  response_name text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, principal_id, action, idempotency_key),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  CHECK (principal_id <> '' AND response_name <> ''),
  CHECK ((action LIKE 'approval.%' OR action IN ('workflow.run.commit_transition','agent.step.commit','agent.tool_receipt.commit')) OR operation_id IS NOT NULL)
);

CREATE INDEX workflow_definitions_list_idx
  ON workflow_definitions (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX workflow_runs_list_idx
  ON workflow_runs (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX workflow_transition_watch_idx
  ON workflow_transition_revisions (tenant_id, project_id, workflow_run_name, transition_sequence);
CREATE INDEX approval_requests_list_idx
  ON approval_requests (tenant_id, project_id, requested_at DESC, name DESC);
CREATE INDEX agent_definitions_list_idx
  ON agent_definitions (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX agent_runs_list_idx
  ON agent_runs (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX agent_steps_list_idx
  ON agent_steps (tenant_id, project_id, agent_run_name, sequence);
CREATE INDEX workflow_agent_receipts_operation_idx
  ON workflow_agent_command_receipts (tenant_id, project_id, operation_id)
  WHERE operation_id IS NOT NULL;

CREATE FUNCTION reject_workflow_agent_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is immutable', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END;
$$;
CREATE TRIGGER workflow_transition_revisions_immutable BEFORE UPDATE OR DELETE ON workflow_transition_revisions
  FOR EACH ROW EXECUTE FUNCTION reject_workflow_agent_immutable_change();
CREATE TRIGGER approval_receipts_immutable BEFORE UPDATE OR DELETE ON approval_receipts
  FOR EACH ROW EXECUTE FUNCTION reject_workflow_agent_immutable_change();
CREATE TRIGGER approval_consumptions_immutable BEFORE UPDATE OR DELETE ON approval_receipt_consumptions
  FOR EACH ROW EXECUTE FUNCTION reject_workflow_agent_immutable_change();
CREATE TRIGGER agent_steps_immutable BEFORE UPDATE OR DELETE ON agent_steps
  FOR EACH ROW EXECUTE FUNCTION reject_workflow_agent_immutable_change();
CREATE TRIGGER agent_tool_receipts_immutable BEFORE UPDATE OR DELETE ON agent_tool_receipts
  FOR EACH ROW EXECUTE FUNCTION reject_workflow_agent_immutable_change();
CREATE TRIGGER workflow_agent_command_receipts_immutable BEFORE UPDATE OR DELETE ON workflow_agent_command_receipts
  FOR EACH ROW EXECUTE FUNCTION reject_workflow_agent_immutable_change();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'workflow_definitions','workflow_definition_tools','workflow_definition_policies',
    'workflow_runs','workflow_run_active_nodes','workflow_transition_revisions',
    'workflow_transition_active_nodes','approval_requests','approval_request_input_artifacts',
    'approval_request_policy_decisions','approval_receipts','approval_receipt_input_artifacts',
    'approval_receipt_consumptions','agent_definitions','agent_definition_non_goals',
    'agent_definition_tools','agent_definition_policies','agent_runs','agent_run_policies',
    'agent_steps','agent_step_policy_decisions','agent_step_observations',
    'agent_step_decisions','agent_decision_evidence','agent_tool_calls',
    'agent_tool_call_approvals','agent_tool_call_inputs','agent_tool_receipts',
    'agent_tool_receipt_approvals','agent_tool_receipt_outputs','workflow_agent_command_receipts'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
      table_name || '_tenant_policy', table_name
    );
  END LOOP;
END;
$$;

COMMIT;
