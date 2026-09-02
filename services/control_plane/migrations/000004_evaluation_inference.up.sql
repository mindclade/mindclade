BEGIN;

-- Immutable policy snapshots and authorization decisions are normalized once
-- for every scientific vertical. Mutable aggregates reference these rows; no
-- protobuf blob is used as durable state.
CREATE TABLE policy_snapshot_references (
  tenant_id text NOT NULL,
  id bigint GENERATED ALWAYS AS IDENTITY,
  name text NOT NULL,
  uid text NOT NULL,
  policy_type text NOT NULL,
  semantic_version text NOT NULL,
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  document_ref_id bigint NOT NULL,
  resource_revision bigint NOT NULL CHECK (resource_revision > 0),
  effective_time timestamptz NOT NULL,
  expire_time timestamptz,
  classification text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, name, resource_revision, digest),
  FOREIGN KEY (tenant_id, document_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND policy_type <> '' AND semantic_version <> ''),
  CHECK (expire_time IS NULL OR expire_time > effective_time)
);

CREATE TABLE authorization_decisions (
  tenant_id text NOT NULL,
  id bigint GENERATED ALWAYS AS IDENTITY,
  name text NOT NULL,
  uid text NOT NULL,
  project_id text NOT NULL,
  principal_ref text NOT NULL,
  action text NOT NULL,
  resource_ref_id bigint NOT NULL,
  intent_digest text NOT NULL CHECK (intent_digest ~ '^sha256:[0-9a-f]{64}$'),
  outcome integer NOT NULL CHECK (outcome BETWEEN 1 AND 3),
  reason_code text NOT NULL,
  safe_reason text NOT NULL DEFAULT '',
  evaluated_at timestamptz NOT NULL,
  expire_time timestamptz,
  context_digest text NOT NULL CHECK (context_digest ~ '^sha256:[0-9a-f]{64}$'),
  decision_digest text NOT NULL CHECK (decision_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, name),
  UNIQUE (tenant_id, uid),
  FOREIGN KEY (tenant_id, resource_ref_id) REFERENCES resource_references(tenant_id, id),
  CHECK (project_id <> '' AND principal_ref <> '' AND action <> '' AND reason_code <> ''),
  CHECK (expire_time IS NULL OR expire_time > evaluated_at)
);

CREATE TABLE authorization_decision_policies (
  tenant_id text NOT NULL,
  decision_id bigint NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, decision_id, ordinal),
  FOREIGN KEY (tenant_id, decision_id) REFERENCES authorization_decisions(tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE authorization_decision_constraints (
  tenant_id text NOT NULL,
  decision_id bigint NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  constraint_kind text NOT NULL,
  details_digest text NOT NULL CHECK (details_digest ~ '^sha256:[0-9a-f]{64}$'),
  expire_time timestamptz,
  PRIMARY KEY (tenant_id, decision_id, ordinal),
  FOREIGN KEY (tenant_id, decision_id) REFERENCES authorization_decisions(tenant_id, id) ON DELETE CASCADE,
  CHECK (constraint_kind <> '')
);

CREATE TABLE evaluation_runs (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  suite_ref_id bigint NOT NULL,
  snapshot_ref_id bigint NOT NULL,
  model_release_ref_id bigint NOT NULL,
  inference_protocol_ref_id bigint NOT NULL,
  executable_plan_ref_id bigint,
  provider_manifest_ref_id bigint,
  kernel_qualification_ref_id bigint,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text NOT NULL,
  job_id text NOT NULL,
  scheduler_run_id text NOT NULL,
  attempt_id text NOT NULL DEFAULT '',
  lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 11),
  completed_samples bigint NOT NULL DEFAULT 0 CHECK (completed_samples >= 0),
  total_samples bigint CHECK (total_samples >= 0),
  failure_ref_id bigint,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  end_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, operation_id),
  FOREIGN KEY (tenant_id, suite_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, snapshot_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, model_release_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, inference_protocol_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, executable_plan_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, provider_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, kernel_qualification_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, scheduler_run_id) REFERENCES runs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, failure_ref_id) REFERENCES error_details(tenant_id, id),
  CHECK ((attempt_id = '') = (lease_epoch = 0)),
  CHECK (update_time >= create_time),
  CHECK (end_time IS NULL OR end_time >= create_time)
);

