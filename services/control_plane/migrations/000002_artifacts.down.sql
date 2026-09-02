DO $$
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'artifact down migration requires explicit local-empty authorization';
  END IF;
  IF EXISTS (SELECT 1 FROM artifact_command_receipts)
    OR EXISTS (SELECT 1 FROM artifact_upload_chunks)
    OR EXISTS (SELECT 1 FROM artifact_upload_sessions)
    OR EXISTS (SELECT 1 FROM artifact_operations)
    OR EXISTS (SELECT 1 FROM artifact_leases)
    OR EXISTS (SELECT 1 FROM artifact_quarantine_evidence)
    OR EXISTS (SELECT 1 FROM artifact_aliases)
    OR EXISTS (SELECT 1 FROM artifact_catalog_entries)
    OR EXISTS (SELECT 1 FROM artifact_staging_receipts) THEN
    RAISE EXCEPTION 'artifact down migration refuses non-empty durable tables';
  END IF;
END $$;

BEGIN;
DROP TABLE IF EXISTS artifact_command_receipts;
DROP TABLE IF EXISTS artifact_operations;
DROP TABLE IF EXISTS artifact_leases;
DROP TABLE IF EXISTS artifact_quarantine_evidence;
DROP TABLE IF EXISTS artifact_aliases;
DROP TABLE IF EXISTS artifact_catalog_entries;
DROP TABLE IF EXISTS artifact_upload_chunks;
DROP TABLE IF EXISTS artifact_upload_sessions;
DROP TABLE IF EXISTS artifact_staging_receipts;
COMMIT;
