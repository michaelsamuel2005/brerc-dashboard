"""Static contract tests for the versioned destination PostgreSQL migration.

These checks intentionally need no database driver. They prevent high-risk
schema and grant regressions on every Python version. Executing the migration
against PostgreSQL 16 + PostGIS remains a separate integration gate.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = ROOT / "db" / "migrations" / "0001_publication_store.sql"
ROLES_PATH = ROOT / "db" / "roles.sql"
README_PATH = ROOT / "db" / "README.md"


def _table_body(sql: str, qualified_name: str) -> str:
    match = re.search(
        rf"CREATE TABLE {re.escape(qualified_name)} \((.*?)\n\);",
        sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"table {qualified_name} is absent")
    return match.group(1)


def _view_body(sql: str, qualified_name: str) -> str:
    match = re.search(
        rf"CREATE VIEW {re.escape(qualified_name)} .*? AS\n(.*?);",
        sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"view {qualified_name} is absent")
    return match.group(1)


class DestinationMigrationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.roles = ROLES_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_migration_is_transactional_and_version_guarded(self):
        self.assertRegex(self.sql, r"(?m)^BEGIN;$")
        self.assertRegex(self.sql, r"(?m)^COMMIT;$")
        self.assertIn("pg_advisory_xact_lock", self.sql)
        self.assertIn("loader_control.schema_migration", self.sql)
        self.assertIn("0001_publication_store is already applied", self.sql)
        self.assertIn("'0001_publication_store'", self.sql)
        self.assertNotRegex(
            self.sql.upper(),
            r"(?m)^\s*CREATE TABLE IF NOT EXISTS\b",
        )
        self.assertNotRegex(self.sql.upper(), r"\b(?:DROP|TRUNCATE)\b")
        self.assertNotIn("CREATE OR REPLACE VIEW", self.sql.upper())

    def test_postgis_and_four_schemas_are_explicit(self):
        self.assertIn("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public", self.sql)
        self.assertIn("CREATE SCHEMA loader_control AUTHORIZATION %I", self.sql)
        for schema in ("loader_stage", "publication", "serve"):
            self.assertRegex(
                self.sql,
                rf"CREATE SCHEMA (?:IF NOT EXISTS )?{schema};",
            )

    def test_preexisting_control_schema_must_have_the_expected_owner_and_acl(self):
        self.assertNotIn("CREATE SCHEMA IF NOT EXISTS loader_control", self.sql)
        self.assertIn("observed_owner <> expected_owner", self.sql)
        self.assertIn("pg_catalog.aclexplode", self.sql)
        self.assertIn("privilege.privilege_type = 'CREATE'", self.sql)
        self.assertIn("privilege.grantee <> n.nspowner", self.sql)
        self.assertIn("loader_control grants CREATE to a non-owner", self.sql)

    def test_control_and_stage_tables_cover_release_protocol(self):
        required = (
            "loader_control.source_state",
            "loader_control.etl_job",
            "loader_control.release",
            "loader_control.release_manifest",
            "loader_control.withheld_summary",
            "loader_control.etl_job_event",
            "loader_control.notification_outbox",
            "loader_control.source_disposition",
            "loader_stage.source_inventory",
            "loader_stage.disposition_delta",
            "loader_stage.reconciliation_result",
        )
        for table in required:
            with self.subTest(table=table):
                _table_body(self.sql, table)

    def test_every_publication_table_has_release_provenance(self):
        tables = (
            "publication.public_release",
            "publication.public_species",
            "publication.public_distribution_cell",
            "publication.public_species_year",
            "publication.public_record",
        )
        for table in tables:
            with self.subTest(table=table):
                self.assertRegex(_table_body(self.sql, table), r"\brelease_id uuid\b")

    def test_publication_tables_have_no_raw_source_control_fields(self):
        bodies = "\n".join(
            _table_body(self.sql, table)
            for table in (
                "publication.public_release",
                "publication.public_species",
                "publication.public_distribution_cell",
                "publication.public_species_year",
                "publication.public_record",
            )
        ).casefold()
        for forbidden in (
            "unique_no",
            "easting",
            "northing",
            "comments",
            "sensitive",
            "source_key_token",
            "input_fingerprint",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotRegex(bodies, rf"\b{forbidden}\b")

    def test_private_identity_is_a_full_hmac_token_not_a_raw_key(self):
        state = _table_body(self.sql, "loader_control.source_disposition")
        inventory = _table_body(self.sql, "loader_stage.source_inventory")
        self.assertIn("source_key_token bytea", state)
        self.assertIn("octet_length(source_key_token) = 32", state)
        self.assertIn("release_id uuid", state)
        self.assertIn("PRIMARY KEY (release_id, source_key_token)", state)
        self.assertNotIn("source_id text", state)
        self.assertIn("source_key_token bytea", inventory)
        self.assertIn("octet_length(source_key_token) = 32", inventory)
        self.assertIn("input_fingerprint bytea NOT NULL", inventory)
        self.assertNotIn("unique_no", state.casefold())
        self.assertNotIn("unique_no", inventory.casefold())

    def test_manifest_pins_watermark_evidence_digests_and_reconciliation(self):
        manifest = _table_body(self.sql, "loader_control.release_manifest")
        for required in (
            "lower_modified_date",
            "lower_modified_key_token",
            "upper_modified_date",
            "upper_modified_key_token",
            "source_contract_sha256",
            "observed_view_definition_sha256",
            "observed_view_identity_sha256",
            "publication_policy_sha256",
            "policy_approval_sha256",
            "suppression_mode text NOT NULL",
            "min_records_per_cell integer NOT NULL",
            "compatibility_sha256",
            "candidate_sha256",
            "database_sha256",
            "source_inventory_count = source_row_count",
            "source_row_count = eligible_pre_suppression_count + transform_withheld_count",
            "= published_basis_count + suppression_withheld_count",
        ):
            with self.subTest(required=required):
                self.assertIn(required, manifest)
        self.assertIn(
            "GRANT SELECT, INSERT ON loader_control.release_manifest TO brerc_loader",
            self.sql,
        )
        self.assertNotIn(
            "GRANT SELECT, INSERT, UPDATE ON loader_control.release_manifest",
            self.sql,
        )
        self.assertIn("inventory_null_date_count", self.sql)
        self.assertIn("inventory_dated_count", self.sql)
        self.assertIn(
            "i.source_key_token > manifest.upper_modified_key_token",
            self.sql,
        )
        self.assertIn("initial delta is not the complete source snapshot", self.sql)
        self.assertIn(
            "incremental delta differs from the complete base change set",
            self.sql,
        )

    def test_unapproved_taxon_group_is_fail_closed(self):
        species = _table_body(self.sql, "publication.public_species")
        self.assertIn(
            "CONSTRAINT public_species_taxon_group_deferred CHECK (taxon_group IS NULL)",
            species,
        )
        self.assertIn("OR recorded.taxon_group IS NOT NULL", self.sql)
        self.assertIn("p.taxon_group", self.sql)

    def test_atomic_pointer_and_concurrency_constraints_exist(self):
        source_state = _table_body(self.sql, "loader_control.source_state")
        self.assertIn("active_release_id uuid", source_state)
        self.assertIn("last_successful_modified_date date", source_state)
        self.assertIn("last_successful_modified_key_token bytea", source_state)
        self.assertIn("source_state_active_release_fk", self.sql)
        self.assertIn("release_one_active_per_source", self.sql)
        self.assertIn("etl_job_one_open_per_source", self.sql)

    def test_all_public_views_are_active_release_only(self):
        views = (
            "serve.public_release",
            "serve.public_species",
            "serve.public_distribution_cell",
            "serve.public_species_year",
            "serve.public_record",
        )
        for view in views:
            with self.subTest(view=view):
                body = _view_body(self.sql, view)
                self.assertIn("loader_control.release", body)
                self.assertIn("r.status = 'active'", body)
                self.assertIn("loader_control.source_state", body)
                self.assertIn("s.active_release_id = r.release_id", body)

    def test_serving_views_enforce_every_publication_capability(self):
        release = _table_body(self.sql, "publication.public_release")
        for flag in (
            "verification_available",
            "individual_records_available",
            "record_verification_available",
            "place_available",
            "abundance_available",
            "record_type_available",
        ):
            self.assertRegex(release, rf"\b{flag} boolean NOT NULL\b")

        cells = _view_body(self.sql, "serve.public_distribution_cell")
        years = _view_body(self.sql, "serve.public_species_year")
        records = _view_body(self.sql, "serve.public_record")
        self.assertIn("CASE WHEN capabilities.verification_available", cells)
        self.assertIn("CASE WHEN capabilities.verification_available", years)
        self.assertIn("capabilities.individual_records_available", records)
        self.assertIn("CASE WHEN capabilities.place_available", records)
        self.assertIn("CASE WHEN capabilities.abundance_available", records)
        self.assertIn("CASE WHEN capabilities.record_type_available", records)
        self.assertIn("CASE WHEN capabilities.record_verification_available", records)

    def test_map_cells_are_constrained_and_spatially_indexed(self):
        cells = _table_body(self.sql, "publication.public_distribution_cell")
        self.assertIn("public.geometry(Polygon, 27700)", cells)
        self.assertIn("precision_metres IN (100, 1000, 10000)", cells)
        self.assertIn("verified_count <= record_count", cells)
        self.assertIn("public.ST_SRID(geom) = 27700", cells)
        self.assertIn("public.ST_IsValid(geom)", cells)
        self.assertIn("public.ST_Area(geom)", cells)
        self.assertIn("loader_control.bng_cell_polygon(cell_id, precision_metres)", cells)
        self.assertIn("CREATE FUNCTION loader_control.bng_cell_polygon", self.sql)
        self.assertIn("grid cell precision disagrees with its reference", self.sql)
        self.assertIn("source_disposition_record_inside_cell", self.sql)
        self.assertIn("disposition_delta_record_inside_cell", self.sql)
        self.assertIn("public.ST_CoveredBy", self.sql)
        self.assertIn("USING gist (geom)", self.sql)

    def test_year_range_matches_the_etl_contract(self):
        for table in (
            "loader_control.source_disposition",
            "loader_stage.disposition_delta",
            "publication.public_species",
            "publication.public_distribution_cell",
            "publication.public_species_year",
            "publication.public_record",
        ):
            with self.subTest(table=table):
                body = _table_body(self.sql, table)
                self.assertIn("BETWEEN 1500 AND 2200", body)
                self.assertNotIn("BETWEEN 1600 AND 2100", body)

    def test_operational_events_cannot_store_arbitrary_json_or_text(self):
        events = _table_body(self.sql, "loader_control.etl_job_event")
        self.assertNotIn("json", events.casefold())
        self.assertNotIn("message", events.casefold())
        for field in ("observed_count bigint", "duration_ms bigint", "retry_number integer"):
            self.assertIn(field, events)
        self.assertIn("GRANT SELECT ON loader_control.etl_job_event TO brerc_loader", self.sql)
        self.assertNotIn(
            "GRANT SELECT, INSERT ON loader_control.etl_job_event TO brerc_loader",
            self.sql,
        )

    def test_terminal_job_audit_rows_are_immutable(self):
        self.assertIn(
            "CREATE FUNCTION loader_control.guard_terminal_etl_job_update()",
            self.sql,
        )
        self.assertIn(
            "IF OLD.status IN ('succeeded', 'failed', 'cancelled')",
            self.sql,
        )
        self.assertIn("terminal ETL job audit rows are immutable", self.sql)
        self.assertRegex(
            self.sql,
            r"CREATE TRIGGER etl_job_terminal_update_guard\s+"
            r"BEFORE UPDATE ON loader_control\.etl_job\s+"
            r"FOR EACH ROW EXECUTE FUNCTION "
            r"loader_control\.guard_terminal_etl_job_update\(\)",
        )

    def test_destination_has_one_independently_pinned_environment_identity(self):
        identity = _table_body(self.sql, "loader_control.deployment_identity")
        self.assertIn("singleton boolean PRIMARY KEY DEFAULT true", identity)
        self.assertIn("environment_id uuid NOT NULL UNIQUE", identity)
        self.assertIn("database_name name NOT NULL DEFAULT current_database()", identity)
        self.assertIn("deployment_identity_singleton CHECK (singleton)", identity)
        self.assertIn("deployment_identity_uuid_not_nil", identity)
        self.assertIn(
            "INSERT INTO loader_control.deployment_identity DEFAULT VALUES",
            self.sql,
        )
        self.assertIn(
            "GRANT SELECT ON loader_control.deployment_identity TO brerc_loader",
            self.sql,
        )

    def test_publication_rows_are_insert_only_and_cleanup_refuses_active_release(self):
        self.assertIn(
            "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA publication TO brerc_loader",
            self.sql,
        )
        self.assertNotRegex(
            self.sql,
            r"GRANT .*\b(?:UPDATE|DELETE)\b.*SCHEMA publication TO brerc_loader",
        )
        self.assertIn("CREATE FUNCTION loader_control.discard_inactive_candidate", self.sql)
        self.assertIn("candidate_status NOT IN ('failed', 'discarded')", self.sql)
        self.assertIn("s.active_release_id = candidate_release_id", self.sql)
        self.assertIn("only an inactive failed or discarded candidate may be removed", self.sql)

    def test_insert_only_role_cannot_append_to_an_active_release(self):
        self.assertIn(
            "CREATE FUNCTION loader_control.authorize_candidate_writes(candidate_release_id uuid)",
            self.sql,
        )
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION loader_control.authorize_candidate_writes(uuid)",
            self.sql,
        )
        self.assertIn(
            "CREATE FUNCTION loader_control.guard_candidate_release_insert()",
            self.sql,
        )
        guard_start = self.sql.index(
            "CREATE FUNCTION loader_control.guard_candidate_release_insert()"
        )
        guard_end = self.sql.index("$guard_candidate_release_insert$;", guard_start)
        guard = self.sql[guard_start:guard_end]
        self.assertIn("candidate_release_status <> 'candidate'", guard)
        self.assertIn("candidate_job_status <> 'reconciling'", guard)
        self.assertIn("brerc.authorized_candidate_release", guard)
        self.assertIn("durable candidate insert authority is absent", guard)
        self.assertIn("held.pid = pg_catalog.pg_backend_pid()", guard)
        self.assertIn(
            "source session advisory lock is required for durable candidate inserts",
            guard,
        )
        for table in (
            "loader_control.release_manifest",
            "loader_control.withheld_summary",
            "loader_control.source_disposition",
            "publication.public_release",
            "publication.public_species",
            "publication.public_distribution_cell",
            "publication.public_species_year",
            "publication.public_record",
        ):
            with self.subTest(table=table):
                self.assertRegex(
                    self.sql,
                    rf"BEFORE INSERT ON {re.escape(table)}\s+"
                    r"FOR EACH STATEMENT EXECUTE FUNCTION "
                    r"loader_control\.guard_candidate_release_insert\(\)",
                )
                self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", self.sql)
        self.assertGreaterEqual(
            self.sql.count(
                "release_id = pg_catalog.current_setting("
                "'brerc.authorized_candidate_release', true)::uuid"
            ),
            8,
        )

    def test_activation_is_the_only_release_pointer_transition(self):
        self.assertIn(
            "CREATE FUNCTION loader_control.activate_validated_release(candidate_release_id uuid)",
            self.sql,
        )
        self.assertIn("SECURITY DEFINER\nSET search_path = pg_catalog", self.sql)
        self.assertIn("FOR UPDATE OF r, j", self.sql)
        self.assertIn("FOR UPDATE;", self.sql)
        self.assertIn("pg_advisory_xact_lock", self.sql)
        self.assertIn("source pointer and watermark could not be updated exactly once", self.sql)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION loader_control.activate_validated_release(uuid)",
            self.sql,
        )
        self.assertNotRegex(
            self.sql,
            r"GRANT\s+(?:SELECT,\s*INSERT,\s*)?UPDATE\s+ON\s+"
            r"loader_control\.(?:source_state|release)\b",
        )
        self.assertNotRegex(
            self.sql,
            r"GRANT\s+INSERT\s+ON\s+loader_control\.(?:source_state|release)\b",
        )

    def test_identical_retry_records_durable_cleanup_without_blocking_success(self):
        retry_start = self.sql.index("-- A whole-run retry can rebuild data already activated")
        retry_end = self.sql.index(
            "IF candidate_load_mode = 'initial'",
            retry_start,
        )
        retry_branch = self.sql[retry_start:retry_end]
        self.assertIn(
            "SET status = 'discarded',\n                cleanup_pending = true", retry_branch
        )
        self.assertIn("RETURN active_release_id", retry_branch)
        self.assertNotIn("DELETE FROM publication.", retry_branch)
        self.assertNotIn("DELETE FROM loader_control.source_disposition", retry_branch)

    def test_failure_transition_commits_status_outbox_and_cleanup_debt_quickly(self):
        failure_start = self.sql.index("CREATE FUNCTION loader_control.fail_candidate(")
        failure_end = self.sql.index(
            "$fail_candidate$;",
            failure_start,
        )
        failure_function = self.sql[failure_start:failure_end]
        self.assertIn("SET status = 'failed',\n        cleanup_pending = true", failure_function)
        self.assertIn("INSERT INTO loader_control.notification_outbox", failure_function)
        self.assertNotIn("DELETE FROM publication.", failure_function)
        self.assertNotIn("DELETE FROM loader_control.source_disposition", failure_function)

    def test_cleanup_debt_is_constrained_monitored_and_atomically_purged(self):
        release = _table_body(self.sql, "loader_control.release")
        self.assertIn("cleanup_pending boolean NOT NULL DEFAULT false", release)
        self.assertIn("NOT cleanup_pending OR status IN ('failed', 'discarded')", release)
        cleanup_start = self.sql.index("CREATE FUNCTION loader_control.discard_inactive_candidate(")
        cleanup_end = self.sql.index("$discard_inactive_candidate$;", cleanup_start)
        cleanup = self.sql[cleanup_start:cleanup_end]
        for statement in (
            "DELETE FROM publication.public_record",
            "DELETE FROM publication.public_distribution_cell",
            "DELETE FROM publication.public_species_year",
            "DELETE FROM publication.public_species",
            "DELETE FROM publication.public_release",
            "DELETE FROM loader_control.source_disposition",
            "DELETE FROM loader_stage.reconciliation_result",
            "DELETE FROM loader_stage.disposition_delta",
            "DELETE FROM loader_stage.source_inventory",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, cleanup)
        self.assertIn("SET cleanup_pending = false", cleanup)
        self.assertIn("source session advisory lock is required for candidate cleanup", cleanup)
        release_view_start = self.sql.index("CREATE VIEW serve.etl_release_status")
        release_view_end = self.sql.index("FROM loader_control.release;", release_view_start)
        self.assertIn("cleanup_pending", self.sql[release_view_start:release_view_end])

    def test_activation_recomputes_inventory_threshold_and_public_aggregates(self):
        for evidence in (
            "inventory and immutable disposition token sets differ",
            "candidate delta does not describe its complete final snapshot",
            "initial delta is not the complete source snapshot",
            "incremental delta differs from the complete base change set",
            "withheld-reason summary differs from its immutable ledger",
            "approval-bound suppression threshold",
            "FULL JOIN recorded USING (species_id, record_year, cell_id, precision_metres)",
            "FULL JOIN recorded USING (species_id, record_year)",
            "FULL JOIN recorded USING (species_id)",
            "FULL JOIN recorded USING (public_record_id)",
            "source_inventory_count",
            "delta_row_count",
            "d.disposition = 'suppressed'",
            "x.action IN ('upsert', 'withhold', 'suppress')",
            "x.public_record_id",
            "d.public_record_id",
            "manifest.published_basis_count < 1",
            "cell_count < 1",
        ):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, self.sql)

    def test_suppressed_rows_retain_only_safe_cohort_evidence(self):
        dispositions = _table_body(self.sql, "loader_control.source_disposition")
        delta = _table_body(self.sql, "loader_stage.disposition_delta")
        self.assertIn("disposition IN ('eligible', 'withheld', 'suppressed')", dispositions)
        self.assertIn("disposition = 'suppressed'", dispositions)
        self.assertIn("withheld_reason = 'suppressed-sparse-cell'", dispositions)
        self.assertIn("action IN ('upsert', 'withhold', 'suppress', 'delete')", delta)
        self.assertIn("action = 'suppress'", delta)
        self.assertIn("CREATE UNIQUE INDEX source_disposition_public_record_idx", self.sql)

    def test_failure_transition_is_fixed_code_inactive_and_transactional(self):
        self.assertIn("CREATE FUNCTION loader_control.fail_candidate(", self.sql)
        self.assertIn("fixed_failure_code text", self.sql)
        self.assertIn("failure code is outside the fixed operational vocabulary", self.sql)
        self.assertIn("only an inactive candidate with a nonterminal job may fail", self.sql)
        self.assertIn("Exact absence is already clean", self.sql)
        self.assertIn("fixed_failure_code NOT IN", self.sql)
        self.assertIn("'etl_failed'", self.sql)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION loader_control.fail_candidate(uuid, text)",
            self.sql,
        )

    def test_dead_worker_recovery_requires_the_session_lock_and_fails_closed(self):
        self.assertIn(
            "CREATE FUNCTION loader_control.recover_orphaned_job(orphan_source_id text)",
            self.sql,
        )
        self.assertIn("source session advisory lock is required for orphan recovery", self.sql)
        self.assertIn("held.pid = pg_catalog.pg_backend_pid()", self.sql)
        self.assertIn("orphan recovery refuses an active or retired release", self.sql)
        self.assertIn("failure_code = 'WORKER_LOST'", self.sql)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION loader_control.recover_orphaned_job(text)",
            self.sql,
        )

    def test_success_and_resumable_cleanup_remove_job_scoped_stage_evidence(self):
        for table, delete_statement in (
            (
                "loader_stage.reconciliation_result",
                "DELETE FROM loader_stage.reconciliation_result",
            ),
            ("loader_stage.disposition_delta", "DELETE FROM loader_stage.disposition_delta"),
            ("loader_stage.source_inventory", "DELETE FROM loader_stage.source_inventory"),
        ):
            with self.subTest(table=table):
                self.assertGreaterEqual(self.sql.count(delete_statement), 2)

    def test_loader_cannot_insert_or_update_activation_columns(self):
        self.assertIn(
            "GRANT INSERT (source_id) ON loader_control.source_state TO brerc_loader",
            self.sql,
        )
        self.assertIn(
            "release_id, source_id, job_id, base_release_id, load_mode",
            self.sql,
        )
        grants_tail = self.sql[self.sql.index("GRANT USAGE ON SCHEMA loader_control") :]
        self.assertNotRegex(grants_tail, r"GRANT .*active_release_id")
        self.assertNotRegex(grants_tail, r"GRANT .*result_release_id")
        self.assertNotRegex(grants_tail, r"GRANT .*failure_code")
        self.assertNotRegex(
            grants_tail,
            r"GRANT\s+UPDATE\s*(?:\([^)]*\)\s*)?ON\s+"
            r"loader_control\.notification_outbox",
        )

    def test_public_and_group_role_grants_are_least_privilege(self):
        for role in ("brerc_loader", "brerc_api", "brerc_martin", "brerc_monitor"):
            with self.subTest(role=role):
                self.assertIn(role, self.roles)
                self.assertIn(role, self.sql)
        for schema in ("loader_control", "loader_stage", "publication", "serve"):
            self.assertIn(schema, self.sql)
        self.assertIn(
            "REVOKE ALL ON SCHEMA loader_control, loader_stage, publication, serve FROM PUBLIC",
            self.sql,
        )
        self.assertNotRegex(
            self.sql,
            r"GRANT .*loader_(?:control|stage).* TO brerc_(?:api|martin|monitor)",
        )
        self.assertIn(
            "GRANT SELECT ON serve.public_release, serve.public_distribution_cell TO brerc_martin",
            self.sql,
        )

    def test_group_roles_are_non_login_and_refuse_unsafe_existing_roles(self):
        for attribute in (
            "NOLOGIN",
            "NOINHERIT",
            "NOSUPERUSER",
            "NOCREATEDB",
            "NOCREATEROLE",
            "NOREPLICATION",
            "NOBYPASSRLS",
        ):
            self.assertIn(attribute, self.roles)
        self.assertIn("refusing to alter it", self.roles)
        self.assertIn("pg_catalog.pg_auth_members", self.roles)
        self.assertIn("refusing effective privilege leakage", self.roles)
        self.assertIn("pg_catalog.pg_auth_members", self.sql)
        self.assertNotRegex(self.roles, r"(?i)PASSWORD\s+")

    def test_no_embedded_connection_or_private_key_material(self):
        combined = "\n".join((self.sql, self.roles, self.readme))
        for marker in (
            "postgres://",
            "postgresql://",
            "BEGIN PRIVATE KEY",
            "BEGIN RSA PRIVATE KEY",
            "password=",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker.casefold(), combined.casefold())

    def test_documentation_keeps_external_guarantees_blocked(self):
        normalised = " ".join(self.readme.split())
        for statement in (
            "not a production release approval",
            "date_mdb_modified",
            "non-null, unique, stable and never reused",
            "deletion/withdrawal signal",
            "aggregate-only",
            "previous release visible",
            "inclusive",
            "never resumed from the token",
            "taxa_nb",
            "verification_available",
        ):
            with self.subTest(statement=statement):
                self.assertIn(statement, normalised)


if __name__ == "__main__":
    unittest.main(verbosity=2)
