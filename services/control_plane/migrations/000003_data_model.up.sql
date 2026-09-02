BEGIN;

-- Dataset and model aggregates are normalized mutable state. Protobuf bytes are
-- deliberately absent here; only immutable audit/outbox delivery records use
-- serialized envelopes in the kernel tables created by 000001.
CREATE TABLE datasets (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  display_name text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 4),
  policy_classification text NOT NULL DEFAULT '',
  create_time timestamptz NOT NULL,
  update_time timestamptz,
  delete_time timestamptz,
  current_release_name text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  CHECK (tenant_id <> '' AND project_id <> '' AND name <> '' AND uid <> ''),
  CHECK (update_time IS NULL OR update_time >= create_time),
  CHECK (delete_time IS NULL OR delete_time >= create_time)
);

CREATE TABLE dataset_labels (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  dataset_name text NOT NULL,
  label_key text NOT NULL CHECK (label_key <> '' AND length(label_key) <= 128),
  label_value text NOT NULL CHECK (length(label_value) <= 256),
  PRIMARY KEY (tenant_id, project_id, dataset_name, label_key),
  FOREIGN KEY (tenant_id, project_id, dataset_name)
    REFERENCES datasets(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE dataset_annotations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  dataset_name text NOT NULL,
  annotation_key text NOT NULL CHECK (annotation_key <> '' AND length(annotation_key) <= 128),
  annotation_value text NOT NULL CHECK (length(annotation_value) <= 4096),
  PRIMARY KEY (tenant_id, project_id, dataset_name, annotation_key),
  FOREIGN KEY (tenant_id, project_id, dataset_name)
    REFERENCES datasets(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE dataset_releases (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  dataset_name text NOT NULL,
  release_id text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  manifest_ref_id bigint NOT NULL,
  parent_release_ref_id bigint,
  use_policy_ref_id bigint,
  policy_classification text NOT NULL DEFAULT '',
  create_time timestamptz NOT NULL,
  publish_time timestamptz,
  revoke_time timestamptz,
  revocation_reason text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, dataset_name, release_id),
  FOREIGN KEY (tenant_id, project_id, dataset_name)
    REFERENCES datasets(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, manifest_ref_id)
    REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, parent_release_ref_id)
    REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, use_policy_ref_id)
    REFERENCES resource_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND release_id <> ''),
  CHECK ((state = 5) = (revoke_time IS NOT NULL)),
  CHECK ((revoke_time IS NULL AND revocation_reason = '') OR
         (revoke_time IS NOT NULL AND revocation_reason <> ''))
);

CREATE TABLE dataset_release_qualification_evidence (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  release_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  subject_digest text NOT NULL CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind <> ''),
  policy_digest text NOT NULL DEFAULT '' CHECK (policy_digest = '' OR policy_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, release_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, release_name)
    REFERENCES dataset_releases(tenant_id, project_id, name) ON DELETE RESTRICT
);

CREATE TABLE dataset_release_revocation_evidence (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  release_name text NOT NULL,
  release_revision bigint NOT NULL CHECK (release_revision > 1),
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  subject_digest text NOT NULL CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind <> ''),
  policy_digest text NOT NULL DEFAULT '' CHECK (policy_digest = '' OR policy_digest ~ '^sha256:[0-9a-f]{64}$'),
  revoked_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, release_name, release_revision, ordinal),
  FOREIGN KEY (tenant_id, project_id, release_name)
    REFERENCES dataset_releases(tenant_id, project_id, name) ON DELETE RESTRICT
);

CREATE TABLE models (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  display_name text NOT NULL,
  family text NOT NULL,
  state integer NOT NULL CHECK (state BETWEEN 1 AND 3),
  definition_manifest_ref_id bigint NOT NULL,
  feature_requirement_set_ref_id bigint NOT NULL,
  model_feature_view_ref_id bigint NOT NULL,
  input_contract_ref_id bigint NOT NULL,
  output_contract_ref_id bigint NOT NULL,
  policy_classification text NOT NULL DEFAULT '',
  create_time timestamptz NOT NULL,
  update_time timestamptz,
  delete_time timestamptz,
  current_release_name text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  FOREIGN KEY (tenant_id, definition_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, feature_requirement_set_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, model_feature_view_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, input_contract_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, output_contract_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND display_name <> '' AND family <> ''),
  CHECK (update_time IS NULL OR update_time >= create_time),
  CHECK (delete_time IS NULL OR delete_time >= create_time)
);

