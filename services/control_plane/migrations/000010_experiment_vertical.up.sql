BEGIN;

-- Experiment aggregates are normalized mutable state. Artifact and resource
-- references remain immutable rows owned by the kernel reference tables.
CREATE TABLE experiments (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  display_name text NOT NULL CHECK (display_name <> '' AND length(display_name) <= 512),
  kind integer NOT NULL CHECK (kind BETWEEN 1 AND 2),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 5),
  intent_manifest_ref_id bigint NOT NULL,
  use_policy_ref_id bigint NOT NULL,
  policy_classification text NOT NULL CHECK (policy_classification <> '' AND length(policy_classification) <= 128),
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  complete_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  FOREIGN KEY (tenant_id, intent_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, use_policy_ref_id) REFERENCES resource_references(tenant_id, id),
  CHECK (tenant_id <> '' AND project_id <> '' AND name <> '' AND uid <> ''),
  CHECK (update_time >= create_time),
  CHECK ((state IN (3,4,5)) = (complete_time IS NOT NULL))
);

CREATE TABLE experiment_labels (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  experiment_name text NOT NULL,
  label_key text NOT NULL CHECK (label_key <> '' AND length(label_key) <= 128),
  label_value text NOT NULL CHECK (length(label_value) <= 256),
  PRIMARY KEY (tenant_id, project_id, experiment_name, label_key),
  FOREIGN KEY (tenant_id, project_id, experiment_name)
    REFERENCES experiments(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE experiment_annotations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  experiment_name text NOT NULL,
  annotation_key text NOT NULL CHECK (annotation_key <> '' AND length(annotation_key) <= 128),
  annotation_value text NOT NULL CHECK (length(annotation_value) <= 4096),
  PRIMARY KEY (tenant_id, project_id, experiment_name, annotation_key),
  FOREIGN KEY (tenant_id, project_id, experiment_name)
    REFERENCES experiments(tenant_id, project_id, name) ON DELETE CASCADE
);

CREATE TABLE experiment_subjects (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  experiment_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  subject_ref_id bigint NOT NULL,
  PRIMARY KEY (tenant_id, project_id, experiment_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, experiment_name)
    REFERENCES experiments(tenant_id, project_id, name) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, subject_ref_id) REFERENCES resource_references(tenant_id, id)
);

CREATE TABLE experiment_studies (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  experiment_name text NOT NULL,
  experiment_ref_id bigint NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  study_type integer NOT NULL CHECK (study_type BETWEEN 1 AND 2),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 6),
  study_manifest_ref_id bigint NOT NULL,
  base_configuration_ref_id bigint NOT NULL,
  search_space_ref_id bigint NOT NULL,
  objective_specification_ref_id bigint NOT NULL,
  maximum_trials integer NOT NULL CHECK (maximum_trials BETWEEN 1 AND 100000),
  maximum_parallel_trials integer NOT NULL CHECK (maximum_parallel_trials BETWEEN 1 AND maximum_trials),
  maximum_duration_seconds bigint NOT NULL CHECK (maximum_duration_seconds >= 0),
  maximum_duration_nanos integer NOT NULL CHECK (maximum_duration_nanos BETWEEN 0 AND 999999999),
  create_time timestamptz NOT NULL,
  start_time timestamptz,
  complete_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  FOREIGN KEY (tenant_id, project_id, experiment_name)
    REFERENCES experiments(tenant_id, project_id, name) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, experiment_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, study_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, base_configuration_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, search_space_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, objective_specification_ref_id) REFERENCES artifact_references(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND experiment_name <> ''),
  CHECK (start_time IS NULL OR start_time >= create_time),
  CHECK (complete_time IS NULL OR complete_time >= create_time),
  CHECK ((state IN (4,5,6)) = (complete_time IS NOT NULL))
);

CREATE TABLE experiment_trials (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  uid text NOT NULL,
  study_name text NOT NULL,
  study_ref_id bigint NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag ~ '^sha256:[0-9a-f]{64}$'),
  trial_number integer NOT NULL CHECK (trial_number > 0),
  state integer NOT NULL CHECK (state BETWEEN 1 AND 7),
  outcome integer NOT NULL CHECK (outcome BETWEEN 0 AND 5),
  resolved_configuration_ref_id bigint NOT NULL,
  execution_ref_id bigint,
  result_manifest_ref_id bigint,
  error_detail_id bigint,
  create_time timestamptz NOT NULL,
  start_time timestamptz,
  complete_time timestamptz,
  elapsed_seconds bigint,
  elapsed_nanos integer,
  PRIMARY KEY (tenant_id, project_id, name),
  UNIQUE (tenant_id, project_id, uid),
  UNIQUE (tenant_id, project_id, study_name, trial_number),
  FOREIGN KEY (tenant_id, project_id, study_name)
    REFERENCES experiment_studies(tenant_id, project_id, name) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, study_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, resolved_configuration_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, execution_ref_id) REFERENCES resource_references(tenant_id, id),
  FOREIGN KEY (tenant_id, result_manifest_ref_id) REFERENCES artifact_references(tenant_id, id),
  FOREIGN KEY (tenant_id, error_detail_id) REFERENCES error_details(tenant_id, id),
  CHECK (name <> '' AND uid <> '' AND study_name <> ''),
  CHECK (start_time IS NULL OR start_time >= create_time),
  CHECK (complete_time IS NULL OR complete_time >= create_time),
  CHECK ((elapsed_seconds IS NULL) = (elapsed_nanos IS NULL)),
  CHECK (elapsed_seconds IS NULL OR (elapsed_seconds >= 0 AND elapsed_nanos BETWEEN 0 AND 999999999)),
  CHECK ((state BETWEEN 4 AND 7) = (complete_time IS NOT NULL)),
  CHECK ((state BETWEEN 4 AND 7) = (outcome <> 0)),
  CHECK ((state = 4) = (result_manifest_ref_id IS NOT NULL)),
  CHECK ((state = 5) = (error_detail_id IS NOT NULL))
);