CREATE TABLE evaluation_run_datasets (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  evaluation_run_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  dataset_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, evaluation_run_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, evaluation_run_name)
    REFERENCES evaluation_runs(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, dataset_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE evaluation_run_policies (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  evaluation_run_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, evaluation_run_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, evaluation_run_name)
    REFERENCES evaluation_runs(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE evaluation_results (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  evaluation_run_name text NOT NULL,
  run_ref_id bigint NOT NULL,
  run_digest text NOT NULL CHECK (run_digest ~ '^sha256:[0-9a-f]{64}$'),
  outcome integer NOT NULL CHECK (outcome BETWEEN 1 AND 5),
  report_ref_id bigint NOT NULL,
  suite_ref_id bigint NOT NULL,
  snapshot_ref_id bigint NOT NULL,
  dataset_manifest_ref_id bigint NOT NULL,
  inference_protocol_ref_id bigint NOT NULL,
  leakage_evidence_ref_id bigint,
  safety_evidence_ref_id bigint,
  statistical_evidence_ref_id bigint,
  performance_evidence_ref_id bigint,
  source_revision text NOT NULL,
  finalized_at timestamptz NOT NULL,
  result_digest text NOT NULL CHECK (result_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, evaluation_run_name),
  FOREIGN KEY (tenant_id, project_id, evaluation_run_name)
    REFERENCES evaluation_runs(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, run_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, report_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, suite_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, snapshot_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, dataset_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, inference_protocol_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, leakage_evidence_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, safety_evidence_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, statistical_evidence_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, performance_evidence_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND source_revision <> '')
);

CREATE TABLE evaluation_result_metrics (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  result_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  metric_id text NOT NULL,
  metric_version text NOT NULL,
  unit text NOT NULL,
  direction integer NOT NULL CHECK (direction BETWEEN 1 AND 3),
  metric_value double precision NOT NULL CHECK (metric_value > '-Infinity'::double precision AND metric_value < 'Infinity'::double precision),
  interval_lower double precision CHECK (interval_lower > '-Infinity'::double precision AND interval_lower < 'Infinity'::double precision),
  interval_upper double precision CHECK (interval_upper > '-Infinity'::double precision AND interval_upper < 'Infinity'::double precision),
  valid_count bigint NOT NULL CHECK (valid_count >= 0),
  invalid_count bigint NOT NULL CHECK (invalid_count >= 0),
  cohort_id text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, result_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, result_name)
    REFERENCES evaluation_results(tenant_id, project_id, name) ON DELETE CASCADE,
  CHECK ((interval_lower IS NULL) = (interval_upper IS NULL)),
  CHECK (interval_lower IS NULL OR interval_lower <= interval_upper)
);

CREATE TABLE evaluation_result_thresholds (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  result_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  rule_id text NOT NULL,
  metric_id text NOT NULL,
  threshold_result integer NOT NULL CHECK (threshold_result BETWEEN 1 AND 4),
  reason_code text NOT NULL,
  evidence_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, result_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, result_name)
    REFERENCES evaluation_results(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, evidence_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (rule_id <> '' AND metric_id <> '' AND reason_code <> '')
);

CREATE TABLE evaluation_result_failure_counts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  result_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  failure_class text NOT NULL,
  failure_count bigint NOT NULL CHECK (failure_count > 0),
  PRIMARY KEY (tenant_id, project_id, result_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, result_name)
    REFERENCES evaluation_results(tenant_id, project_id, name) ON DELETE CASCADE,
  CHECK (failure_class <> '')
);

