"""Static safety contract for notification migration 0002.

The PostgreSQL 16 integration suite must still execute both migrations and the
concurrency protocol.  These dependency-free tests make privilege, redaction,
state-machine and version-guard regressions visible in every Python CI job.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = ROOT / "db" / "migrations" / "0002_notification_delivery.sql"
ROLES_PATH = ROOT / "db" / "notifier_roles.sql"


def _function(sql: str, qualified_name: str) -> str:
    start = sql.index(f"CREATE FUNCTION {qualified_name}(")
    next_function = sql.find("\nCREATE FUNCTION ", start + 1)
    next_view = sql.find("\nCREATE ", start + 1)
    candidates = [position for position in (next_function, next_view) if position >= 0]
    end = min(candidates) if candidates else len(sql)
    return sql[start:end]


def _view(sql: str, qualified_name: str) -> str:
    match = re.search(
        rf"CREATE (?:OR REPLACE )?VIEW {re.escape(qualified_name)}\b(.*?);",
        sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"view {qualified_name} is absent")
    return match.group(1)


class NotificationMigrationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.roles = ROLES_PATH.read_text(encoding="utf-8")

    def test_migration_is_transactional_ordered_and_versioned(self) -> None:
        self.assertRegex(self.sql, r"(?m)^BEGIN;$")
        self.assertRegex(self.sql, r"(?m)^COMMIT;$")
        self.assertIn("pg_advisory_xact_lock", self.sql)
        self.assertIn("history_count <> 1", self.sql)
        self.assertIn("migration_version = 1", self.sql)
        self.assertIn("migration_key = '0001_publication_store'", self.sql)
        self.assertIn("'0002_notification_delivery'", self.sql)
        self.assertLess(
            self.sql.index("CREATE FUNCTION loader_control.claim_notifications"),
            self.sql.index("INSERT INTO loader_control.schema_migration"),
        )

    def test_unreviewed_legacy_delivery_state_is_not_invented(self) -> None:
        self.assertIn("DO $legacy_state_guard$", self.sql)
        for condition in (
            "status <> 'pending'",
            "attempt_count <> 0",
            "locked_at IS NOT NULL",
            "delivered_at IS NOT NULL",
        ):
            with self.subTest(condition=condition):
                self.assertIn(condition, self.sql)

    def test_two_notifier_roles_are_safe_nologin_capabilities(self) -> None:
        for role in ("brerc_notifier", "brerc_notifier_operator"):
            with self.subTest(role=role):
                self.assertIn(f"'{role}'", self.roles)
                self.assertIn(f"'{role}'", self.sql)
        posture = (
            "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
            "'\n                'NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )
        self.assertIn(posture, self.roles)
        for check in (
            "rolcanlogin",
            "rolinherit",
            "rolsuper",
            "rolcreatedb",
            "rolcreaterole",
            "rolreplication",
            "rolbypassrls",
            "pg_catalog.pg_auth_members",
        ):
            with self.subTest(check=check):
                self.assertIn(check, self.roles)

        required_roles = self.sql[
            self.sql.index("DO $required_roles$") : self.sql.index(
                "DO $legacy_state_guard$"
            )
        ]
        for catalog in (
            "pg_catalog.pg_db_role_setting",
            "pg_catalog.pg_shdepend",
            "pg_catalog.pg_database",
            "pg_catalog.pg_default_acl",
            "pg_catalog.pg_namespace",
            "pg_catalog.pg_class",
            "pg_catalog.pg_attribute",
            "pg_catalog.pg_proc",
            "pg_catalog.pg_type",
            "pg_catalog.pg_language",
            "pg_catalog.pg_largeobject_metadata",
            "pg_catalog.pg_foreign_data_wrapper",
            "pg_catalog.pg_foreign_server",
            "pg_catalog.pg_tablespace",
            "pg_catalog.pg_parameter_acl",
        ):
            with self.subTest(catalog=catalog):
                self.assertIn(catalog, required_roles)
        self.assertIn("pg_catalog.aclexplode", required_roles)
        self.assertIn("deptype IN ('o', 'a')", required_roles)
        self.assertIn("defaclrole = role_row.oid", required_roles)
        self.assertIn("direct_acl.grantee = role_row.oid", required_roles)
        self.assertIn("pristine NOLOGIN capability role", required_roles)

    def test_outbox_has_lease_retry_dead_letter_and_lifetime_audit_state(self) -> None:
        for column in (
            "delivery_cycle integer NOT NULL DEFAULT 1",
            "total_attempt_count bigint NOT NULL DEFAULT 0",
            "max_attempts smallint NOT NULL DEFAULT 8",
            "claim_token uuid",
            "lease_expires_at timestamp with time zone",
            "dead_lettered_at timestamp with time zone",
            "last_delivery_failure_code text",
        ):
            with self.subTest(column=column):
                self.assertIn(column, self.sql)
        self.assertIn("'dead_letter'", self.sql)
        self.assertIn("attempt_count <= max_attempts", self.sql)
        self.assertIn("total_attempt_count >= attempt_count", self.sql)
        self.assertIn("max_attempts BETWEEN 1 AND 32", self.sql)
        self.assertIn("notification_outbox_claim_token_not_nil", self.sql)

    def test_delivery_audit_is_typed_and_contains_no_free_text(self) -> None:
        start = self.sql.index("CREATE TABLE loader_control.notification_delivery_event")
        end = self.sql.index("CREATE INDEX notification_delivery_event_notification_time_idx")
        event_table = self.sql[start:end]
        for field in (
            "delivery_cycle integer NOT NULL",
            "cycle_attempt integer NOT NULL",
            "total_attempt_count bigint NOT NULL",
            "event_code text NOT NULL",
            "delivery_failure_code text",
            "operator_reason_code text",
            "duration_ms bigint",
        ):
            with self.subTest(field=field):
                self.assertIn(field, event_table)
        for unsafe in ("message_body", "exception", "provider_response", "email_address", "webhook"):
            with self.subTest(unsafe=unsafe):
                self.assertNotIn(unsafe, event_table.casefold())

    def test_claim_is_bounded_concurrent_and_lease_tokened(self) -> None:
        claim = _function(self.sql, "loader_control.claim_notifications")
        self.assertIn("requested_limit NOT BETWEEN 1 AND 100", claim)
        self.assertIn("requested_lease_seconds NOT BETWEEN 30 AND 900", claim)
        self.assertGreaterEqual(claim.count("FOR UPDATE OF o SKIP LOCKED"), 2)
        self.assertIn("generated_token := pg_catalog.gen_random_uuid()", claim)
        self.assertIn("total_attempt_count = candidate.total_attempt_count + 1", claim)
        self.assertIn("o.lease_expires_at <= pg_catalog.clock_timestamp()", claim)
        self.assertIn("j.finished_at IS NOT NULL", claim)
        self.assertIn("j.failure_code = o.failure_code", claim)
        self.assertNotIn("SELECT o.*", claim)
        for unnecessary in (
            "source_id text",
            "started_at timestamp",
            "source_rows_seen bigint",
            "candidate_rows bigint",
            "rows_withheld bigint",
            "created_at timestamp",
        ):
            with self.subTest(unnecessary=unnecessary):
                self.assertNotIn(unnecessary, claim)

    def test_all_worker_mutations_are_security_definer_with_fixed_search_path(self) -> None:
        functions = (
            "loader_control.claim_notifications",
            "loader_control.renew_notification_lease",
            "loader_control.ack_notification",
            "loader_control.fail_notification",
            "loader_control.requeue_dead_notification",
            "serve.notification_delivery_metrics",
            "serve.notification_worker_preflight",
        )
        for name in functions:
            with self.subTest(name=name):
                body = _function(self.sql, name)
                self.assertIn("SECURITY DEFINER", body)
                self.assertIn("SET search_path = pg_catalog", body)

    def test_acknowledgement_is_claim_bound_and_idempotent(self) -> None:
        ack = _function(self.sql, "loader_control.ack_notification")
        self.assertIn("delivery_row.status = 'delivered'", ack)
        self.assertIn("delivery_row.claim_token = requested_claim_token", ack)
        self.assertIn("delivery_row.status <> 'delivering'", ack)
        self.assertIn("o.lease_expires_at", ack)
        self.assertIn("delivery_row.lease_expires_at IS NULL", ack)
        self.assertIn(
            "delivery_row.lease_expires_at <= pg_catalog.clock_timestamp()",
            ack,
        )
        self.assertLess(
            ack.index("delivery_row.status = 'delivered'"),
            ack.index("delivery_row.lease_expires_at <= pg_catalog.clock_timestamp()"),
        )
        self.assertIn("SET status = 'delivered'", ack)
        self.assertIn("'DELIVERED'", ack)

    def test_failure_codes_and_database_owned_retry_policy_are_fixed(self) -> None:
        fail = _function(self.sql, "loader_control.fail_notification")
        for code in (
            "DELIVERY_TIMEOUT",
            "DELIVERY_CONNECTION_FAILED",
            "DELIVERY_RATE_LIMITED",
            "DELIVERY_PROVIDER_UNAVAILABLE",
            "DELIVERY_AUTHENTICATION_FAILED",
            "DELIVERY_DESTINATION_INVALID",
            "DELIVERY_PAYLOAD_REJECTED",
            "DELIVERY_CONFIGURATION_INVALID",
        ):
            with self.subTest(code=code):
                self.assertIn(f"'{code}'", fail)
        self.assertIn("requested_retry_after_seconds NOT BETWEEN 30 AND 3600", fail)
        self.assertIn("delivery_row.attempt_count < delivery_row.max_attempts", fail)
        self.assertIn("o.lease_expires_at", fail)
        self.assertIn("delivery_row.lease_expires_at IS NULL", fail)
        self.assertIn(
            "delivery_row.lease_expires_at <= pg_catalog.clock_timestamp()",
            fail,
        )
        self.assertLess(
            fail.index("delivery_row.status IN ('delivery_failed', 'dead_letter')"),
            fail.index("delivery_row.lease_expires_at <= pg_catalog.clock_timestamp()"),
        )
        self.assertIn("result_status := 'delivery_failed'", fail)
        self.assertIn("result_status := 'dead_letter'", fail)
        self.assertNotRegex(fail, r"requested_max_attempts|free.?text|error_message")

    def test_redrive_is_operator_only_cycle_preserving_and_fixed_reason(self) -> None:
        redrive = _function(self.sql, "loader_control.requeue_dead_notification")
        self.assertIn("delivery_row.status <> 'dead_letter'", redrive)
        self.assertIn("next_cycle := delivery_row.delivery_cycle + 1", redrive)
        self.assertIn("attempt_count = 0", redrive)
        self.assertNotIn("total_attempt_count = 0", redrive)
        self.assertIn("'REDRIVEN'", redrive)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION loader_control.requeue_dead_notification(uuid, text)\n"
            "TO brerc_notifier_operator",
            self.sql,
        )
        self.assertNotIn(
            "GRANT EXECUTE ON FUNCTION loader_control.requeue_dead_notification(uuid, text)\n"
            "TO brerc_notifier;",
            self.sql,
        )

    def test_worker_and_operator_have_no_raw_table_grant(self) -> None:
        grants = self.sql[self.sql.index("-- A function is executable by PUBLIC") :]
        self.assertNotRegex(
            grants,
            r"GRANT\s+(?:SELECT|INSERT|UPDATE|DELETE|ALL).*\bON\s+(?:TABLE\s+)?"
            r"loader_control\..*\bTO\s+brerc_notifier",
        )
        self.assertIn("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA loader_control", grants)
        for signature in (
            "claim_notifications(integer, integer)",
            "renew_notification_lease(uuid, uuid, integer)",
            "ack_notification(uuid, uuid)",
            "fail_notification(uuid, uuid, text, integer)",
            "requeue_dead_notification(uuid, text)",
            "notification_delivery_metrics()",
            "notification_worker_preflight()",
        ):
            with self.subTest(signature=signature):
                self.assertRegex(grants, rf"REVOKE ALL ON FUNCTION .*{re.escape(signature)} FROM PUBLIC")

        self.assertIn(
            "REVOKE SELECT ON TABLE loader_control.notification_outbox "
            "FROM brerc_loader;",
            grants,
        )
        loader_columns_match = re.search(
            r"GRANT SELECT \((.*?)\) ON "
            r"loader_control\.notification_outbox TO brerc_loader;",
            grants,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(loader_columns_match)
        loader_columns = loader_columns_match.group(1)
        self.assertNotIn("claim_token", loader_columns)
        for required in (
            "notification_id",
            "job_id",
            "event_type",
            "failure_code",
            "status",
            "total_attempt_count",
            "last_delivery_failure_code",
        ):
            with self.subTest(loader_column=required):
                self.assertIn(required, loader_columns)

    def test_monitor_surfaces_are_redacted(self) -> None:
        status_view = _view(self.sql, "serve.etl_notification_status")
        event_view = _view(self.sql, "serve.etl_notification_delivery_event")
        for forbidden in (
            "claim_token",
            "destination_key",
            "failure_code,",
            "locked_at",
            "message",
            "payload",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, status_view)
        self.assertNotIn("claim_token", event_view)
        self.assertIn(
            "GRANT SELECT ON serve.etl_notification_delivery_event TO brerc_monitor",
            self.sql,
        )

    def test_metrics_and_preflight_expose_only_bounded_operational_fields(self) -> None:
        metrics = _function(self.sql, "serve.notification_delivery_metrics")
        for field in (
            "notification_count",
            "total_attempt_count",
            "redrive_count",
            "oldest_ready_at",
            "latest_dead_lettered_at",
        ):
            with self.subTest(field=field):
                self.assertIn(field, metrics)
        self.assertIn("total_attempt_count bigint", metrics)
        self.assertIn("redrive_count bigint", metrics)
        self.assertIn(
            "pg_catalog.sum(o.total_attempt_count)::bigint",
            metrics,
        )
        self.assertIn(
            "pg_catalog.sum(o.delivery_cycle - 1)::bigint",
            metrics,
        )
        for forbidden in ("destination_key", "claim_token", "failure_code", "job_id", "release_id"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, metrics)

        preflight = _function(self.sql, "serve.notification_worker_preflight")
        self.assertIn("m.migration_version = 2", preflight)
        self.assertIn("m.migration_key = '0002_notification_delivery'", preflight)
        self.assertIn("server_version_num integer", preflight)
        self.assertIn("ssl_version text", preflight)
        self.assertIn(
            "pg_catalog.current_setting('server_version_num')::integer",
            preflight,
        )
        self.assertIn("SELECT s.version", preflight)

        expected_start = preflight.index("expected_function(function_oid)")
        expected_end = preflight.index("role_posture AS", expected_start)
        expected_functions = preflight[expected_start:expected_end]
        signatures = (
            "loader_control.claim_notifications(integer,integer)",
            "loader_control.renew_notification_lease(uuid,uuid,integer)",
            "loader_control.ack_notification(uuid,uuid)",
            "loader_control.fail_notification(uuid,uuid,text,integer)",
            "serve.notification_delivery_metrics()",
            "serve.notification_worker_preflight()",
        )
        self.assertEqual(expected_functions.count("pg_catalog.to_regprocedure("), 6)
        for signature in signatures:
            with self.subTest(expected_function=signature):
                self.assertIn(f"'{signature}'", expected_functions)
        self.assertNotIn("requeue_dead_notification", expected_functions)

        for membership_posture in (
            "membership_posture.login_parent_count = 1",
            "membership_posture.notifier_membership_count = 1",
            "membership_posture.notifier_membership_options_safe",
            "membership_posture.notifier_child_count = 1",
            "membership_posture.notifier_parent_count = 0",
            "NOT membership.admin_option",
            "membership.inherit_option",
            "NOT membership.set_option",
        ):
            with self.subTest(membership_posture=membership_posture):
                self.assertIn(membership_posture, preflight)

        for role_posture in (
            "role_posture.login_can_login",
            "role_posture.login_inherits",
            "NOT role_posture.login_super",
            "NOT role_posture.login_create_db",
            "NOT role_posture.login_create_role",
            "NOT role_posture.login_replication",
            "NOT role_posture.login_bypass_rls",
            "NOT role_posture.notifier_can_login",
            "NOT role_posture.notifier_inherits",
            "NOT role_posture.notifier_super",
            "NOT role_posture.notifier_create_db",
            "NOT role_posture.notifier_create_role",
            "NOT role_posture.notifier_replication",
            "NOT role_posture.notifier_bypass_rls",
        ):
            with self.subTest(role_posture=role_posture):
                self.assertIn(role_posture, preflight)

        for direct_acl_surface in (
            "database_acl AS",
            "schema_acl AS",
            "relation_acl AS",
            "column_acl AS",
            "routine_acl AS",
            "type_acl AS",
            "miscellaneous_acl AS",
            "pg_catalog.aclexplode(",
            "database_acl.privilege_type <> 'CONNECT'",
            "schema_acl.privilege_type <> 'USAGE'",
            "routine_acl.privilege_type <> 'EXECUTE'",
            "schema_acl.is_grantable",
            "routine_acl.is_grantable",
        ):
            with self.subTest(direct_acl_surface=direct_acl_surface):
                self.assertIn(direct_acl_surface, preflight)

        for ownership_or_setting_guard in (
            "pg_catalog.pg_db_role_setting",
            "pg_catalog.pg_shdepend",
            "ownership.deptype = 'o'",
            "cross_database_acl.deptype = 'a'",
            "pg_catalog.pg_database",
            "database.datdba IN",
            "pg_catalog.pg_default_acl",
            "default_acl.defaclrole IN",
        ):
            with self.subTest(guard=ownership_or_setting_guard):
                self.assertIn(ownership_or_setting_guard, preflight)

        for database_posture in (
            "pg_catalog.has_database_privilege(",
            "pg_catalog.current_database(),\n                'CONNECT'",
            "pg_catalog.current_database(),\n                'CREATE'",
            "pg_catalog.current_database(),\n                'TEMP'",
            "other_database.datallowconn",
            "other_database.datname <>",
        ):
            with self.subTest(database_posture=database_posture):
                self.assertIn(database_posture, preflight)

        for schema_name in (
            "loader_control",
            "loader_stage",
            "publication",
            "serve",
        ):
            with self.subTest(application_schema=schema_name):
                self.assertIn(f"('{schema_name}'::name)", preflight)

        for effective_privilege_guard in (
            "pg_catalog.has_schema_privilege(",
            "relation.relkind IN ('r', 'p', 'v', 'm', 'f')",
            "pg_catalog.has_table_privilege(",
            "pg_catalog.has_any_column_privilege(",
            "sequence.relkind = 'S'",
            "pg_catalog.has_sequence_privilege(",
            "pg_catalog.has_function_privilege(",
            "WHERE expected_function.function_oid IS NULL",
            "WHERE expected_function.function_oid = routine.oid",
        ):
            with self.subTest(effective_guard=effective_privilege_guard):
                self.assertIn(effective_privilege_guard, preflight)

        self.assertIn(
            "WHERE routine_acl.grantee = role_posture.notifier_oid\n"
            "            ) = 6",
            preflight,
        )
        self.assertIn(
            "WHERE schema_acl.grantee = role_posture.notifier_oid\n"
            "            ) = 2",
            preflight,
        )
        self.assertNotIn("password", preflight.casefold())


if __name__ == "__main__":
    unittest.main()