CREATE TABLE model_labels (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  model_name text NOT NULL,
  label_key text NOT NULL CHECK (label_key <> '' AND length(label_key) <= 128),
  label_value text NOT NULL CHECK (length(label_value) <= 256),
  PRIMARY KEY (tenant_id, project_id, model_name, label_key),
  FOREIGN KEY (tenant_id, project_id, model_name)
    REFERENCES models(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE model_annotations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  model_name text NOT NULL,
  annotation_key text NOT NULL CHECK (annotation_key <> '' AND length(annotation_key) <= 128),
  annotation_value text NOT NULL CHECK (length(annotation_value) <= 4096),
  PRIMARY KEY (tenant_id, project_id, model_name, annotation_key),
  FOREIGN KEY (tenant_id, project_id, model_name)
    REFERENCES models(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE model_releases (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  model_name text NOT NULL,
  release_id text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  stage integer NOT NULL CHECK (stage BETWEEN 1 AND 6),
  bundle_manifest_ref_id bigint NOT NULL,
  model_manifest_ref_id bigint NOT NULL,
  checkpoint_ref_id bigint NOT NULL,
  feature_requirement_set_ref_id bigint NOT NULL,
  model_feature_view_ref_id bigint NOT NULL,
  release_policy_ref_id bigint NOT NULL,
  policy_classification text NOT NULL DEFAULT '',
  create_time timestamptz NOT NULL,
  qualify_time timestamptz,
  release_time timestamptz,
  revoke_time timestamptz,
  revocation_reason text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, model_name, release_id),
  FOREIGN KEY (tenant_id, project_id, model_name)
    REFERENCES models(tenant_id, project_id, name),
  FOREIGN KEY (tenant_id, bundle_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, model_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, checkpoint_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, feature_requirement_set_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, model_feature_view_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, release_policy_ref_id) REFERENCES resource_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND release_id <> ''),
  CHECK ((stage = 6) = (revoke_time IS NOT NULL)),
  CHECK ((revoke_time IS NULL AND revocation_reason = '') OR
         (revoke_time IS NOT NULL AND revocation_reason <> ''))
);

CREATE TABLE model_release_evaluation_evidence (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  release_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  subject_digest text NOT NULL CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind <> ''),
  policy_digest text NOT NULL DEFAULT '' CHECK (policy_digest = '' OR policy_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, release_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, release_name)
    REFERENCES model_releases(tenant_id, project_id, name) ON DELETE RESTRICT
);

-- Promotion and revocation evidence are immutable facts distinct from the
-- release's registration-time evaluation evidence.
CREATE TABLE model_release_transition_evidence (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  release_name text NOT NULL,
  release_revision bigint NOT NULL CHECK (release_revision > 1),
  transition_kind text NOT NULL CHECK (transition_kind IN ('PROMOTION','PROMOTION_DECISION','REVOCATION')),
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  subject_digest text NOT NULL CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind <> ''),
  policy_digest text NOT NULL DEFAULT '' CHECK (policy_digest = '' OR policy_digest ~ '^sha256:[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, release_name, release_revision, transition_kind, ordinal),
  FOREIGN KEY (tenant_id, project_id, release_name)
    REFERENCES model_releases(tenant_id, project_id, name) ON DELETE RESTRICT
);