CREATE TABLE promotion_decisions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  candidate_release_ref_id bigint NOT NULL,
  candidate_digest text NOT NULL CHECK (candidate_digest ~ '^sha256:[0-9a-f]{64}$'),
  target_profile text NOT NULL,
  outcome integer NOT NULL CHECK (outcome BETWEEN 1 AND 4),
  reason_code text NOT NULL,
  safe_reason text NOT NULL DEFAULT '',
  decided_by_principal_ref text NOT NULL,
  decided_at timestamptz NOT NULL,
  expire_time timestamptz,
  source_revision text NOT NULL,
  decision_digest text NOT NULL CHECK (decision_digest ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, decision_digest),
  FOREIGN KEY (tenant_id, candidate_release_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  CHECK (target_profile <> '' AND reason_code <> '' AND decided_by_principal_ref <> '' AND source_revision <> ''),
  CHECK (expire_time IS NULL OR expire_time > decided_at)
);

CREATE TABLE promotion_decision_results (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  decision_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  evaluation_result_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, decision_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, decision_name)
    REFERENCES promotion_decisions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, evaluation_result_ref_id) REFERENCES resource_references(tenant_id, id)
);

CREATE TABLE promotion_decision_rules (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  decision_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  rule_id text NOT NULL,
  threshold_result integer NOT NULL CHECK (threshold_result BETWEEN 1 AND 4),
  reason_code text NOT NULL,
  evidence_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, decision_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, decision_name)
    REFERENCES promotion_decisions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, evidence_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE promotion_decision_exceptions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  decision_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  exception_id text NOT NULL,
  rule_id text NOT NULL,
  rationale_ref_id bigint NOT NULL,
  expire_time timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, decision_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, decision_name)
    REFERENCES promotion_decisions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, rationale_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (exception_id <> '' AND rule_id <> '')
);

CREATE TABLE promotion_exception_approvals (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  decision_name text NOT NULL,
  exception_ordinal integer NOT NULL CHECK (exception_ordinal >= 0),
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  approval_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, decision_name, exception_ordinal, ordinal),
  FOREIGN KEY (tenant_id, project_id, decision_name, exception_ordinal)
    REFERENCES promotion_decision_exceptions(tenant_id, project_id, decision_name, ordinal) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, approval_ref_id) REFERENCES resource_references(tenant_id, id)
);

CREATE TABLE promotion_decision_authorizations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  decision_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  authorization_decision_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, decision_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, decision_name)
    REFERENCES promotion_decisions(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, authorization_decision_id) REFERENCES authorization_decisions(tenant_id, id)
);

