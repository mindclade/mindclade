BEGIN;

-- Nested protobuf values remain normalized relational state. A row's presence
-- preserves protobuf message presence; no mutable aggregate is stored as bytes.
CREATE TABLE artifact_references (
  id bigint GENERATED ALWAYS AS IDENTITY,
  tenant_id text NOT NULL,
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  media_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  artifact_kind text NOT NULL DEFAULT '',
  schema_id text NOT NULL DEFAULT '',
  integrity_digest text NOT NULL DEFAULT '' CHECK (integrity_digest = '' OR integrity_digest ~ '^sha256:[0-9a-f]{64}$'),
  uri text NOT NULL DEFAULT '',
  schema_version text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE resource_references (
  id bigint GENERATED ALWAYS AS IDENTITY,
  tenant_id text NOT NULL,
  resource_type text NOT NULL,
  resource_id text NOT NULL,
  referenced_tenant_id text NOT NULL DEFAULT '',
  project_id text NOT NULL DEFAULT '',
  resource_version bigint NOT NULL DEFAULT 0 CHECK (resource_version >= 0),
  name text NOT NULL,
  etag text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, id),
  CHECK (resource_type <> '' AND resource_id <> '' AND name <> '')
);

CREATE TABLE error_details (
  id bigint GENERATED ALWAYS AS IDENTITY,
  tenant_id text NOT NULL,
  code integer NOT NULL CHECK (code > 0),
  message text NOT NULL,
  retry_class integer NOT NULL CHECK (retry_class >= 0),
  subject_present boolean NOT NULL,
  subject_resource_type text NOT NULL DEFAULT '',
  subject_resource_id text NOT NULL DEFAULT '',
  subject_tenant_id text NOT NULL DEFAULT '',
  subject_project_id text NOT NULL DEFAULT '',
  subject_resource_version bigint NOT NULL DEFAULT 0 CHECK (subject_resource_version >= 0),
  subject_name text NOT NULL DEFAULT '',
  subject_etag text NOT NULL DEFAULT '',
  retry_after_seconds bigint,
  retry_after_nanos integer CHECK (retry_after_nanos BETWEEN -999999999 AND 999999999),
  error_id text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, id),
  CHECK ((retry_after_seconds IS NULL) = (retry_after_nanos IS NULL))
);

CREATE TABLE error_field_violations (
  tenant_id text NOT NULL,
  error_detail_id bigint NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  field_path text NOT NULL,
  description text NOT NULL,
  PRIMARY KEY (tenant_id, error_detail_id, ordinal),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE error_precondition_violations (
  tenant_id text NOT NULL,
  error_detail_id bigint NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  violation_type text NOT NULL,
  subject text NOT NULL,
  description text NOT NULL,
  PRIMARY KEY (tenant_id, error_detail_id, ordinal),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id) ON DELETE CASCADE
);

