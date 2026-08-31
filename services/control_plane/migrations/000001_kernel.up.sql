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
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, input_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, configuration_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE operations (
  id text NOT NULL,
  tenant_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  job_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLING','CANCELLED')),
  version bigint NOT NULL CHECK (version > 0),
  done boolean NOT NULL,
  etag text NOT NULL DEFAULT '',
  result_ref_id bigint,
  error_detail_id bigint,
  request_hash text NOT NULL CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id),
  FOREIGN KEY (tenant_id, result_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (done = (status IN ('SUCCEEDED','FAILED','CANCELLED')))
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
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id),
  FOREIGN KEY (tenant_id, input_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, configuration_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, plan_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id)
);

CREATE TABLE run_output_refs (
  tenant_id text NOT NULL,
  run_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, run_id, ordinal),
  FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id) ON DELETE CASCADE,
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
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, run_id, lease_epoch),
  FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id),
  FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (lease_expires_at > leased_at)
);

CREATE TABLE attempt_output_refs (
  tenant_id text NOT NULL,
  attempt_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  artifact_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, attempt_id, ordinal),
  FOREIGN KEY (tenant_id, attempt_id) REFERENCES attempts(tenant_id, id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id)
);

CREATE TABLE attempt_completion_history (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id text NOT NULL,
  attempt_id text NOT NULL,
  worker_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  lease_token_digest text NOT NULL CHECK (lease_token_digest ~ '^sha256:[0-9a-f]{64}$'),
  accepted boolean NOT NULL,
  outcome text NOT NULL,
  recorded_at timestamptz NOT NULL,
  FOREIGN KEY (tenant_id, attempt_id) REFERENCES attempts(tenant_id, id)
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
  command_key text NOT NULL,
  request_hash text NOT NULL CHECK (request_hash ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, command_key),
  FOREIGN KEY (tenant_id, operation_id) REFERENCES operations(tenant_id, id)
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
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  envelope_bytes bytea NOT NULL CHECK (octet_length(envelope_bytes) > 0),
  delivery_epoch bigint NOT NULL DEFAULT 0 CHECK (delivery_epoch >= 0),
  publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
  claim_expires_at timestamptz,
  next_attempt_at timestamptz NOT NULL,
  last_error text NOT NULL DEFAULT '',
  delivered_at timestamptz,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id)
);
CREATE INDEX outbox_delivery_idx ON outbox_messages (tenant_id, next_attempt_at, created_at)
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

CREATE TABLE dead_letter_messages (
  id text NOT NULL,
  tenant_id text NOT NULL,
  event_id text NOT NULL,
  reason text NOT NULL,
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  envelope_bytes bytea NOT NULL CHECK (octet_length(envelope_bytes) > 0),
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id)
);

-- FORCE prevents the table owner from bypassing tenant policies. Production
-- application roles must additionally be NOSUPERUSER and NOBYPASSRLS.
ALTER TABLE artifact_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_references FORCE ROW LEVEL SECURITY;
ALTER TABLE error_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_details FORCE ROW LEVEL SECURITY;
ALTER TABLE error_field_violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_field_violations FORCE ROW LEVEL SECURITY;
ALTER TABLE error_precondition_violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_precondition_violations FORCE ROW LEVEL SECURITY;
ALTER TABLE operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations FORCE ROW LEVEL SECURITY;
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
ALTER TABLE dead_letter_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_messages FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_scope_artifact_references ON artifact_references
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
CREATE POLICY tenant_scope_dead_letter ON dead_letter_messages
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));

COMMIT;