CREATE TABLE experiment_trial_evidence (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  trial_name text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  subject_digest text NOT NULL CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind <> '' AND length(evidence_kind) <= 128),
  policy_digest text NOT NULL DEFAULT '' CHECK (policy_digest = '' OR policy_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, trial_name, ordinal),
  FOREIGN KEY (tenant_id, project_id, trial_name)
    REFERENCES experiment_trials(tenant_id, project_id, name) ON DELETE RESTRICT
);

CREATE TABLE experiment_command_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  principal_id text NOT NULL,
  action text NOT NULL,
  idempotency_key text NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  resource_type text NOT NULL CHECK (resource_type IN ('experiment','study','trial')),
  resource_name text NOT NULL,
  resource_revision bigint NOT NULL CHECK (resource_revision > 0),
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, principal_id, action, idempotency_key),
  CHECK (principal_id <> '' AND action <> '' AND idempotency_key <> '' AND resource_name <> ''),
  CHECK (length(principal_id) <= 255 AND length(action) <= 128 AND length(idempotency_key) <= 255)
);

CREATE INDEX experiments_project_list_idx ON experiments (tenant_id, project_id, create_time DESC, name DESC);
CREATE INDEX experiment_studies_parent_list_idx ON experiment_studies (tenant_id, project_id, experiment_name, create_time DESC, name DESC);
CREATE INDEX experiment_trials_parent_list_idx ON experiment_trials (tenant_id, project_id, study_name, create_time DESC, name DESC);
CREATE INDEX experiment_trials_parent_state_idx ON experiment_trials (tenant_id, project_id, study_name, state);
CREATE INDEX experiment_receipts_resource_idx ON experiment_command_receipts (tenant_id, project_id, resource_type, resource_name);

CREATE FUNCTION guard_experiment_inputs_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.name IS DISTINCT FROM OLD.name OR NEW.uid IS DISTINCT FROM OLD.uid OR
     NEW.kind IS DISTINCT FROM OLD.kind OR NEW.intent_manifest_ref_id IS DISTINCT FROM OLD.intent_manifest_ref_id OR
     NEW.use_policy_ref_id IS DISTINCT FROM OLD.use_policy_ref_id OR NEW.create_time IS DISTINCT FROM OLD.create_time OR
     (OLD.complete_time IS NOT NULL AND NEW.complete_time IS DISTINCT FROM OLD.complete_time) THEN
    RAISE EXCEPTION 'experiment immutable fields cannot be changed' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.revision <> OLD.revision + 1 OR NEW.etag = OLD.etag OR
     (NEW.state IS DISTINCT FROM OLD.state AND
      NOT ((OLD.state = 1 AND NEW.state IN (2,4)) OR
           (OLD.state = 2 AND NEW.state IN (3,4)) OR
           (OLD.state IN (3,4) AND NEW.state = 5))) THEN
    RAISE EXCEPTION 'experiment revision must advance exactly once' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER experiment_inputs_immutable BEFORE UPDATE ON experiments
  FOR EACH ROW EXECUTE FUNCTION guard_experiment_inputs_immutable();