CREATE TABLE jobs (
  id text NOT NULL,
  tenant_id text NOT NULL,
  operation_id text NOT NULL DEFAULT '',
  project_id text NOT NULL DEFAULT '',
  desired_state text NOT NULL CHECK (desired_state IN ('ACCEPTED','QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLING','CANCELLED')),
  version bigint NOT NULL CHECK (version > 0),
  policy_digest text NOT NULL DEFAULT '',
  job_kind text NOT NULL DEFAULT '',
  input_ref_id bigint,
  configuration_ref_id bigint,
  configuration_digest text NOT NULL CHECK (configuration_digest ~ '^sha256:[0-9a-f]{64}$'),
  etag text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, input_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, configuration_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE operations (
  id text NOT NULL,
  tenant_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  job_id text NOT NULL,
  target_present boolean NOT NULL DEFAULT false,
  target_resource_type text NOT NULL DEFAULT '',
  target_resource_id text NOT NULL DEFAULT '',
  target_tenant_id text NOT NULL DEFAULT '',
  target_project_id text NOT NULL DEFAULT '',
  target_resource_version bigint NOT NULL DEFAULT 0 CHECK (target_resource_version >= 0),
  target_name text NOT NULL DEFAULT '',
  target_etag text NOT NULL DEFAULT '',
  status text NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLING','CANCELLED')),
  version bigint NOT NULL CHECK (version > 0),
  done boolean NOT NULL,
  etag text NOT NULL DEFAULT '',
  result_ref_id bigint,
  error_detail_id bigint,
  request_hash text NOT NULL CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  history_floor_version bigint NOT NULL DEFAULT 1 CHECK (history_floor_version > 0 AND history_floor_version <= version),
  PRIMARY KEY (tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, result_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (done = (status IN ('SUCCEEDED','FAILED','CANCELLED'))),
  CHECK (target_present OR (
    target_resource_type = '' AND target_resource_id = '' AND target_tenant_id = '' AND
    target_project_id = '' AND target_resource_version = 0 AND target_name = '' AND target_etag = ''
  )),
  CHECK (NOT target_present OR (target_resource_type <> '' AND target_resource_id <> '' AND target_name <> ''))
);

-- Immutable, normalized snapshots make operation watches lossless. The
-- current operation row remains the aggregate authority; these rows are the
-- bounded resumability history and never contain serialized mutable state.
CREATE TABLE operation_revisions (
  operation_id text NOT NULL,
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  job_id text NOT NULL,
  target_present boolean NOT NULL DEFAULT false,
  target_resource_type text NOT NULL DEFAULT '',
  target_resource_id text NOT NULL DEFAULT '',
  target_tenant_id text NOT NULL DEFAULT '',
  target_project_id text NOT NULL DEFAULT '',
  target_resource_version bigint NOT NULL DEFAULT 0 CHECK (target_resource_version >= 0),
  target_name text NOT NULL DEFAULT '',
  target_etag text NOT NULL DEFAULT '',
  status text NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLING','CANCELLED')),
  done boolean NOT NULL,
  etag text NOT NULL,
  result_ref_id bigint,
  error_detail_id bigint,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, operation_id, revision),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, result_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (done = (status IN ('SUCCEEDED','FAILED','CANCELLED'))),
  CHECK (target_present OR (
    target_resource_type = '' AND target_resource_id = '' AND target_tenant_id = '' AND
    target_project_id = '' AND target_resource_version = 0 AND target_name = '' AND target_etag = ''
  )),
  CHECK (NOT target_present OR (target_resource_type <> '' AND target_resource_id <> '' AND target_name <> ''))
);
CREATE INDEX operation_revisions_watch_idx
  ON operation_revisions (tenant_id, project_id, operation_id, revision);

CREATE TABLE training_progress_snapshots (
  id bigint GENERATED ALWAYS AS IDENTITY,
  tenant_id text NOT NULL,
  training_run_name text NOT NULL,
  progress_revision bigint NOT NULL CHECK (progress_revision >= 0),
  latest_update_present boolean NOT NULL DEFAULT false,
  latest_update_value text NOT NULL DEFAULT '',
  latest_update_sequence bigint NOT NULL DEFAULT 0 CHECK (latest_update_sequence >= 0),
  committed_update_count bigint NOT NULL DEFAULT 0 CHECK (committed_update_count >= 0),
  committed_sample_count bigint NOT NULL DEFAULT 0 CHECK (committed_sample_count >= 0),
  committed_token_count bigint NOT NULL DEFAULT 0 CHECK (committed_token_count >= 0),
  effective_work_units bigint NOT NULL DEFAULT 0 CHECK (effective_work_units >= 0),
  effective_work_unit_name text NOT NULL DEFAULT '',
  data_range_present boolean NOT NULL DEFAULT false,
  data_range_dataset_ref_id bigint,
  data_range_split_name text NOT NULL DEFAULT '',
  data_range_partition_id text NOT NULL DEFAULT '',
  data_range_start_ordinal bigint NOT NULL DEFAULT 0 CHECK (data_range_start_ordinal >= 0),
  data_range_end_ordinal bigint NOT NULL DEFAULT 0 CHECK (data_range_end_ordinal >= 0),
  data_range_batch_ref_id bigint,
  progress_ledger_ref_id bigint,
  metric_snapshot_ref_id bigint,
  committed_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, data_range_dataset_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, data_range_batch_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, progress_ledger_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, metric_snapshot_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (latest_update_present OR (latest_update_value = '' AND latest_update_sequence = 0)),
  CHECK (data_range_present OR (
    data_range_dataset_ref_id IS NULL AND data_range_split_name = '' AND
    data_range_partition_id = '' AND data_range_start_ordinal = 0 AND
    data_range_end_ordinal = 0 AND data_range_batch_ref_id IS NULL
  )),
  CHECK (NOT data_range_present OR data_range_end_ordinal >= data_range_start_ordinal)
);

CREATE TABLE training_runs (
  name text NOT NULL,
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 10),
  operation_id text NOT NULL,
  job_id text NOT NULL,
  scheduler_run_id text NOT NULL,
  training_recipe_ref_id bigint NOT NULL,
  dataset_release_ref_id bigint NOT NULL,
  model_release_ref_id bigint NOT NULL,
  executable_plan_ref_id bigint,
  hardware_topology_ref_id bigint,
  use_policy_ref_id bigint,
  active_fence_present boolean NOT NULL DEFAULT false,
  fence_job_id text NOT NULL DEFAULT '',
  fence_run_id text NOT NULL DEFAULT '',
  fence_attempt_id text NOT NULL DEFAULT '',
  fence_lease_epoch bigint NOT NULL DEFAULT 0 CHECK (fence_lease_epoch >= 0),
  fence_deadline timestamptz,
  fence_tenant_id text NOT NULL DEFAULT '',
  fence_project_id text NOT NULL DEFAULT '',
  fence_token_digest text NOT NULL DEFAULT '' CHECK (fence_token_digest = '' OR fence_token_digest ~ '^sha256:[0-9a-f]{64}$'),
  committed_progress_id bigint,
  latest_checkpoint_ref_id bigint,
  result_manifest_ref_id bigint,
  terminal_classification integer NOT NULL DEFAULT 0 CHECK (terminal_classification BETWEEN 0 AND 9),
  error_detail_id bigint,
  policy_classification text NOT NULL DEFAULT '',
  create_time timestamptz NOT NULL,
  start_time timestamptz,
  complete_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, operation_id),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, training_recipe_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, dataset_release_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, model_release_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, executable_plan_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, hardware_topology_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, use_policy_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, committed_progress_id) REFERENCES training_progress_snapshots(tenant_id, id),
  FOREIGN KEY (tenant_id, latest_checkpoint_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, result_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (NOT active_fence_present OR (
    fence_job_id <> '' AND fence_run_id <> '' AND fence_attempt_id <> '' AND
    fence_lease_epoch > 0 AND fence_deadline IS NOT NULL AND fence_token_digest <> ''
  )),
  CHECK (active_fence_present OR (
    fence_job_id = '' AND fence_run_id = '' AND fence_attempt_id = '' AND
    fence_lease_epoch = 0 AND fence_deadline IS NULL AND fence_tenant_id = '' AND
    fence_project_id = '' AND fence_token_digest = ''
  ))
);
CREATE INDEX training_runs_project_state_idx ON training_runs (tenant_id, project_id, state, create_time, name);