CREATE TABLE inference_requests (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  context_request_id text NOT NULL,
  context_idempotency_key text NOT NULL,
  context_principal_id text NOT NULL,
  context_trace_id text NOT NULL DEFAULT '',
  context_deadline timestamptz,
  context_canonical_request_digest text NOT NULL CHECK (context_canonical_request_digest ~ '^sha256:[0-9a-f]{64}$'),
  context_tenant_id text NOT NULL,
  context_project_id text NOT NULL,
  context_correlation_id text NOT NULL DEFAULT '',
  context_causation_id text NOT NULL DEFAULT '',
  context_cancellation_token_id text NOT NULL DEFAULT '',
  capability text NOT NULL,
  mode integer NOT NULL CHECK (mode BETWEEN 1 AND 5),
  model_ref_id bigint NOT NULL,
  resolved_model_bundle_ref_id bigint NOT NULL,
  input_kind text NOT NULL CHECK (input_kind IN ('ARTIFACT','INLINE')),
  input_artifact_ref_id bigint,
  inline_media_type text NOT NULL DEFAULT '',
  inline_schema_id text NOT NULL DEFAULT '',
  inline_payload bytea,
  inline_content_digest text NOT NULL DEFAULT '' CHECK (inline_content_digest = '' OR inline_content_digest ~ '^sha256:[0-9a-f]{64}$'),
  feature_policy_ref_id bigint NOT NULL,
  sampling_algorithm text NOT NULL,
  sampling_algorithm_version text NOT NULL,
  sampling_candidate_count integer NOT NULL CHECK (sampling_candidate_count BETWEEN 1 AND 256),
  sampling_maximum_steps integer NOT NULL CHECK (sampling_maximum_steps > 0),
  sampling_temperature double precision CHECK (sampling_temperature > '-Infinity'::double precision AND sampling_temperature < 'Infinity'::double precision),
  sampling_guidance_scale double precision CHECK (sampling_guidance_scale > '-Infinity'::double precision AND sampling_guidance_scale < 'Infinity'::double precision),
  sampling_random_key text NOT NULL,
  sampling_maximum_compute_seconds bigint NOT NULL CHECK (sampling_maximum_compute_seconds >= 0),
  sampling_maximum_compute_nanos integer NOT NULL CHECK (sampling_maximum_compute_nanos BETWEEN 0 AND 999999999),
  sampling_policy_ref_id bigint NOT NULL,
  confidence_policy_ref_id bigint NOT NULL,
  result_schema_id text NOT NULL,
  include_bounded_candidate_summaries boolean NOT NULL,
  retain_diagnostics boolean NOT NULL,
  resource_class text NOT NULL,
  reproducibility integer NOT NULL CHECK (reproducibility BETWEEN 1 AND 4),
  data_classification text NOT NULL,
  deadline timestamptz NOT NULL,
  create_time timestamptz NOT NULL,
  operation_id text NOT NULL,
  job_id text NOT NULL,
  scheduler_run_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, operation_id),
  FOREIGN KEY (tenant_id, model_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, resolved_model_bundle_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, input_artifact_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, feature_policy_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, sampling_policy_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, confidence_policy_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, scheduler_run_id) REFERENCES runs(tenant_id, project_id, id),
  CHECK (context_request_id <> '' AND context_idempotency_key <> '' AND context_principal_id <> ''),
  CHECK (context_tenant_id = tenant_id AND context_project_id = project_id),
  CHECK (context_deadline IS NULL OR context_deadline > create_time),
  CHECK (capability <> '' AND sampling_algorithm <> '' AND sampling_algorithm_version <> '' AND sampling_random_key <> ''),
  CHECK (octet_length(inline_payload) <= 1048576),
  CHECK ((input_kind = 'ARTIFACT') = (input_artifact_ref_id IS NOT NULL)),
  CHECK ((input_kind = 'INLINE') = (inline_payload IS NOT NULL)),
  CHECK ((input_kind = 'ARTIFACT') OR (inline_media_type <> '' AND inline_schema_id <> '' AND inline_content_digest <> '')),
  CHECK (deadline > create_time)
);

CREATE TABLE inference_request_output_kinds (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  request_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_kind text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, request_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, request_name)
    REFERENCES inference_requests(tenant_id, project_id, name) ON DELETE CASCADE,
  CHECK (artifact_kind <> '')
);

CREATE TABLE inference_request_policies (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  request_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, request_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, request_name)
    REFERENCES inference_requests(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id) REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE inference_results (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  inference_request_name text NOT NULL,
  request_ref_id bigint NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  operation_ref_id bigint NOT NULL,
  job_id text NOT NULL,
  scheduler_run_id text NOT NULL,
  attempt_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  outcome integer NOT NULL CHECK (outcome BETWEEN 1 AND 6),
  result_manifest_ref_id bigint NOT NULL,
  input_artifact_ref_id bigint,
  model_bundle_ref_id bigint NOT NULL,
  feature_bundle_ref_id bigint,
  executable_plan_ref_id bigint,
  provider_manifest_ref_id bigint,
  kernel_qualification_ref_id bigint,
  selected_candidate_id text NOT NULL DEFAULT '',
  confidence_report_ref_id bigint,
  ranking_report_ref_id bigint,
  failure_diagnostics_ref_id bigint,
  source_revision text NOT NULL,
  completed_at timestamptz NOT NULL,
  result_digest text NOT NULL CHECK (result_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, inference_request_name),
  FOREIGN KEY (tenant_id, project_id, inference_request_name)
    REFERENCES inference_requests(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, request_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, operation_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, result_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, input_artifact_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, model_bundle_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, feature_bundle_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, executable_plan_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, provider_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, kernel_qualification_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, confidence_report_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, ranking_report_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, failure_diagnostics_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND source_revision <> '')
);

