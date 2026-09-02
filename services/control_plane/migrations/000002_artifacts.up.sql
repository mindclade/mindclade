BEGIN;

-- Durable transfer-plane proof. A receipt is written only after the object
-- adapter has verified SHA-256, exact size, provider checksum, and immutable
-- generation. The current metadata RPCs consume but cannot create receipts.
CREATE TABLE artifact_staging_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  receipt_digest text NOT NULL CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
  artifact_digest text NOT NULL CHECK (artifact_digest ~ '^sha256:[0-9a-f]{64}$'),
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0 AND size_bytes <= 5497558138880),
  object_generation bigint NOT NULL CHECK (object_generation > 0),
  state text NOT NULL CHECK (state IN ('VERIFIED','QUARANTINED')),
  verified_at timestamptz NOT NULL,
  expire_time timestamptz NOT NULL,
  quarantine_time timestamptz,
  quarantine_reason text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, receipt_digest),
  CHECK (expire_time > verified_at),
  CHECK (
    (state = 'VERIFIED' AND quarantine_time IS NULL AND quarantine_reason = '') OR
    (state = 'QUARANTINED' AND quarantine_time IS NOT NULL AND quarantine_reason <> '')
  )
);
CREATE INDEX artifact_staging_receipt_expiry_idx
  ON artifact_staging_receipts (tenant_id, project_id, state, expire_time);

-- Resumable transfer state is normalized and contains no provider locator or
-- content bytes. Chunk generations pin private immutable GCS staging objects;
-- the final generation pins the verified content-addressed object.
CREATE TABLE artifact_upload_sessions (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  upload_id text NOT NULL CHECK (upload_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  artifact_digest text NOT NULL CHECK (artifact_digest ~ '^sha256:[0-9a-f]{64}$'),
  media_type text NOT NULL CHECK (media_type <> '' AND length(media_type) <= 255),
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0 AND size_bytes <= 5497558138880),
  artifact_kind text NOT NULL DEFAULT '',
  schema_id text NOT NULL DEFAULT '',
  integrity_digest text NOT NULL DEFAULT '' CHECK (integrity_digest = '' OR integrity_digest = artifact_digest),
  schema_version text NOT NULL DEFAULT '',
  state text NOT NULL CHECK (state IN ('OPEN','FINALIZING','FINALIZED','ABORTED','QUARANTINED','EXPIRED')),
  committed_offset bigint NOT NULL DEFAULT 0 CHECK (committed_offset >= 0 AND committed_offset <= size_bytes),
  next_chunk_index bigint NOT NULL DEFAULT 0 CHECK (next_chunk_index >= 0),
  staging_receipt_digest text,
  object_generation bigint CHECK (object_generation IS NULL OR object_generation > 0),
  finalize_idempotency_key text,
  finalize_request_digest text CHECK (finalize_request_digest IS NULL OR finalize_request_digest ~ '^sha256:[0-9a-f]{64}$'),
  finalize_time timestamptz,
  receipt_expire_time timestamptz,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag <> ''),
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  expire_time timestamptz NOT NULL,
  terminal_reason text NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id, project_id, upload_id),
  FOREIGN KEY (tenant_id, project_id, staging_receipt_digest)
    REFERENCES artifact_staging_receipts(tenant_id, project_id, receipt_digest),
  CHECK ((schema_id = '') = (schema_version = '')),
  CHECK (expire_time > create_time),
  CHECK (
    (finalize_idempotency_key IS NULL AND finalize_request_digest IS NULL AND finalize_time IS NULL AND receipt_expire_time IS NULL) OR
    (finalize_idempotency_key IS NOT NULL AND finalize_request_digest IS NOT NULL AND finalize_time IS NOT NULL AND receipt_expire_time > finalize_time)
  ),
  CHECK (state NOT IN ('FINALIZING','FINALIZED') OR finalize_idempotency_key IS NOT NULL),
  CHECK (
    (state IN ('OPEN','FINALIZING') AND staging_receipt_digest IS NULL AND object_generation IS NULL AND terminal_reason = '') OR
    (state = 'FINALIZED' AND staging_receipt_digest IS NOT NULL AND object_generation IS NOT NULL AND committed_offset = size_bytes AND terminal_reason = '') OR
    (state IN ('ABORTED','QUARANTINED','EXPIRED') AND staging_receipt_digest IS NULL AND object_generation IS NULL AND terminal_reason <> '')
  )
);
CREATE INDEX artifact_upload_expiry_idx
  ON artifact_upload_sessions (tenant_id, project_id, state, expire_time);

CREATE TABLE artifact_upload_chunks (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  upload_id text NOT NULL,
  chunk_index bigint NOT NULL CHECK (chunk_index >= 0),
  byte_offset bigint NOT NULL CHECK (byte_offset >= 0),
  size_bytes integer NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 4194304),
  chunk_digest text NOT NULL CHECK (chunk_digest ~ '^sha256:[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('WRITING','STORED')),
  object_generation bigint CHECK (object_generation IS NULL OR object_generation > 0),
  create_time timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, upload_id, chunk_index),
  UNIQUE (tenant_id, project_id, upload_id, byte_offset),
  FOREIGN KEY (tenant_id, project_id, upload_id)
    REFERENCES artifact_upload_sessions(tenant_id, project_id, upload_id) ON DELETE CASCADE,
  CHECK ((state = 'WRITING' AND object_generation IS NULL) OR (state = 'STORED' AND object_generation IS NOT NULL))
);