CREATE TABLE training_run_labels (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  training_run_name text NOT NULL,
  label_key text NOT NULL,
  label_value text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, training_run_name, label_key),
  FOREIGN KEY (tenant_id, project_id, training_run_name) REFERENCES training_runs(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE training_checkpoints (
  name text NOT NULL,
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL,
  training_run_name text NOT NULL,
  snapshot_epoch bigint NOT NULL CHECK (snapshot_epoch > 0),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 6),
  checkpoint_manifest_ref_id bigint,
  logical_state_ref_id bigint NOT NULL,
  committed_progress_id bigint,
  parent_checkpoint_ref_id bigint,
  topology_envelope_ref_id bigint,
  evidence_digest text NOT NULL DEFAULT '',
  evidence_subject_digest text NOT NULL DEFAULT '',
  evidence_kind text NOT NULL DEFAULT '',
  evidence_policy_digest text NOT NULL DEFAULT '',
  error_detail_id bigint,
  prepare_time timestamptz NOT NULL,
  verify_time timestamptz,
  commit_time timestamptz,
  revoke_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, training_run_name, snapshot_epoch),
  FOREIGN KEY (tenant_id, project_id, training_run_name) REFERENCES training_runs(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, checkpoint_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, logical_state_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, committed_progress_id) REFERENCES training_progress_snapshots(tenant_id, id),
  FOREIGN KEY (tenant_id, parent_checkpoint_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, topology_envelope_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (evidence_digest = '' OR evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
  CHECK (evidence_subject_digest = '' OR evidence_subject_digest ~ '^sha256:[0-9a-f]{64}$'),
  CHECK (evidence_policy_digest = '' OR evidence_policy_digest ~ '^sha256:[0-9a-f]{64}$')
);

CREATE TABLE runs (
  id text NOT NULL,
  tenant_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  job_id text NOT NULL,
  input_ref_id bigint,
  configuration_ref_id bigint,
  plan_ref_id bigint,
  status text NOT NULL CHECK (status IN ('READY','EXECUTING','SUCCEEDED','FAILED','CANCELLING','CANCELLED')),
  version bigint NOT NULL CHECK (version > 0),
  lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
  error_detail_id bigint,
  etag text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL,
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, input_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, configuration_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, plan_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id)
);

