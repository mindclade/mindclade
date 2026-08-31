BEGIN;

CREATE TABLE operations (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  job_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLING','CANCELLED')),
  version bigint NOT NULL CHECK (version > 0),
  request_hash text NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);

CREATE TABLE jobs (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  desired_state text NOT NULL CHECK (desired_state IN ('ACCEPTED','QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
  version bigint NOT NULL CHECK (version > 0),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);
ALTER TABLE jobs ADD CONSTRAINT jobs_tenant_id_key UNIQUE (tenant_id, id);
ALTER TABLE operations ADD CONSTRAINT operations_tenant_id_key UNIQUE (tenant_id, id);
ALTER TABLE operations ADD CONSTRAINT operations_job_tenant_fk FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id);
CREATE TABLE runs (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  job_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('CREATED','READY','EXECUTING','COMPLETED','FAILED','CANCELLED')),
  version bigint NOT NULL CHECK (version > 0),
  lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);
ALTER TABLE runs ADD CONSTRAINT runs_tenant_id_key UNIQUE (tenant_id, id);
ALTER TABLE runs ADD CONSTRAINT runs_job_tenant_fk FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id);
CREATE TABLE attempts (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  run_id text NOT NULL,
  lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
  status text NOT NULL CHECK (status IN ('LEASED','ACTIVE','COMPLETED','FAILED','FENCED','CANCELLED')),
  created_at timestamptz NOT NULL,
  UNIQUE (tenant_id, run_id, lease_epoch),
  FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id)
);
CREATE TABLE attempt_completion_history (
  id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  attempt_id text NOT NULL,
  lease_epoch bigint NOT NULL,
  accepted boolean NOT NULL,
  outcome text NOT NULL,
  recorded_at timestamptz NOT NULL
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
  request_hash text NOT NULL,
  operation_id text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, command_key)
);
ALTER TABLE idempotency_records ADD CONSTRAINT idempotency_operation_tenant_fk FOREIGN KEY (tenant_id, operation_id) REFERENCES operations(tenant_id, id);
CREATE TABLE audit_events (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  actor_id text NOT NULL,
  action text NOT NULL,
  subject_id text NOT NULL,
  occurred_at timestamptz NOT NULL,
  details_digest text NOT NULL
);
CREATE TABLE outbox_messages (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  event_type text NOT NULL,
  event_version integer NOT NULL CHECK (event_version > 0),
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  envelope_bytes bytea NOT NULL CHECK (octet_length(envelope_bytes) > 0),
  delivery_epoch bigint NOT NULL DEFAULT 0,
  delivered_at timestamptz,
  created_at timestamptz NOT NULL
);
CREATE TABLE inbox_messages (
  consumer text NOT NULL,
  event_id text NOT NULL,
  tenant_id text NOT NULL,
  received_at timestamptz NOT NULL,
  PRIMARY KEY (consumer, event_id)
);
CREATE TABLE dead_letter_messages (
  id text PRIMARY KEY,
  tenant_id text NOT NULL,
  event_id text NOT NULL,
  reason text NOT NULL,
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  envelope_bytes bytea NOT NULL CHECK (octet_length(envelope_bytes) > 0),
  created_at timestamptz NOT NULL
);

ALTER TABLE operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_scope_operations ON operations USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_jobs ON jobs USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_runs ON runs USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_attempts ON attempts USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_artifacts ON artifacts USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_idempotency ON idempotency_records USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_audit ON audit_events USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_outbox ON outbox_messages USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_inbox ON inbox_messages USING (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY tenant_scope_dead_letter ON dead_letter_messages USING (tenant_id = current_setting('app.tenant_id', true));

COMMIT;
