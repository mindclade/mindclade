BEGIN;

-- Dead-letter replay is an explicit, tenant-scoped state machine. Existing
-- rows remain quarantined. Pre-existing inbox rows lack a recoverable consumer
-- identity and therefore remain reviewable but fail closed if replay is
-- requested.
ALTER TABLE dead_letter_messages
  ADD COLUMN consumer text,
  ADD COLUMN replay_state text NOT NULL DEFAULT 'QUARANTINED',
  ADD COLUMN replay_generation bigint NOT NULL DEFAULT 0,
  ADD COLUMN replay_delivery_epoch bigint NOT NULL DEFAULT 0,
  ADD COLUMN replay_publish_attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN replay_claim_expires_at timestamptz,
  ADD COLUMN replay_next_attempt_at timestamptz,
  ADD COLUMN replay_requested_at timestamptz,
  ADD COLUMN replay_published_at timestamptz,
  ADD COLUMN replayed_at timestamptz,
  ADD COLUMN replay_last_error text NOT NULL DEFAULT '',
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
  ADD CONSTRAINT chk_dead_letter_consumer
    CHECK (consumer IS NULL OR (consumer <> '' AND length(consumer) <= 255 AND consumer = btrim(consumer))),
  ADD CONSTRAINT chk_dead_letter_replay_consumer_source
    CHECK (source <> 'INBOX' OR consumer IS NOT NULL) NOT VALID,
  ADD CONSTRAINT chk_dead_letter_replay_outbox_consumer
    CHECK (source <> 'OUTBOX' OR consumer IS NULL),
  ADD CONSTRAINT chk_dead_letter_replay_source_state
    CHECK (source = 'INBOX' OR replay_state IN ('QUARANTINED','PENDING','REPLAYED')),
  ADD CONSTRAINT chk_dead_letter_replay_state
    CHECK (replay_state IN ('QUARANTINED','PENDING','CLAIMED','PUBLISHED','REPLAYED')),
  ADD CONSTRAINT chk_dead_letter_replay_generation
    CHECK (replay_generation >= 0),
  ADD CONSTRAINT chk_dead_letter_replay_delivery_epoch
    CHECK (replay_delivery_epoch >= 0),
  ADD CONSTRAINT chk_dead_letter_replay_publish_attempts
    CHECK (replay_publish_attempts >= 0),
  ADD CONSTRAINT chk_dead_letter_replay_shape CHECK (
    (replay_state = 'QUARANTINED' AND replay_claim_expires_at IS NULL AND replay_next_attempt_at IS NULL AND replay_published_at IS NULL AND replayed_at IS NULL) OR
    (replay_state = 'PENDING' AND replay_generation > 0 AND replay_requested_at IS NOT NULL AND replay_next_attempt_at IS NOT NULL AND replay_claim_expires_at IS NULL AND replay_published_at IS NULL AND replayed_at IS NULL) OR
    (replay_state = 'CLAIMED' AND replay_generation > 0 AND replay_requested_at IS NOT NULL AND replay_next_attempt_at IS NOT NULL AND replay_claim_expires_at IS NOT NULL AND replay_published_at IS NULL AND replayed_at IS NULL) OR
    (replay_state = 'PUBLISHED' AND replay_generation > 0 AND replay_requested_at IS NOT NULL AND replay_published_at IS NOT NULL AND replay_claim_expires_at IS NULL AND replay_next_attempt_at IS NULL AND replayed_at IS NULL) OR
    (replay_state = 'REPLAYED' AND replay_generation > 0 AND replay_requested_at IS NOT NULL AND replayed_at IS NOT NULL AND replay_claim_expires_at IS NULL AND replay_next_attempt_at IS NULL)
  );

CREATE INDEX dead_letter_replay_claim_idx
  ON dead_letter_messages (tenant_id,replay_next_attempt_at,created_at,id)
  WHERE source = 'INBOX' AND replay_state = 'PENDING';

-- A crashed dispatcher leaves a CLAIMED row until its bounded lease expires.
-- Keep recovery indexable independently of the normal pending-work scan.
CREATE INDEX dead_letter_replay_expired_claim_idx
  ON dead_letter_messages (tenant_id,replay_claim_expires_at,created_at,id)
  WHERE source = 'INBOX' AND replay_state = 'CLAIMED';

-- A tenant-wide idempotency key identifies one immutable replay command. The
-- request digest and actor are checked under an advisory lock before a replay
-- can be returned as an idempotent success.
CREATE TABLE dead_letter_replay_receipts (
  tenant_id text NOT NULL,
  idempotency_key text NOT NULL
    CHECK (idempotency_key <> '' AND length(idempotency_key) <= 255 AND idempotency_key = btrim(idempotency_key)),
  request_digest text NOT NULL CHECK (request_digest ~ '^sha256:[0-9a-f]{64}$'),
  dead_letter_id text NOT NULL
    CHECK (dead_letter_id <> '' AND length(dead_letter_id) <= 512 AND dead_letter_id = btrim(dead_letter_id)),
  replay_generation bigint NOT NULL CHECK (replay_generation > 0),
  requested_by text NOT NULL
    CHECK (requested_by <> '' AND length(requested_by) <= 255 AND requested_by = btrim(requested_by)),
  requested_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id,idempotency_key),
  UNIQUE (tenant_id,dead_letter_id,replay_generation),
  FOREIGN KEY (tenant_id,dead_letter_id)
    REFERENCES dead_letter_messages (tenant_id,id)
    ON DELETE RESTRICT
);

ALTER TABLE dead_letter_replay_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_replay_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_scope_dead_letter_replay_receipts ON dead_letter_replay_receipts
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''));

COMMIT;
