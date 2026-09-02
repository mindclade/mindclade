BEGIN;

DO $$
DECLARE
  table_name text;
  contains_rows boolean;
BEGIN
  IF current_setting('app.allow_local_empty_down_migration', true) IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'policy/admin down migration requires explicit local-empty authorization';
  END IF;
  FOREACH table_name IN ARRAY ARRAY[
    'use_policies','use_policy_permitted_purposes','use_policy_permitted_capabilities',
    'use_policy_prohibited_capabilities','use_policy_accepted_classifications',
    'use_policy_approval_requirements','administrative_tenants',
    'administrative_tenant_policy_snapshots','administrative_tenant_allowed_regions',
    'administrative_tenant_labels','administrative_tenant_annotations','administrative_projects',
    'administrative_project_policy_snapshots','administrative_project_labels',
    'administrative_project_annotations','administrative_audit_records','audit_exports',
    'audit_export_actor_filters','audit_export_action_filters','audit_export_resource_filters',
    'audit_export_result_filters','audit_export_reason_filters','policy_admin_command_receipts'
  ] LOOP
    EXECUTE format('LOCK TABLE %I IN ACCESS EXCLUSIVE MODE', table_name);
    EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I)', table_name) INTO contains_rows;
    IF contains_rows THEN
      RAISE EXCEPTION 'policy/admin down migration refuses non-empty durable table %', table_name;
    END IF;
  END LOOP;
END $$;

DROP TABLE IF EXISTS policy_admin_command_receipts;
DROP TABLE IF EXISTS audit_export_reason_filters;
DROP TABLE IF EXISTS audit_export_result_filters;
DROP TABLE IF EXISTS audit_export_resource_filters;
DROP TABLE IF EXISTS audit_export_action_filters;
DROP TABLE IF EXISTS audit_export_actor_filters;
DROP TABLE IF EXISTS audit_exports;
DROP TABLE IF EXISTS administrative_audit_records;
DROP TABLE IF EXISTS administrative_project_annotations;
DROP TABLE IF EXISTS administrative_project_labels;
DROP TABLE IF EXISTS administrative_project_policy_snapshots;
DROP TABLE IF EXISTS administrative_projects;
DROP TABLE IF EXISTS administrative_tenant_annotations;
DROP TABLE IF EXISTS administrative_tenant_labels;
DROP TABLE IF EXISTS administrative_tenant_allowed_regions;
DROP TABLE IF EXISTS administrative_tenant_policy_snapshots;
DROP TABLE IF EXISTS administrative_tenants;
DROP TABLE IF EXISTS use_policy_approval_requirements;
DROP TABLE IF EXISTS use_policy_accepted_classifications;
DROP TABLE IF EXISTS use_policy_prohibited_capabilities;
DROP TABLE IF EXISTS use_policy_permitted_capabilities;
DROP TABLE IF EXISTS use_policy_permitted_purposes;
DROP TABLE IF EXISTS use_policies;
DROP FUNCTION IF EXISTS reject_policy_admin_immutable_change();
DROP FUNCTION IF EXISTS guard_audit_export_update();
DROP FUNCTION IF EXISTS guard_administrative_project_update();
DROP FUNCTION IF EXISTS guard_use_policy_update();
DROP FUNCTION IF EXISTS guard_policy_admin_resource_update();

COMMIT;