-- Idempotency authority is bound to authenticated principal and semantic
-- action; one principal cannot replay another principal's durable command.
CREATE TABLE data_model_command_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  principal_id text NOT NULL,
  action text NOT NULL,
  idempotency_key text NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  operation_id text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, principal_id, action, idempotency_key),
  FOREIGN KEY (tenant_id, project_id, operation_id)
    REFERENCES operations(tenant_id, project_id, id),
  CHECK (principal_id <> '' AND action <> '' AND idempotency_key <> ''),
  CHECK (length(principal_id) <= 255 AND length(action) <= 128 AND length(idempotency_key) <= 255)
);

CREATE INDEX datasets_project_list_idx ON datasets (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX dataset_releases_parent_list_idx ON dataset_releases (tenant_id, project_id, dataset_name, create_time DESC, name DESC);
CREATE INDEX models_project_list_idx ON models (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX model_releases_parent_list_idx ON model_releases (tenant_id, project_id, model_name, create_time DESC, name DESC);
CREATE INDEX data_model_receipts_operation_idx ON data_model_command_receipts (tenant_id, project_id, operation_id);

-- Immutable release identity and scientific inputs cannot be rewritten by a
-- stage/disposition transition. Only lifecycle columns may change.
CREATE FUNCTION guard_dataset_release_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.name IS DISTINCT FROM OLD.name OR NEW.uid IS DISTINCT FROM OLD.uid OR
     NEW.dataset_name IS DISTINCT FROM OLD.dataset_name OR NEW.release_id IS DISTINCT FROM OLD.release_id OR
     NEW.manifest_ref_id IS DISTINCT FROM OLD.manifest_ref_id OR
     NEW.parent_release_ref_id IS DISTINCT FROM OLD.parent_release_ref_id OR
     NEW.use_policy_ref_id IS DISTINCT FROM OLD.use_policy_ref_id OR
     NEW.policy_classification IS DISTINCT FROM OLD.policy_classification OR
     NEW.create_time IS DISTINCT FROM OLD.create_time OR NEW.publish_time IS DISTINCT FROM OLD.publish_time THEN
    RAISE EXCEPTION 'dataset release immutable fields cannot be changed' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.revision <> OLD.revision + 1 OR NEW.etag = OLD.etag OR
     (OLD.revoke_time IS NOT NULL AND NEW.revoke_time IS DISTINCT FROM OLD.revoke_time) OR
     (OLD.revocation_reason <> '' AND NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason) OR
     NOT ((OLD.state = 1 AND NEW.state = 2) OR
          (OLD.state = 2 AND NEW.state = 3) OR
          (OLD.state = 3 AND NEW.state = 4) OR
          (OLD.state BETWEEN 1 AND 4 AND NEW.state = 5)) THEN
    RAISE EXCEPTION 'dataset release lifecycle transition is invalid' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER dataset_release_immutable BEFORE UPDATE ON dataset_releases
  FOR EACH ROW EXECUTE FUNCTION guard_dataset_release_immutable();

CREATE FUNCTION guard_model_release_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.name IS DISTINCT FROM OLD.name OR NEW.uid IS DISTINCT FROM OLD.uid OR
     NEW.model_name IS DISTINCT FROM OLD.model_name OR NEW.release_id IS DISTINCT FROM OLD.release_id OR
     NEW.bundle_manifest_ref_id IS DISTINCT FROM OLD.bundle_manifest_ref_id OR
     NEW.model_manifest_ref_id IS DISTINCT FROM OLD.model_manifest_ref_id OR
     NEW.checkpoint_ref_id IS DISTINCT FROM OLD.checkpoint_ref_id OR
     NEW.feature_requirement_set_ref_id IS DISTINCT FROM OLD.feature_requirement_set_ref_id OR
     NEW.model_feature_view_ref_id IS DISTINCT FROM OLD.model_feature_view_ref_id OR
     NEW.release_policy_ref_id IS DISTINCT FROM OLD.release_policy_ref_id OR
     NEW.policy_classification IS DISTINCT FROM OLD.policy_classification OR
     NEW.create_time IS DISTINCT FROM OLD.create_time THEN
    RAISE EXCEPTION 'model release immutable fields cannot be changed' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.revision <> OLD.revision + 1 OR NEW.etag = OLD.etag OR
     (OLD.qualify_time IS NOT NULL AND NEW.qualify_time IS DISTINCT FROM OLD.qualify_time) OR
     (OLD.release_time IS NOT NULL AND NEW.release_time IS DISTINCT FROM OLD.release_time) OR
     (OLD.revoke_time IS NOT NULL AND NEW.revoke_time IS DISTINCT FROM OLD.revoke_time) OR
     (OLD.revocation_reason <> '' AND NEW.revocation_reason IS DISTINCT FROM OLD.revocation_reason) OR
     NOT ((OLD.stage = 1 AND NEW.stage = 2) OR
          (OLD.stage = 2 AND NEW.stage = 3) OR
          (OLD.stage = 3 AND NEW.stage = 4) OR
          (OLD.stage = 4 AND NEW.stage = 5) OR
          (OLD.stage BETWEEN 1 AND 5 AND NEW.stage = 6)) THEN
    RAISE EXCEPTION 'model release lifecycle transition is invalid' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER model_release_immutable BEFORE UPDATE ON model_releases
  FOR EACH ROW EXECUTE FUNCTION guard_model_release_immutable();

CREATE FUNCTION reject_immutable_data_model_fact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable data/model evidence or receipt cannot be changed' USING ERRCODE = 'check_violation';
END;
$$;
CREATE TRIGGER dataset_release_evidence_immutable
  BEFORE UPDATE ON dataset_release_qualification_evidence
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_data_model_fact();
CREATE TRIGGER dataset_release_revocation_evidence_immutable
  BEFORE UPDATE ON dataset_release_revocation_evidence
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_data_model_fact();
CREATE TRIGGER model_release_evaluation_immutable
  BEFORE UPDATE ON model_release_evaluation_evidence
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_data_model_fact();
CREATE TRIGGER model_release_transition_immutable
  BEFORE UPDATE ON model_release_transition_evidence
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_data_model_fact();
CREATE TRIGGER data_model_receipt_immutable
  BEFORE UPDATE ON data_model_command_receipts
  FOR EACH ROW EXECUTE FUNCTION reject_immutable_data_model_fact();

ALTER TABLE datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE datasets FORCE ROW LEVEL SECURITY;
ALTER TABLE dataset_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_labels FORCE ROW LEVEL SECURITY;
ALTER TABLE dataset_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_annotations FORCE ROW LEVEL SECURITY;
ALTER TABLE dataset_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_releases FORCE ROW LEVEL SECURITY;
ALTER TABLE dataset_release_qualification_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_release_qualification_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE dataset_release_revocation_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_release_revocation_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE models ENABLE ROW LEVEL SECURITY;
ALTER TABLE models FORCE ROW LEVEL SECURITY;
ALTER TABLE model_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_labels FORCE ROW LEVEL SECURITY;
ALTER TABLE model_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_annotations FORCE ROW LEVEL SECURITY;
ALTER TABLE model_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_releases FORCE ROW LEVEL SECURITY;
ALTER TABLE model_release_evaluation_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_release_evaluation_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE model_release_transition_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_release_transition_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE data_model_command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_model_command_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY datasets_tenant_policy ON datasets USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY dataset_labels_tenant_policy ON dataset_labels USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY dataset_annotations_tenant_policy ON dataset_annotations USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY dataset_releases_tenant_policy ON dataset_releases USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY dataset_release_evidence_tenant_policy ON dataset_release_qualification_evidence USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY dataset_release_revocation_evidence_tenant_policy ON dataset_release_revocation_evidence USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY models_tenant_policy ON models USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY model_labels_tenant_policy ON model_labels USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY model_annotations_tenant_policy ON model_annotations USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY model_releases_tenant_policy ON model_releases USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY model_release_evaluation_tenant_policy ON model_release_evaluation_evidence USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY model_release_transition_tenant_policy ON model_release_transition_evidence USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY data_model_receipts_tenant_policy ON data_model_command_receipts USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

COMMIT;
