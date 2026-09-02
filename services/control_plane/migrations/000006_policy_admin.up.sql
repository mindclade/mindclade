BEGIN;

-- Mutable policy resources own lifecycle metadata while their immutable
-- documents and activated snapshots remain normalized references. The shared
-- snapshot and decision authorities are created by 000004 and are not
-- duplicated here.
CREATE TABLE use_policies (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  display_name text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  policy_document_ref_id bigint NOT NULL,
  active_snapshot_id bigint,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  delete_time timestamptz,
  revocation_reason_code text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  FOREIGN KEY (tenant_id, policy_document_ref_id)
    REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, active_snapshot_id)
    REFERENCES policy_snapshot_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND display_name <> ''),
  CHECK (update_time >= create_time),
  CHECK (delete_time IS NULL OR delete_time >= create_time),
  CHECK ((state = 4) = (revocation_reason_code <> ''))
);

CREATE TABLE use_policy_permitted_purposes (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  policy_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  value text NOT NULL CHECK (value <> ''),
  PRIMARY KEY (tenant_id, project_id, policy_name, ordinal),
  UNIQUE (tenant_id, project_id, policy_name, value),
  FOREIGN KEY (tenant_id, project_id, policy_name)
    REFERENCES use_policies(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE use_policy_permitted_capabilities (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  policy_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  value text NOT NULL CHECK (value <> ''),
  PRIMARY KEY (tenant_id, project_id, policy_name, ordinal),
  UNIQUE (tenant_id, project_id, policy_name, value),
  FOREIGN KEY (tenant_id, project_id, policy_name)
    REFERENCES use_policies(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE use_policy_prohibited_capabilities (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  policy_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  value text NOT NULL CHECK (value <> ''),
  PRIMARY KEY (tenant_id, project_id, policy_name, ordinal),
  UNIQUE (tenant_id, project_id, policy_name, value),
  FOREIGN KEY (tenant_id, project_id, policy_name)
    REFERENCES use_policies(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE use_policy_accepted_classifications (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  policy_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  value text NOT NULL CHECK (value <> ''),
  PRIMARY KEY (tenant_id, project_id, policy_name, ordinal),
  UNIQUE (tenant_id, project_id, policy_name, value),
  FOREIGN KEY (tenant_id, project_id, policy_name)
    REFERENCES use_policies(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE use_policy_approval_requirements (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  policy_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  action text NOT NULL,
  risk_class integer NOT NULL CHECK (risk_class BETWEEN 1 AND 4),
  minimum_independent_approvers integer NOT NULL CHECK (minimum_independent_approvers > 0),
  step_up_authentication_required boolean NOT NULL,
  maximum_receipt_age_seconds bigint,
  maximum_receipt_age_nanos integer,
  single_use boolean NOT NULL,
  PRIMARY KEY (tenant_id, project_id, policy_name, ordinal),
  UNIQUE (tenant_id, project_id, policy_name, action),
  FOREIGN KEY (tenant_id, project_id, policy_name)
    REFERENCES use_policies(tenant_id, project_id, name) ON DELETE CASCADE,
  CHECK (action <> ''),
  CHECK ((maximum_receipt_age_seconds IS NULL) = (maximum_receipt_age_nanos IS NULL)),
  CHECK (maximum_receipt_age_nanos IS NULL OR maximum_receipt_age_nanos BETWEEN 0 AND 999999999),
  CHECK (maximum_receipt_age_seconds IS NULL OR maximum_receipt_age_seconds >= 0)
);

-- Administrative tenant and project projections are deliberately separate
-- from database tenancy mechanics. They preserve every protobuf field through
-- normalized child tables and references.
CREATE TABLE administrative_tenants (
  tenant_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  display_name text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  default_classification text NOT NULL DEFAULT '',
  billing_account_ref_id bigint,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  delete_time timestamptz,
  PRIMARY KEY (tenant_id),
  UNIQUE (tenant_id, name),
  UNIQUE (tenant_id, uid),
  FOREIGN KEY (tenant_id, billing_account_ref_id)
    REFERENCES resource_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND display_name <> ''),
  CHECK (update_time >= create_time),
  CHECK (delete_time IS NULL OR delete_time >= create_time)
);

CREATE TABLE administrative_tenant_policy_snapshots (
  tenant_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, ordinal),
  FOREIGN KEY (tenant_id) REFERENCES administrative_tenants(tenant_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id)
    REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE administrative_tenant_allowed_regions (
  tenant_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  region text NOT NULL CHECK (region <> ''),
  PRIMARY KEY (tenant_id, ordinal),
  UNIQUE (tenant_id, region),
  FOREIGN KEY (tenant_id) REFERENCES administrative_tenants(tenant_id) ON DELETE CASCADE
);

CREATE TABLE administrative_tenant_labels (
  tenant_id text NOT NULL,
  label_key text NOT NULL CHECK (label_key <> '' AND length(label_key) <= 128),
  label_value text NOT NULL CHECK (length(label_value) <= 256),
  PRIMARY KEY (tenant_id, label_key),
  FOREIGN KEY (tenant_id) REFERENCES administrative_tenants(tenant_id) ON DELETE CASCADE
);

CREATE TABLE administrative_tenant_annotations (
  tenant_id text NOT NULL,
  annotation_key text NOT NULL CHECK (annotation_key <> '' AND length(annotation_key) <= 128),
  annotation_value text NOT NULL CHECK (length(annotation_value) <= 4096),
  PRIMARY KEY (tenant_id, annotation_key),
  FOREIGN KEY (tenant_id) REFERENCES administrative_tenants(tenant_id) ON DELETE CASCADE
);

CREATE TABLE administrative_projects (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  tenant_ref_id bigint NOT NULL,
  display_name text NOT NULL,
  purpose text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  default_classification text NOT NULL DEFAULT '',
  quota_present boolean NOT NULL,
  maximum_concurrent_jobs bigint NOT NULL DEFAULT 0 CHECK (maximum_concurrent_jobs BETWEEN 0 AND 4294967295),
  maximum_concurrent_accelerator_jobs bigint NOT NULL DEFAULT 0 CHECK (maximum_concurrent_accelerator_jobs BETWEEN 0 AND 4294967295),
  maximum_storage_bytes numeric(20,0) NOT NULL DEFAULT 0 CHECK (maximum_storage_bytes >= 0),
  maximum_monthly_spend_micros numeric(20,0) NOT NULL DEFAULT 0 CHECK (maximum_monthly_spend_micros >= 0),
  maximum_daily_inference_work_units numeric(20,0) NOT NULL DEFAULT 0 CHECK (maximum_daily_inference_work_units >= 0),
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  delete_time timestamptz,
  PRIMARY KEY (tenant_id, project_id),
  UNIQUE (tenant_id, name),
  UNIQUE (tenant_id, uid),
  FOREIGN KEY (tenant_id) REFERENCES administrative_tenants(tenant_id),
  FOREIGN KEY (tenant_id, tenant_ref_id) REFERENCES resource_references(tenant_id, id),
  CHECK (project_id <> '' AND name <> '' AND uid <> '' AND display_name <> '' AND purpose <> ''),
  CHECK (update_time >= create_time),
  CHECK (delete_time IS NULL OR delete_time >= create_time)
);

CREATE TABLE administrative_project_policy_snapshots (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  policy_snapshot_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, ordinal),
  FOREIGN KEY (tenant_id, project_id)
    REFERENCES administrative_projects(tenant_id, project_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, policy_snapshot_id)
    REFERENCES policy_snapshot_references(tenant_id, id)
);

CREATE TABLE administrative_project_labels (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  label_key text NOT NULL CHECK (label_key <> '' AND length(label_key) <= 128),
  label_value text NOT NULL CHECK (length(label_value) <= 256),
  PRIMARY KEY (tenant_id, project_id, label_key),
  FOREIGN KEY (tenant_id, project_id)
    REFERENCES administrative_projects(tenant_id, project_id) ON DELETE CASCADE
);

CREATE TABLE administrative_project_annotations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  annotation_key text NOT NULL CHECK (annotation_key <> '' AND length(annotation_key) <= 128),
  annotation_value text NOT NULL CHECK (length(annotation_value) <= 4096),
  PRIMARY KEY (tenant_id, project_id, annotation_key),
  FOREIGN KEY (tenant_id, project_id)
    REFERENCES administrative_projects(tenant_id, project_id) ON DELETE CASCADE
);

-- This payload-minimized query projection contains no serialized contract
-- model and is immutable evidence. Sensitive details remain digest references.
CREATE TABLE administrative_audit_records (
  tenant_id text NOT NULL,
  event_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  occurred_at timestamptz NOT NULL,
  actor_principal_ref text NOT NULL,
  delegated_principal_ref text NOT NULL DEFAULT '',
  authentication_context_digest text NOT NULL DEFAULT '' CHECK (authentication_context_digest = '' OR authentication_context_digest ~ '^sha256:[0-9a-f]{64}$'),
  request_origin_class text NOT NULL DEFAULT '',
  action text NOT NULL,
  resource_ref_id bigint,
  authorization_decision_digest text NOT NULL DEFAULT '' CHECK (authorization_decision_digest = '' OR authorization_decision_digest ~ '^sha256:[0-9a-f]{64}$'),
  before_revision text NOT NULL DEFAULT '',
  after_revision text NOT NULL DEFAULT '',
  policy_reason_code text NOT NULL DEFAULT '',
  result integer NOT NULL CHECK (result BETWEEN 1 AND 4),
  failure_class text NOT NULL DEFAULT '',
  request_id text NOT NULL DEFAULT '',
  trace_id text NOT NULL DEFAULT '',
  detail_digest text NOT NULL CHECK (detail_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, event_id),
  FOREIGN KEY (tenant_id, resource_ref_id) REFERENCES resource_references(tenant_id, id),
  CHECK (actor_principal_ref <> '' AND action <> '')
);

CREATE TABLE audit_exports (
  tenant_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  query_digest text NOT NULL CHECK (query_digest ~ '^sha256:[0-9a-f]{64}$'),
  query_parent text NOT NULL,
  query_start_time timestamptz NOT NULL,
  query_end_time timestamptz NOT NULL,
  query_request_id text NOT NULL DEFAULT '',
  query_trace_id text NOT NULL DEFAULT '',
  artifact_ref_id bigint,
  failure_code text NOT NULL DEFAULT '',
  operation_id text NOT NULL,
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  expire_time timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  FOREIGN KEY (tenant_id, artifact_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, project_id, operation_id) REFERENCES operations(tenant_id, project_id, id),
  CHECK (name <> '' AND uid <> '' AND query_parent <> ''),
  CHECK (query_end_time > query_start_time),
  CHECK (update_time >= create_time AND expire_time > create_time),
  CHECK ((state = 3) = (artifact_ref_id IS NOT NULL)),
  CHECK ((state = 4) = (failure_code <> ''))
);

CREATE TABLE audit_export_actor_filters (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  export_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  actor_principal_ref text NOT NULL CHECK (actor_principal_ref <> ''),
  PRIMARY KEY (tenant_id, project_id, export_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, export_name)
    REFERENCES audit_exports(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE audit_export_action_filters (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  export_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  action text NOT NULL CHECK (action <> ''),
  PRIMARY KEY (tenant_id, project_id, export_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, export_name)
    REFERENCES audit_exports(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE audit_export_resource_filters (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  export_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  resource_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, export_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, export_name)
    REFERENCES audit_exports(tenant_id, project_id, name) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, resource_ref_id) REFERENCES resource_references(tenant_id, id)
);

CREATE TABLE audit_export_result_filters (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  export_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  result integer NOT NULL CHECK (result BETWEEN 1 AND 4),
  PRIMARY KEY (tenant_id, project_id, export_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, export_name)
    REFERENCES audit_exports(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE audit_export_reason_filters (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  export_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  reason_code text NOT NULL CHECK (reason_code <> ''),
  PRIMARY KEY (tenant_id, project_id, export_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, export_name)
    REFERENCES audit_exports(tenant_id, project_id, name) ON DELETE CASCADE
);

-- All mutating commands are replay-bound to tenant, project, authenticated
-- principal, semantic action, key, and canonical digest. Exactly one durable
-- result is referenced.
CREATE TABLE policy_admin_command_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL DEFAULT '',
  principal_id text NOT NULL,
  action text NOT NULL,
  idempotency_key text NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text,
  decision_name text,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, principal_id, action, idempotency_key),
  FOREIGN KEY (tenant_id, project_id, operation_id)
    REFERENCES operations(tenant_id, project_id, id),
  FOREIGN KEY (tenant_id, decision_name)
    REFERENCES authorization_decisions(tenant_id, name),
  CHECK (principal_id <> '' AND action <> '' AND idempotency_key <> ''),
  CHECK ((operation_id IS NOT NULL)::integer + (decision_name IS NOT NULL)::integer = 1)
);

CREATE INDEX use_policies_list_idx
  ON use_policies (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX administrative_projects_list_idx
  ON administrative_projects (tenant_id, create_time DESC, name DESC);
CREATE INDEX administrative_audit_records_query_idx
  ON administrative_audit_records (tenant_id, project_id, occurred_at DESC, event_id DESC);
CREATE INDEX audit_exports_list_idx
  ON audit_exports (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX policy_admin_receipts_operation_idx
  ON policy_admin_command_receipts (tenant_id, project_id, operation_id)
  WHERE operation_id IS NOT NULL;

CREATE FUNCTION guard_policy_admin_resource_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.name IS DISTINCT FROM OLD.name OR
     NEW.uid IS DISTINCT FROM OLD.uid OR NEW.create_time IS DISTINCT FROM OLD.create_time THEN
    RAISE EXCEPTION '% identity is immutable', TG_TABLE_NAME USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.revision <> OLD.revision + 1 OR NEW.etag = OLD.etag OR NEW.update_time < OLD.update_time THEN
    RAISE EXCEPTION '% requires monotonic revision, etag, and update time', TG_TABLE_NAME USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION guard_use_policy_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.policy_document_ref_id IS DISTINCT FROM OLD.policy_document_ref_id THEN
    RAISE EXCEPTION 'use_policies ownership and document are immutable' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION guard_administrative_project_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.tenant_ref_id IS DISTINCT FROM OLD.tenant_ref_id THEN
    RAISE EXCEPTION 'administrative_projects ownership is immutable' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION guard_audit_export_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.query_digest IS DISTINCT FROM OLD.query_digest OR
     NEW.query_parent IS DISTINCT FROM OLD.query_parent OR
     NEW.query_start_time IS DISTINCT FROM OLD.query_start_time OR
     NEW.query_end_time IS DISTINCT FROM OLD.query_end_time OR
     NEW.query_request_id IS DISTINCT FROM OLD.query_request_id OR
     NEW.query_trace_id IS DISTINCT FROM OLD.query_trace_id OR
     NEW.operation_id IS DISTINCT FROM OLD.operation_id OR
     NEW.expire_time IS DISTINCT FROM OLD.expire_time THEN
    RAISE EXCEPTION 'audit_exports request and ownership are immutable' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER use_policies_revision_guard BEFORE UPDATE ON use_policies
  FOR EACH ROW EXECUTE FUNCTION guard_policy_admin_resource_update();
CREATE TRIGGER use_policies_ownership_guard BEFORE UPDATE ON use_policies
  FOR EACH ROW EXECUTE FUNCTION guard_use_policy_update();
CREATE TRIGGER administrative_tenants_revision_guard BEFORE UPDATE ON administrative_tenants
  FOR EACH ROW EXECUTE FUNCTION guard_policy_admin_resource_update();
CREATE TRIGGER administrative_projects_revision_guard BEFORE UPDATE ON administrative_projects
  FOR EACH ROW EXECUTE FUNCTION guard_policy_admin_resource_update();
CREATE TRIGGER administrative_projects_ownership_guard BEFORE UPDATE ON administrative_projects
  FOR EACH ROW EXECUTE FUNCTION guard_administrative_project_update();
CREATE TRIGGER audit_exports_revision_guard BEFORE UPDATE ON audit_exports
  FOR EACH ROW EXECUTE FUNCTION guard_policy_admin_resource_update();
CREATE TRIGGER audit_exports_request_guard BEFORE UPDATE ON audit_exports
  FOR EACH ROW EXECUTE FUNCTION guard_audit_export_update();

CREATE FUNCTION reject_policy_admin_immutable_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is immutable', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END;
$$;
CREATE TRIGGER administrative_audit_records_immutable BEFORE UPDATE OR DELETE ON administrative_audit_records
  FOR EACH ROW EXECUTE FUNCTION reject_policy_admin_immutable_change();
CREATE TRIGGER policy_admin_command_receipts_immutable BEFORE UPDATE OR DELETE ON policy_admin_command_receipts
  FOR EACH ROW EXECUTE FUNCTION reject_policy_admin_immutable_change();
CREATE TRIGGER audit_export_actor_filters_immutable BEFORE UPDATE OR DELETE ON audit_export_actor_filters
  FOR EACH ROW EXECUTE FUNCTION reject_policy_admin_immutable_change();
CREATE TRIGGER audit_export_action_filters_immutable BEFORE UPDATE OR DELETE ON audit_export_action_filters
  FOR EACH ROW EXECUTE FUNCTION reject_policy_admin_immutable_change();
CREATE TRIGGER audit_export_resource_filters_immutable BEFORE UPDATE OR DELETE ON audit_export_resource_filters
  FOR EACH ROW EXECUTE FUNCTION reject_policy_admin_immutable_change();
CREATE TRIGGER audit_export_result_filters_immutable BEFORE UPDATE OR DELETE ON audit_export_result_filters
  FOR EACH ROW EXECUTE FUNCTION reject_policy_admin_immutable_change();
CREATE TRIGGER audit_export_reason_filters_immutable BEFORE UPDATE OR DELETE ON audit_export_reason_filters
  FOR EACH ROW EXECUTE FUNCTION reject_policy_admin_immutable_change();

ALTER TABLE use_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE use_policy_permitted_purposes ENABLE ROW LEVEL SECURITY;
ALTER TABLE use_policy_permitted_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE use_policy_prohibited_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE use_policy_accepted_classifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE use_policy_approval_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_policy_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_allowed_regions ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_project_policy_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_project_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_project_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE administrative_audit_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_export_actor_filters ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_export_action_filters ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_export_resource_filters ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_export_result_filters ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_export_reason_filters ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_admin_command_receipts ENABLE ROW LEVEL SECURITY;

ALTER TABLE use_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE use_policy_permitted_purposes FORCE ROW LEVEL SECURITY;
ALTER TABLE use_policy_permitted_capabilities FORCE ROW LEVEL SECURITY;
ALTER TABLE use_policy_prohibited_capabilities FORCE ROW LEVEL SECURITY;
ALTER TABLE use_policy_accepted_classifications FORCE ROW LEVEL SECURITY;
ALTER TABLE use_policy_approval_requirements FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_policy_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_allowed_regions FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_labels FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_tenant_annotations FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_projects FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_project_policy_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_project_labels FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_project_annotations FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_audit_records FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_exports FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_export_actor_filters FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_export_action_filters FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_export_resource_filters FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_export_result_filters FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_export_reason_filters FORCE ROW LEVEL SECURITY;
ALTER TABLE policy_admin_command_receipts FORCE ROW LEVEL SECURITY;

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'use_policies','use_policy_permitted_purposes','use_policy_permitted_capabilities',
    'use_policy_prohibited_capabilities','use_policy_accepted_classifications',
    'use_policy_approval_requirements','administrative_tenants',
    'administrative_tenant_policy_snapshots','administrative_tenant_allowed_regions',
    'administrative_tenant_labels','administrative_tenant_annotations',
    'administrative_projects','administrative_project_policy_snapshots',
    'administrative_project_labels','administrative_project_annotations',
    'administrative_audit_records','audit_exports','audit_export_actor_filters',
    'audit_export_action_filters','audit_export_resource_filters',
    'audit_export_result_filters','audit_export_reason_filters','policy_admin_command_receipts'
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
