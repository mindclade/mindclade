BEGIN;

DO $$
DECLARE
  table_name text;
  contains_rows boolean;
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'artifact down migration requires explicit local-empty authorization';
  END IF;
  FOREACH table_name IN ARRAY ARRAY[
    'artifact_staging_receipts','artifact_upload_sessions','artifact_upload_chunks',
    'artifact_catalog_entries','artifact_aliases','artifact_quarantine_evidence',
    'artifact_leases','artifact_operations','artifact_command_receipts'
  ] LOOP
    EXECUTE format('LOCK TABLE %I IN ACCESS EXCLUSIVE MODE', table_name);
    EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I)', table_name) INTO contains_rows;
    IF contains_rows THEN
      RAISE EXCEPTION 'artifact down migration refuses non-empty durable table %', table_name;
    END IF;
  END LOOP;
END $$;

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