-- Training owns domain meaning while the scheduler run owns dispatch and
-- lease state. The tenant-scoped link is added after runs exists because the
-- domain table is declared earlier to support its normalized child tables.
ALTER TABLE training_runs
  ADD CONSTRAINT training_runs_scheduler_run_fk
  FOREIGN KEY (tenant_id, project_id, scheduler_run_id) REFERENCES runs(tenant_id, project_id, id);

CREATE TABLE run_output_refs (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  run_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, run_id, ordinal),
  FOREIGN KEY (tenant_id, project_id, run_id) REFERENCES runs(tenant_id, project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE attempts (
  id text NOT NULL,
  tenant_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  job_id text NOT NULL,
  run_id text NOT NULL,
  worker_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  lease_token_digest text NOT NULL CHECK (lease_token_digest ~ '^sha256:[0-9a-f]{64}$'),
  lease_expires_at timestamptz NOT NULL,
  last_heartbeat_at timestamptz NOT NULL,
  status text NOT NULL CHECK (status IN ('LEASED','ACTIVE','COMPLETED','FAILED','FENCED','CANCELLED','TIMED_OUT')),
  version bigint NOT NULL CHECK (version > 0),
  error_detail_id bigint,
  created_at timestamptz NOT NULL,
  leased_at timestamptz NOT NULL,
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, id),
  UNIQUE (tenant_id, project_id, run_id, lease_epoch),
  FOREIGN KEY (tenant_id, project_id, run_id) REFERENCES runs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, job_id) REFERENCES jobs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (lease_expires_at > leased_at)
);
CREATE UNIQUE INDEX attempts_one_active_lease_idx ON attempts (tenant_id, project_id, run_id)
  WHERE status IN ('LEASED','ACTIVE');

