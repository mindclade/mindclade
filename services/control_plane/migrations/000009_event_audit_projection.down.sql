BEGIN;

DO $$
BEGIN
  IF COALESCE(current_setting('app.allow_local_empty_down_migration', true), '') <> 'true' THEN
    RAISE EXCEPTION 'event audit projection down migration requires app.allow_local_empty_down_migration=true';
  END IF;
END
$$;

-- Migration ownership is required for ALTER TABLE. Temporarily remove FORCE
-- while holding the transaction's AccessExclusive locks so the table owner can
-- inspect every tenant. If evidence exists, the exception rolls this entire
-- transaction back and restores FORCE RLS; an ordinary runtime role cannot
-- execute this migration.
ALTER TABLE event_audit_projection NO FORCE ROW LEVEL SECURITY;
ALTER TABLE event_audit_projection_heads NO FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM event_audit_projection)
    OR EXISTS (SELECT 1 FROM event_audit_projection_heads) THEN
    RAISE EXCEPTION 'cannot remove event audit projection while immutable evidence exists';
  END IF;
END
$$;

DROP TABLE event_audit_projection_heads;
DROP TABLE event_audit_projection;
DROP FUNCTION guard_event_audit_projection_head_update();
DROP FUNCTION reject_event_audit_projection_change();

COMMIT;