CREATE TABLE inference_result_candidates (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  result_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 255),
  candidate_id text NOT NULL,
  sample_index integer NOT NULL CHECK (sample_index >= 0),
  output_ref_id bigint NOT NULL,
  confidence double precision CHECK (confidence > '-Infinity'::double precision AND confidence < 'Infinity'::double precision),
  selected boolean NOT NULL,
  diagnostics_ref_id bigint,
  PRIMARY KEY (tenant_id, project_id, result_name, ordinal),
  UNIQUE (tenant_id, project_id, result_name, candidate_id),
  FOREIGN KEY (tenant_id, project_id, result_name)
    REFERENCES inference_results(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, output_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, diagnostics_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (candidate_id <> '')
);

CREATE TABLE inference_result_authorizations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  result_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  authorization_decision_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, result_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, result_name)
    REFERENCES inference_results(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, authorization_decision_id) REFERENCES authorization_decisions(tenant_id, id)
);

CREATE TABLE evaluation_inference_command_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  principal_id text NOT NULL,
  action text NOT NULL,
  idempotency_key text NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, principal_id, action, idempotency_key),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  CHECK (principal_id <> '' AND action <> '' AND idempotency_key <> '')
);

CREATE INDEX evaluation_runs_list_idx ON evaluation_runs (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX inference_requests_operation_idx ON inference_requests (tenant_id, project_id, operation_id);
CREATE INDEX evaluation_inference_receipts_operation_idx ON evaluation_inference_command_receipts (tenant_id, project_id, operation_id);

-- Results and decisions are immutable scientific/governance records.
CREATE FUNCTION reject_immutable_scientific_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is immutable', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END;
$$;
CREATE TRIGGER evaluation_results_immutable BEFORE UPDATE OR DELETE ON evaluation_results
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_scientific_update();
CREATE TRIGGER promotion_decisions_immutable BEFORE UPDATE OR DELETE ON promotion_decisions
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_scientific_update();
CREATE TRIGGER inference_requests_immutable BEFORE UPDATE OR DELETE ON inference_requests
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_scientific_update();
CREATE TRIGGER inference_results_immutable BEFORE UPDATE OR DELETE ON inference_results
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_scientific_update();
CREATE TRIGGER authorization_decisions_immutable BEFORE UPDATE OR DELETE ON authorization_decisions
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_scientific_update();

ALTER TABLE policy_snapshot_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE authorization_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE authorization_decision_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE authorization_decision_constraints ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_run_datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_run_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_result_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_result_thresholds ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_result_failure_counts ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_exception_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_request_output_kinds ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_request_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_result_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_result_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_inference_command_receipts ENABLE ROW LEVEL SECURITY;

ALTER TABLE policy_snapshot_references FORCE ROW LEVEL SECURITY;
ALTER TABLE authorization_decisions FORCE ROW LEVEL SECURITY;
ALTER TABLE authorization_decision_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE authorization_decision_constraints FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_run_datasets FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_run_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_results FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_result_metrics FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_result_thresholds FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_result_failure_counts FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_decisions FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_results FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_rules FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_exceptions FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_exception_approvals FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_decision_authorizations FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_request_output_kinds FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_request_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_results FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_result_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_result_authorizations FORCE ROW LEVEL SECURITY;
ALTER TABLE evaluation_inference_command_receipts FORCE ROW LEVEL SECURITY;

DO $$
DECLARE table_name text;
BEGIN
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
  ]
  LOOP
    EXECUTE format(
      'CREATE POLICY %I ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
      table_name || '_tenant_policy', table_name
    );
  END LOOP;
END;
$$;

COMMIT;
