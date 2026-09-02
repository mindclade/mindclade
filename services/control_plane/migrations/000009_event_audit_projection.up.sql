BEGIN;

-- This is a payload-minimized, immutable semantic projection of the
-- authoritative protobuf event stream. The inbox foreign key proves that a
-- row can only be created in the same transaction as durable deduplication.
CREATE TABLE event_audit_projection (
  tenant_id text NOT NULL,
  consumer text NOT NULL,
  event_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  event_type text NOT NULL,
  event_version bigint NOT NULL CHECK (event_version > 0 AND event_version <= 4294967295),
  occurred_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL,
  producer text NOT NULL,
  subject_resource_type text NOT NULL,
  subject_resource_id text NOT NULL,
  subject_name text NOT NULL DEFAULT '',
  resource_ref_id bigint,
  aggregate_type text NOT NULL,
  aggregate_id text NOT NULL,
  aggregate_sequence bigint NOT NULL CHECK (aggregate_sequence > 0),
  semantic_action text NOT NULL,
  semantic_outcome text NOT NULL DEFAULT '',
  audit_result integer NOT NULL CHECK (audit_result BETWEEN 1 AND 4),
  actor_principal_ref text NOT NULL,
  reason_code text NOT NULL DEFAULT '',
  request_id text NOT NULL DEFAULT '',
  trace_id text NOT NULL DEFAULT '',
  correlation_id text NOT NULL DEFAULT '',
  causation_id text NOT NULL DEFAULT '',
  job_id text NOT NULL DEFAULT '',
  run_id text NOT NULL DEFAULT '',
  payload_digest text NOT NULL CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
  payload_content_type text NOT NULL CHECK (payload_content_type = 'application/x-protobuf; deterministic=true'),
  classification integer NOT NULL CHECK (classification BETWEEN 1 AND 3),
  PRIMARY KEY (tenant_id,event_id),
  UNIQUE (tenant_id,aggregate_type,aggregate_id,aggregate_sequence),
  UNIQUE (tenant_id,event_id,aggregate_type,aggregate_id,aggregate_sequence,occurred_at),
  FOREIGN KEY (tenant_id,consumer,event_id)
    REFERENCES inbox_messages (tenant_id,consumer,event_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id,resource_ref_id)
    REFERENCES resource_references (tenant_id,id) ON DELETE RESTRICT,
  CHECK (tenant_id <> '' AND length(tenant_id) <= 255),
  CHECK (consumer <> '' AND length(consumer) <= 255),
  CHECK (event_id <> '' AND length(event_id) <= 512),
  CHECK (project_id = '' OR length(project_id) <= 255),
  CHECK (event_type <> '' AND length(event_type) <= 255),
  CHECK (producer <> '' AND length(producer) <= 255),
  CHECK (subject_resource_type <> '' AND length(subject_resource_type) <= 255),
  CHECK (subject_resource_id <> '' AND length(subject_resource_id) <= 1024),
  CHECK (subject_name = '' OR length(subject_name) <= 2048),
  CHECK (aggregate_type <> '' AND length(aggregate_type) <= 255),
  CHECK (aggregate_id <> '' AND length(aggregate_id) <= 2048),
  CHECK (semantic_action <> '' AND length(semantic_action) <= 512),
  CHECK (semantic_outcome <> '' AND length(semantic_outcome) <= 255),
  CHECK (actor_principal_ref <> '' AND length(actor_principal_ref) <= 512),
  CHECK (length(reason_code) <= 255 AND length(request_id) <= 512 AND length(trace_id) <= 512),
  CHECK (length(correlation_id) <= 512 AND length(causation_id) <= 512),
  CHECK (length(job_id) <= 512 AND length(run_id) <= 512),
  -- received_at is an observation from another host and may be earlier than
  -- recorded_at during clock skew; aggregate_sequence provides ordering.
  CHECK (recorded_at >= occurred_at)
);

-- One locked row per aggregate enforces contiguous processing after the first
-- retained event. baseline_sequence is explicit because a new subscription
-- may begin after prior events have expired from Pub/Sub retention.
CREATE TABLE event_audit_projection_heads (
  tenant_id text NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id text NOT NULL,
  baseline_sequence bigint NOT NULL CHECK (baseline_sequence > 0),
  last_sequence bigint NOT NULL CHECK (last_sequence >= baseline_sequence),
  last_event_id text NOT NULL,
  last_occurred_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id,aggregate_type,aggregate_id),
  FOREIGN KEY (tenant_id,last_event_id,aggregate_type,aggregate_id,last_sequence,last_occurred_at)
    REFERENCES event_audit_projection
      (tenant_id,event_id,aggregate_type,aggregate_id,aggregate_sequence,occurred_at)
    ON DELETE RESTRICT,
  CHECK (tenant_id <> '' AND length(tenant_id) <= 255),
  CHECK (aggregate_type <> '' AND length(aggregate_type) <= 255),
  CHECK (aggregate_id <> '' AND length(aggregate_id) <= 2048),
  CHECK (last_event_id <> '' AND length(last_event_id) <= 512)
);

CREATE INDEX event_audit_projection_query_idx
  ON event_audit_projection (tenant_id,project_id,occurred_at DESC,event_id DESC);
CREATE INDEX event_audit_projection_type_query_idx
  ON event_audit_projection (tenant_id,event_type,occurred_at DESC,event_id DESC);
CREATE INDEX event_audit_projection_correlation_idx
  ON event_audit_projection (tenant_id,correlation_id,occurred_at DESC)
  WHERE correlation_id <> '';

CREATE FUNCTION reject_event_audit_projection_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'event_audit_projection is immutable' USING ERRCODE = 'check_violation';
END;
$$;

CREATE FUNCTION guard_event_audit_projection_head_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'event projection aggregate heads cannot be deleted'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR
     NEW.aggregate_type IS DISTINCT FROM OLD.aggregate_type OR
     NEW.aggregate_id IS DISTINCT FROM OLD.aggregate_id OR
     NEW.baseline_sequence IS DISTINCT FROM OLD.baseline_sequence THEN
    RAISE EXCEPTION 'event projection aggregate identity and baseline are immutable'
      USING ERRCODE = 'check_violation';
  END IF;
  -- Sequence, not either host's wall clock, is the ordering authority.
  IF NEW.last_sequence <> OLD.last_sequence + 1 OR
     NEW.last_event_id = OLD.last_event_id THEN
    RAISE EXCEPTION 'event projection aggregate head must advance exactly once'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER event_audit_projection_immutable
  BEFORE UPDATE OR DELETE ON event_audit_projection
  FOR EACH ROW EXECUTE FUNCTION reject_event_audit_projection_change();
CREATE TRIGGER event_audit_projection_head_monotonic
  BEFORE UPDATE OR DELETE ON event_audit_projection_heads
  FOR EACH ROW EXECUTE FUNCTION guard_event_audit_projection_head_update();

ALTER TABLE event_audit_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_audit_projection FORCE ROW LEVEL SECURITY;
ALTER TABLE event_audit_projection_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_audit_projection_heads FORCE ROW LEVEL SECURITY;

CREATE POLICY event_audit_projection_tenant_policy ON event_audit_projection
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));
CREATE POLICY event_audit_projection_heads_tenant_policy ON event_audit_projection_heads
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));

COMMIT;
