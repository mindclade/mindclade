BEGIN;

DO $$
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'dead-letter replay down migration requires explicit local-empty authorization';
  END IF;
END
$$;

LOCK TABLE dead_letter_replay_receipts, dead_letter_messages IN ACCESS EXCLUSIVE MODE;
ALTER TABLE dead_letter_replay_receipts NO FORCE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_messages NO FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM dead_letter_replay_receipts)
    OR EXISTS (
      SELECT 1 FROM dead_letter_messages
      WHERE replay_state <> 'QUARANTINED' OR replay_generation <> 0
    ) THEN
    RAISE EXCEPTION 'cannot remove dead-letter replay schema while replay evidence exists';
  END IF;
END
$$;

DROP TABLE dead_letter_replay_receipts;
DROP INDEX dead_letter_replay_expired_claim_idx;
DROP INDEX dead_letter_replay_claim_idx;

ALTER TABLE dead_letter_messages
  DROP CONSTRAINT chk_dead_letter_replay_shape,
  DROP CONSTRAINT chk_dead_letter_replay_publish_attempts,
  DROP CONSTRAINT chk_dead_letter_replay_delivery_epoch,
  DROP CONSTRAINT chk_dead_letter_replay_generation,
  DROP CONSTRAINT chk_dead_letter_replay_state,
  DROP CONSTRAINT IF EXISTS chk_dead_letter_replay_source_state,
  DROP CONSTRAINT IF EXISTS chk_dead_letter_replay_outbox_consumer,
  DROP CONSTRAINT IF EXISTS chk_dead_letter_replay_consumer_source,
  DROP CONSTRAINT chk_dead_letter_consumer,
  DROP COLUMN updated_at,
  DROP COLUMN replay_last_error,
  DROP COLUMN replayed_at,
  DROP COLUMN replay_published_at,
  DROP COLUMN replay_requested_at,
  DROP COLUMN replay_next_attempt_at,
  DROP COLUMN replay_claim_expires_at,
  DROP COLUMN replay_publish_attempts,
  DROP COLUMN replay_delivery_epoch,
  DROP COLUMN replay_generation,
  DROP COLUMN replay_state,
  DROP COLUMN consumer;

ALTER TABLE dead_letter_messages FORCE ROW LEVEL SECURITY;

COMMIT;