CREATE TABLE attempt_output_refs (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  attempt_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, attempt_id, ordinal),
  FOREIGN KEY (tenant_id, project_id, attempt_id) REFERENCES attempts(tenant_id, project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE attempt_completion_history (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  attempt_id text NOT NULL,
  worker_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  lease_token_digest text NOT NULL CHECK (lease_token_digest ~ '^sha256:[0-9a-f]{64}$'),
  accepted boolean NOT NULL,
  outcome text NOT NULL,
  recorded_at timestamptz NOT NULL,
  FOREIGN KEY (tenant_id, project_id, attempt_id) REFERENCES attempts(tenant_id, project_id, id)
);

-- Durable RunService command receipts make successful mutations replayable
-- without storing raw lease credentials or serialized mutable resources.
-- Response resources are reconstructed through the normalized identifiers;
-- acquire credentials are deterministically re-derived from token_key_id.
CREATE TABLE run_command_receipts (
  tenant_id text NOT NULL,
  command_key text NOT NULL,
  request_hash text NOT NULL CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
  action text NOT NULL CHECK (action IN (
    'run.acquire_lease','run.renew_lease','run.heartbeat','run.cancel_attempt',
    'run.expire_leases','run.commit_attempt'
  )),
  project_id text NOT NULL,
  principal_id text NOT NULL,
  worker_id text NOT NULL,
  run_id text,
  attempt_id text,
  token_key_id text NOT NULL DEFAULT '',
  observed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, command_key),
  FOREIGN KEY (tenant_id, project_id, run_id) REFERENCES runs(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, project_id, attempt_id) REFERENCES attempts(tenant_id, project_id, id),
  CHECK (token_key_id = '' OR action = 'run.acquire_lease'),
  CHECK (action <> 'run.acquire_lease' OR (run_id IS NOT NULL AND attempt_id IS NOT NULL AND token_key_id <> '')),
  CHECK (action <> 'run.expire_leases' OR (run_id IS NULL AND attempt_id IS NULL))
);

CREATE TABLE run_command_receipt_attempts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  command_key text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  attempt_id text NOT NULL,
  PRIMARY KEY (tenant_id, project_id, command_key, ordinal),
  UNIQUE (tenant_id, project_id, command_key, attempt_id),
  FOREIGN KEY (tenant_id, project_id, command_key) REFERENCES run_command_receipts(tenant_id, project_id, command_key) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, project_id, attempt_id) REFERENCES attempts(tenant_id, project_id, id)
);

CREATE TABLE artifacts (
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  tenant_id text NOT NULL,
  media_type text NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, digest)
);

CREATE TABLE idempotency_records (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  command_key text NOT NULL,
  request_hash text NOT NULL CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, command_key),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id)
);

CREATE TABLE audit_events (
  id text NOT NULL,
  tenant_id text NOT NULL,
  actor_id text NOT NULL,
  action text NOT NULL,
  subject_id text NOT NULL,
  occurred_at timestamptz NOT NULL,
  details_digest text NOT NULL,
  event_version integer NOT NULL CHECK (event_version > 0),
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  envelope_bytes bytea NOT NULL CHECK (octet_length(envelope_bytes) > 0),
  PRIMARY KEY (tenant_id, id)
);

CREATE TABLE outbox_messages (
  id text NOT NULL,
  tenant_id text NOT NULL,
  event_type text NOT NULL,
  event_version integer NOT NULL CHECK (event_version > 0),
  aggregate_type text NOT NULL,
  aggregate_id text NOT NULL,
  aggregate_sequence bigint NOT NULL CHECK (aggregate_sequence > 0),
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  envelope_bytes bytea NOT NULL CHECK (octet_length(envelope_bytes) > 0),
  delivery_epoch bigint NOT NULL DEFAULT 0 CHECK (delivery_epoch >= 0),
  publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
  claim_expires_at timestamptz,
  next_attempt_at timestamptz NOT NULL,
  last_error text NOT NULL DEFAULT '',
  delivered_at timestamptz,
  quarantined_at timestamptz,
  quarantine_reason text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, aggregate_type, aggregate_id, aggregate_sequence),
  CHECK (
    (quarantined_at IS NULL AND quarantine_reason = '') OR
    (quarantined_at IS NOT NULL AND quarantine_reason <> '')
  )
);
CREATE INDEX outbox_delivery_idx ON outbox_messages (tenant_id, next_attempt_at, created_at)
  WHERE delivered_at IS NULL AND quarantined_at IS NULL;
CREATE INDEX outbox_aggregate_predecessor_idx
  ON outbox_messages (tenant_id, aggregate_type, aggregate_id, aggregate_sequence)
  WHERE delivered_at IS NULL;