CREATE FUNCTION guard_experiment_study_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.name IS DISTINCT FROM OLD.name OR NEW.uid IS DISTINCT FROM OLD.uid OR
     NEW.experiment_name IS DISTINCT FROM OLD.experiment_name OR NEW.experiment_ref_id IS DISTINCT FROM OLD.experiment_ref_id OR
     NEW.study_type IS DISTINCT FROM OLD.study_type OR NEW.study_manifest_ref_id IS DISTINCT FROM OLD.study_manifest_ref_id OR
     NEW.base_configuration_ref_id IS DISTINCT FROM OLD.base_configuration_ref_id OR NEW.search_space_ref_id IS DISTINCT FROM OLD.search_space_ref_id OR
     NEW.objective_specification_ref_id IS DISTINCT FROM OLD.objective_specification_ref_id OR
     NEW.maximum_trials IS DISTINCT FROM OLD.maximum_trials OR NEW.maximum_parallel_trials IS DISTINCT FROM OLD.maximum_parallel_trials OR
     NEW.maximum_duration_seconds IS DISTINCT FROM OLD.maximum_duration_seconds OR NEW.maximum_duration_nanos IS DISTINCT FROM OLD.maximum_duration_nanos OR
     NEW.create_time IS DISTINCT FROM OLD.create_time OR
     (OLD.start_time IS NOT NULL AND NEW.start_time IS DISTINCT FROM OLD.start_time) OR
     (OLD.complete_time IS NOT NULL AND NEW.complete_time IS DISTINCT FROM OLD.complete_time) THEN
    RAISE EXCEPTION 'study immutable fields cannot be changed' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.revision <> OLD.revision + 1 OR NEW.etag = OLD.etag OR
     NOT ((OLD.state = 1 AND NEW.state IN (2,5)) OR
          (OLD.state = 2 AND NEW.state IN (3,4,5,6)) OR
          (OLD.state = 3 AND NEW.state IN (2,5,6))) THEN
    RAISE EXCEPTION 'study lifecycle transition is invalid' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER experiment_study_immutable BEFORE UPDATE ON experiment_studies
  FOR EACH ROW EXECUTE FUNCTION guard_experiment_study_immutable();

CREATE FUNCTION guard_experiment_trial_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
     NEW.name IS DISTINCT FROM OLD.name OR NEW.uid IS DISTINCT FROM OLD.uid OR
     NEW.study_name IS DISTINCT FROM OLD.study_name OR NEW.study_ref_id IS DISTINCT FROM OLD.study_ref_id OR
     NEW.trial_number IS DISTINCT FROM OLD.trial_number OR
     NEW.resolved_configuration_ref_id IS DISTINCT FROM OLD.resolved_configuration_ref_id OR
     NEW.execution_ref_id IS DISTINCT FROM OLD.execution_ref_id OR NEW.create_time IS DISTINCT FROM OLD.create_time OR
     (OLD.result_manifest_ref_id IS NOT NULL AND NEW.result_manifest_ref_id IS DISTINCT FROM OLD.result_manifest_ref_id) OR
     (OLD.error_detail_id IS NOT NULL AND NEW.error_detail_id IS DISTINCT FROM OLD.error_detail_id) OR
     (OLD.start_time IS NOT NULL AND NEW.start_time IS DISTINCT FROM OLD.start_time) OR
     (OLD.complete_time IS NOT NULL AND NEW.complete_time IS DISTINCT FROM OLD.complete_time) OR
     (OLD.outcome <> 0 AND NEW.outcome IS DISTINCT FROM OLD.outcome) THEN
    RAISE EXCEPTION 'trial immutable fields cannot be changed' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.revision <> OLD.revision + 1 OR NEW.etag = OLD.etag OR
     NOT ((OLD.state = 1 AND NEW.state IN (2,6,7)) OR
          (OLD.state = 2 AND NEW.state IN (3,6,7)) OR
          (OLD.state = 3 AND NEW.state IN (4,5,6,7))) THEN
    RAISE EXCEPTION 'trial lifecycle transition is invalid' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER experiment_trial_immutable BEFORE UPDATE ON experiment_trials
  FOR EACH ROW EXECUTE FUNCTION guard_experiment_trial_immutable();

CREATE FUNCTION reject_experiment_immutable_fact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable experiment fact cannot be changed' USING ERRCODE = 'check_violation';
END;
$$;
CREATE TRIGGER experiment_subject_immutable BEFORE UPDATE ON experiment_subjects FOR EACH ROW EXECUTE FUNCTION reject_experiment_immutable_fact();
CREATE TRIGGER experiment_trial_evidence_immutable BEFORE UPDATE ON experiment_trial_evidence FOR EACH ROW EXECUTE FUNCTION reject_experiment_immutable_fact();
CREATE TRIGGER experiment_receipt_immutable BEFORE UPDATE ON experiment_command_receipts FOR EACH ROW EXECUTE FUNCTION reject_experiment_immutable_fact();

ALTER TABLE experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiments FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_labels FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_annotations FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_subjects FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_studies ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_studies FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_trials ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_trials FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_trial_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_trial_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE experiment_command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_command_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY experiments_tenant_policy ON experiments USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY experiment_labels_tenant_policy ON experiment_labels USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY experiment_annotations_tenant_policy ON experiment_annotations USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY experiment_subjects_tenant_policy ON experiment_subjects USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY experiment_studies_tenant_policy ON experiment_studies USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY experiment_trials_tenant_policy ON experiment_trials USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY experiment_trial_evidence_tenant_policy ON experiment_trial_evidence USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY experiment_receipts_tenant_policy ON experiment_command_receipts USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

COMMIT;