-- ArtifactRef remains the generated application boundary. These private rows
-- normalize its immutable fields and keep storage locators out of the catalog.
CREATE TABLE artifact_catalog_entries (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
  media_type text NOT NULL CHECK (media_type <> '' AND length(media_type) <= 255),
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0 AND size_bytes <= 5497558138880),
  artifact_kind text NOT NULL DEFAULT '',
  schema_id text NOT NULL DEFAULT '',
  integrity_digest text NOT NULL DEFAULT '' CHECK (integrity_digest = '' OR integrity_digest = digest),
  schema_version text NOT NULL DEFAULT '',
  staging_receipt_digest text NOT NULL CHECK (staging_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('COMMITTED','QUARANTINED')),
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag <> ''),
  quarantine_reason text NOT NULL DEFAULT '',
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  quarantine_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, digest),
  FOREIGN KEY (tenant_id, project_id, staging_receipt_digest)
    REFERENCES artifact_staging_receipts(tenant_id, project_id, receipt_digest),
  CHECK ((schema_id = '') = (schema_version = '')),
  CHECK (
    (state = 'COMMITTED' AND quarantine_reason = '' AND quarantine_time IS NULL) OR
    (state = 'QUARANTINED' AND quarantine_reason <> '' AND quarantine_time IS NOT NULL)
  )
);
CREATE INDEX artifact_catalog_list_idx
  ON artifact_catalog_entries (tenant_id, project_id, create_time DESC, digest DESC);
CREATE INDEX artifact_catalog_state_list_idx
  ON artifact_catalog_entries (tenant_id, project_id, state, create_time DESC, digest DESC);

CREATE TABLE artifact_aliases (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  alias text NOT NULL CHECK (alias ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  digest text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag <> ''),
  update_time timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, alias),
  FOREIGN KEY (tenant_id, project_id, digest)
    REFERENCES artifact_catalog_entries(tenant_id, project_id, digest)
);

CREATE TABLE artifact_quarantine_evidence (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  artifact_digest text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  evidence_digest text NOT NULL CHECK (evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
  subject_digest text NOT NULL CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
  evidence_kind text NOT NULL,
  policy_digest text NOT NULL DEFAULT '' CHECK (policy_digest = '' OR policy_digest ~ '^sha256:[0-9a-f]{64}$'),
  PRIMARY KEY (tenant_id, project_id, artifact_digest, ordinal),
  FOREIGN KEY (tenant_id, project_id, artifact_digest)
    REFERENCES artifact_catalog_entries(tenant_id, project_id, digest) ON DELETE CASCADE
);

CREATE TABLE artifact_leases (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  lease_id text NOT NULL,
  artifact_digest text NOT NULL,
  principal_id text NOT NULL,
  state text NOT NULL CHECK (state IN ('ACTIVE','RELEASED')),
  expire_time timestamptz NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  etag text NOT NULL CHECK (etag <> ''),
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  release_time timestamptz,
  PRIMARY KEY (tenant_id, project_id, lease_id),
  FOREIGN KEY (tenant_id, project_id, artifact_digest)
    REFERENCES artifact_catalog_entries(tenant_id, project_id, digest),
  CHECK (
    (state = 'ACTIVE' AND release_time IS NULL) OR
    (state = 'RELEASED' AND release_time IS NOT NULL)
  )
);
CREATE INDEX artifact_lease_expiry_idx
  ON artifact_leases (tenant_id, project_id, state, expire_time);

-- Quarantine is committed synchronously, but its generated response remains a
-- durable Operation so callers receive stable retry and audit semantics.
CREATE TABLE artifact_operations (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  operation_id text NOT NULL,
  target_digest text NOT NULL,
  state integer NOT NULL CHECK (state > 0),
  resource_version bigint NOT NULL CHECK (resource_version > 0),
  done boolean NOT NULL,
  etag text NOT NULL CHECK (etag <> ''),
  create_time timestamptz NOT NULL,
  update_time timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, operation_id),
  FOREIGN KEY (tenant_id, project_id, target_digest)
    REFERENCES artifact_catalog_entries(tenant_id, project_id, digest)
);

CREATE TABLE artifact_command_receipts (
  tenant_id text NOT NULL,
  project_id text NOT NULL,
  action text NOT NULL,
  idempotency_key text NOT NULL,
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  response_kind text NOT NULL CHECK (response_kind IN ('ARTIFACT','OPERATION','LEASE','UPLOAD','EMPTY')),
  response_id text NOT NULL,
  create_time timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, project_id, action, idempotency_key)
);

ALTER TABLE artifact_catalog_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_catalog_entries FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_aliases FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_quarantine_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_quarantine_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_leases FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_operations FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_command_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_staging_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_staging_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_upload_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_upload_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_upload_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_upload_chunks FORCE ROW LEVEL SECURITY;

CREATE POLICY artifact_catalog_tenant_policy ON artifact_catalog_entries
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_alias_tenant_policy ON artifact_aliases
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_evidence_tenant_policy ON artifact_quarantine_evidence
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_lease_tenant_policy ON artifact_leases
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_operation_tenant_policy ON artifact_operations
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_receipt_tenant_policy ON artifact_command_receipts
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_staging_receipt_tenant_policy ON artifact_staging_receipts
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_upload_session_tenant_policy ON artifact_upload_sessions
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY artifact_upload_chunk_tenant_policy ON artifact_upload_chunks
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

COMMIT;