CREATE TABLE inbox_messages (
  consumer text NOT NULL,
  event_id text NOT NULL,
  tenant_id text NOT NULL,
  event_type text NOT NULL,
  event_version integer NOT NULL CHECK (event_version > 0),
  received_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, consumer, event_id)
);

-- Subscriber delivery-attempt headers are not guaranteed on every transport
-- path. Persist failures by tenant/consumer/event so retry bounds survive
-- process restarts and a successful inbox transaction can delete the counter.
CREATE TABLE inbox_delivery_failures (
  tenant_id text NOT NULL,
  consumer text NOT NULL,
  event_id text NOT NULL,
  event_type text NOT NULL,
  event_version integer NOT NULL CHECK (event_version > 0),
  attempts integer NOT NULL CHECK (attempts > 0),
  last_error text NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, consumer, event_id)
);

CREATE TABLE dead_letter_messages (
  id text NOT NULL,
  tenant_id text NOT NULL,
  event_id text NOT NULL,
  source text NOT NULL CHECK (source IN ('OUTBOX','INBOX')),
  event_type text NOT NULL,
  event_version integer NOT NULL CHECK (event_version > 0),
  attempts integer NOT NULL CHECK (attempts > 0),
  reason text NOT NULL,
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  envelope_bytes bytea NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

-- FORCE prevents the table owner from bypassing tenant policies. Production
-- application roles must additionally be NOSUPERUSER and NOBYPASSRLS.
ALTER TABLE artifact_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_references FORCE ROW LEVEL SECURITY;
ALTER TABLE resource_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE resource_references FORCE ROW LEVEL SECURITY;
ALTER TABLE error_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_details FORCE ROW LEVEL SECURITY;
ALTER TABLE error_field_violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_field_violations FORCE ROW LEVEL SECURITY;
ALTER TABLE error_precondition_violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_precondition_violations FORCE ROW LEVEL SECURITY;
ALTER TABLE operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations FORCE ROW LEVEL SECURITY;
ALTER TABLE operation_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE operation_revisions FORCE ROW LEVEL SECURITY;
ALTER TABLE training_progress_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_progress_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE training_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE training_run_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_run_labels FORCE ROW LEVEL SECURITY;
ALTER TABLE training_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE training_checkpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs FORCE ROW LEVEL SECURITY;
ALTER TABLE run_output_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_output_refs FORCE ROW LEVEL SECURITY;
ALTER TABLE attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE attempt_output_refs ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempt_output_refs FORCE ROW LEVEL SECURITY;
ALTER TABLE attempt_completion_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempt_completion_history FORCE ROW LEVEL SECURITY;
ALTER TABLE run_command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_command_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE run_command_receipt_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_command_receipt_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts FORCE ROW LEVEL SECURITY;
ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_records FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
ALTER TABLE outbox_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE inbox_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE inbox_delivery_failures ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_delivery_failures FORCE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_messages FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_scope_artifact_references ON artifact_references
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_resource_references ON resource_references
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_error_details ON error_details
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_error_field_violations ON error_field_violations
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_error_precondition_violations ON error_precondition_violations
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_operations ON operations
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_operation_revisions ON operation_revisions
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_training_progress ON training_progress_snapshots
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_training_runs ON training_runs
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_training_run_labels ON training_run_labels
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_training_checkpoints ON training_checkpoints
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_jobs ON jobs
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_runs ON runs
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_run_output_refs ON run_output_refs
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_attempts ON attempts
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_attempt_output_refs ON attempt_output_refs
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_attempt_completion_history ON attempt_completion_history
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_run_command_receipts ON run_command_receipts
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_run_command_receipt_attempts ON run_command_receipt_attempts
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_artifacts ON artifacts
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_idempotency ON idempotency_records
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_audit ON audit_events
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_outbox ON outbox_messages
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_inbox ON inbox_messages
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_inbox_delivery_failures ON inbox_delivery_failures
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY tenant_scope_dead_letter ON dead_letter_messages
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));

COMMIT;
