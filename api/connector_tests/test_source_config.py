"""Fail-closed tests for trusted PostgreSQL connector configuration."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

import yaml

from brerc_source.config import (
    BRERC_SOURCE_APPLICATION_NAME,
    MAX_CONFIG_BYTES,
    SourceConfigError,
    load_source_config,
)

API_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = API_ROOT / "configuration.example.yaml"

ENVIRONMENT = {
    "BRERC_SOURCE_SERVICE": "brerc-internal",
    "PGSERVICEFILE": "/run/secrets/brerc/pg_service.conf",
    "BRERC_SOURCE_PASSFILE": "/run/secrets/brerc/pgpass",
    "BRERC_SOURCE_SSLROOTCERT": "/run/secrets/brerc/root.crt",
    "BRERC_SOURCE_HOST": "source.example.invalid",
    "BRERC_SOURCE_PORT": "5432",
    "BRERC_SOURCE_DATABASE": "brerc",
    "BRERC_SOURCE_USER": "brerc_dashboard_reader",
}


def template_document() -> dict[str, object]:
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


class ConfigCase(unittest.TestCase):
    def load_document(
        self,
        document: object,
        *,
        environ: dict[str, str] | None = None,
    ):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory, "configuration.yaml")
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            return load_source_config(path, environ=ENVIRONMENT if environ is None else environ)

    def assert_rejected(self, document: object) -> None:
        with self.assertRaises(SourceConfigError):
            self.load_document(document)


class TestValidConfiguration(ConfigCase):
    def test_template_is_complete_and_service_values_are_redacted(self) -> None:
        config = load_source_config(TEMPLATE, environ=ENVIRONMENT)
        self.assertEqual(config.contract_version, "brerc-main-data-dash-2026-07-31")
        self.assertEqual(config.connection.mode, "service")
        self.assertEqual(config.runtime.batch_size, 5000)
        self.assertEqual(config.runtime.source_environment, "brerc-production")
        self.assertEqual(config.source.schema, "dashboard")
        self.assertEqual(config.source.object, "main_data_dash")
        self.assertEqual(config.column_map.sensitivity, "sensitive")
        self.assertEqual(config.projection[-1], "sensitive")
        parameters = config.connection.parameters()
        self.assertEqual(next(iter(parameters)), "service")
        self.assertEqual(tuple(parameters)[-1], "connect_timeout")
        self.assertEqual(parameters["service"], "brerc-internal")
        self.assertEqual(parameters["sslmode"], "verify-full")
        self.assertEqual(parameters["application_name"], BRERC_SOURCE_APPLICATION_NAME)
        self.assertNotIn("servicefile", parameters)
        self.assertNotIn("password", parameters)
        rendered = repr(config) + repr(config.connection)
        for secret_or_infrastructure_value in (
            "brerc-internal",
            "/run/secrets/brerc/pg_service.conf",
            "/run/secrets/brerc/pgpass",
            "/run/secrets/brerc/root.crt",
            "source.example.invalid",
            "brerc_dashboard_reader",
        ):
            self.assertNotIn(secret_or_infrastructure_value, rendered)
        self.assertNotIn("REPLACE_WITH_BRERC_DATABASE_NAME", rendered)
        self.assertNotIn("REPLACE_WITH_READ_ONLY_ROLE_NAME", rendered)

    def test_connection_parameters_are_a_fresh_copy(self) -> None:
        config = load_source_config(TEMPLATE, environ=ENVIRONMENT)
        first = config.connection.parameters()
        first["service"] = "changed"
        self.assertEqual(config.connection.parameters()["service"], "brerc-internal")

    def test_service_file_binding_requires_the_exact_live_process_value(self) -> None:
        config = load_source_config(TEMPLATE, environ=ENVIRONMENT)
        config.connection.assert_process_environment(
            {"PGSERVICEFILE": ENVIRONMENT["PGSERVICEFILE"]}
        )
        for process_environment in ({}, {"PGSERVICEFILE": "/different/private/path"}):
            with self.subTest(process_environment=process_environment):
                with self.assertRaises(SourceConfigError) as raised:
                    config.connection.assert_process_environment(process_environment)
                rendered = str(raised.exception)
                self.assertNotIn("/run/secrets", rendered)
                self.assertNotIn("/different", rendered)

    def test_ambient_pgpassword_is_rejected_at_load_and_before_connect(self) -> None:
        with self.assertRaises(SourceConfigError):
            load_source_config(
                TEMPLATE,
                environ={**ENVIRONMENT, "PGPASSWORD": "must-not-be-used"},
            )

        service = load_source_config(TEMPLATE, environ=ENVIRONMENT)
        with self.assertRaises(SourceConfigError):
            service.connection.assert_process_environment(
                {
                    "PGSERVICEFILE": ENVIRONMENT["PGSERVICEFILE"],
                    "PGPASSWORD": "introduced-after-load",
                }
            )

        document = template_document()
        document["connection"] = {
            "mode": "direct",
            "host_env": "BRERC_SOURCE_HOST",
            "port_env": "BRERC_SOURCE_PORT",
            "database_env": "BRERC_SOURCE_DATABASE",
            "user_env": "BRERC_SOURCE_USER",
            "passfile_env": "BRERC_SOURCE_PASSFILE",
            "sslrootcert_env": "BRERC_SOURCE_SSLROOTCERT",
            "sslmode": "verify-full",
        }
        document["runtime"]["expected_database"] = "brerc"
        document["runtime"]["expected_role"] = "brerc_dashboard_reader"
        direct = self.load_document(document)
        with self.assertRaises(SourceConfigError):
            direct.connection.assert_process_environment({"PGPASSWORD": "introduced-after-load"})

    def test_service_file_uses_only_libpqs_standard_process_variable(self) -> None:
        document = template_document()
        document["connection"]["service_file_env"] = "BRERC_SOURCE_SERVICE_FILE"
        self.assert_rejected(document)

    def test_direct_tcp_mode_is_mutually_exclusive_and_verified(self) -> None:
        document = template_document()
        document["connection"] = {
            "mode": "direct",
            "host_env": "BRERC_SOURCE_HOST",
            "port_env": "BRERC_SOURCE_PORT",
            "database_env": "BRERC_SOURCE_DATABASE",
            "user_env": "BRERC_SOURCE_USER",
            "passfile_env": "BRERC_SOURCE_PASSFILE",
            "sslrootcert_env": "BRERC_SOURCE_SSLROOTCERT",
            "sslmode": "verify-full",
        }
        document["runtime"]["expected_database"] = "brerc"
        document["runtime"]["expected_role"] = "brerc_dashboard_reader"
        parameters = self.load_document(document).connection.parameters()
        # Direct mode does not use process-level service discovery.
        self.load_document(document).connection.assert_process_environment({})
        self.assertEqual(parameters["host"], "source.example.invalid")
        self.assertEqual(parameters["port"], 5432)
        self.assertEqual(parameters["dbname"], "brerc")
        self.assertEqual(parameters["user"], "brerc_dashboard_reader")
        self.assertNotIn("service", parameters)

    def test_parameters_are_accepted_by_real_psycopg_conninfo(self) -> None:
        try:
            from psycopg.conninfo import conninfo_to_dict, make_conninfo
        except ImportError:
            self.skipTest("connector driver extra is not installed")

        service_parameters = load_source_config(
            TEMPLATE, environ=ENVIRONMENT
        ).connection.parameters()
        parsed_service = conninfo_to_dict(make_conninfo(**service_parameters))
        self.assertEqual(parsed_service["service"], "brerc-internal")
        self.assertEqual(parsed_service["sslmode"], "verify-full")
        self.assertNotIn("password", parsed_service)

        document = template_document()
        document["connection"] = {
            "mode": "direct",
            "host_env": "BRERC_SOURCE_HOST",
            "port_env": "BRERC_SOURCE_PORT",
            "database_env": "BRERC_SOURCE_DATABASE",
            "user_env": "BRERC_SOURCE_USER",
            "passfile_env": "BRERC_SOURCE_PASSFILE",
            "sslrootcert_env": "BRERC_SOURCE_SSLROOTCERT",
            "sslmode": "verify-full",
        }
        document["runtime"]["expected_database"] = "brerc"
        document["runtime"]["expected_role"] = "brerc_dashboard_reader"
        direct_parameters = self.load_document(document).connection.parameters()
        parsed_direct = conninfo_to_dict(make_conninfo(**direct_parameters))
        self.assertEqual(parsed_direct["host"], "source.example.invalid")
        self.assertEqual(parsed_direct["sslmode"], "verify-full")
        self.assertNotIn("password", parsed_direct)


class TestRestrictedYaml(ConfigCase):
    def load_text(self, text: str) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory, "configuration.yaml")
            path.write_text(text, encoding="utf-8")
            load_source_config(path, environ=ENVIRONMENT)

    def test_duplicate_key_is_rejected(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8") + "\ncontract_version: duplicate\n"
        with self.assertRaisesRegex(SourceConfigError, "duplicate"):
            self.load_text(text)

    def test_alias_anchor_and_custom_tag_are_rejected(self) -> None:
        for suffix in (
            "\nprobe: &x value\n",
            "\nprobe: *x\n",
            "\nprobe: !!python/name:os.system\n",
        ):
            with self.subTest(suffix=suffix), self.assertRaises(SourceConfigError):
                self.load_text(TEMPLATE.read_text(encoding="utf-8") + suffix)

    def test_multiple_documents_are_rejected(self) -> None:
        with self.assertRaises(SourceConfigError):
            self.load_text(TEMPLATE.read_text(encoding="utf-8") + "\n---\n{}\n")

    def test_parser_failure_suppresses_raw_input_and_cause(self) -> None:
        sensitive_input = "password: [private-value"
        with self.assertRaises(SourceConfigError) as raised:
            self.load_text(sensitive_input)
        self.assertNotIn("private-value", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_filesystem_failure_suppresses_private_path_and_context(self) -> None:
        private_path = "/controlled/internal/secret/configuration.yaml"
        with self.assertRaises(SourceConfigError) as raised:
            load_source_config(private_path, environ=ENVIRONMENT)
        self.assertNotIn(private_path, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_yaml_1_1_boolean_shorthands_and_case_variants_are_rejected(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        for scalar in ("yes", "no", "on", "off", "Yes", "No", "ON", "OFF", "True", "False"):
            text = template.replace("strict_schema: true", f"strict_schema: {scalar}")
            with self.subTest(scalar=scalar), self.assertRaises(SourceConfigError):
                self.load_text(text)

    def test_only_canonical_integer_and_null_spellings_are_typed(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        for original, replacement in (
            ("batch_size: 5000", "batch_size: 05_000"),
            ("batch_size: 5000", "batch_size: 0x1388"),
            ("place: null", "place: Null"),
            ("place: null", "place: ~"),
        ):
            with self.subTest(replacement=replacement), self.assertRaises(SourceConfigError):
                self.load_text(template.replace(original, replacement))

    def test_empty_and_oversized_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory, "configuration.yaml")
            for payload in ("", "x" * (MAX_CONFIG_BYTES + 1)):
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(SourceConfigError):
                    load_source_config(path, environ=ENVIRONMENT)


class TestExactContract(ConfigCase):
    def test_unknown_root_and_nested_keys_are_rejected(self) -> None:
        for path, value in (
            (("force",), True),
            (("source", "skip_schema_check"), True),
            (("connection", "password"), "do-not-accept"),
            (("connection", "dsn"), "postgresql://secret"),
        ):
            document = template_document()
            target = document
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assert_rejected(document)

    def test_contract_source_columns_mapping_and_projection_cannot_drift(self) -> None:
        mutations = []
        document = template_document()
        document["contract_version"] = "unapproved-version"
        mutations.append(document)
        document = template_document()
        document["source"]["strict_schema"] = False
        mutations.append(document)
        document = template_document()
        document["source_columns"][0] = "renamed"
        mutations.append(document)
        document = template_document()
        document["projection"].append("easting")
        mutations.append(document)
        document = template_document()
        document["mapping"]["sensitivity"] = None
        mutations.append(document)
        document = template_document()
        document["incremental"]["status"] = "enabled"
        mutations.append(document)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_rejected(mutation)

    def test_list_order_duplicates_and_wildcards_are_rejected(self) -> None:
        for field in ("source_columns", "projection"):
            for operation in ("reverse", "duplicate", "wildcard"):
                document = template_document()
                values = document[field]
                if operation == "reverse":
                    values.reverse()
                elif operation == "duplicate":
                    values.append(values[0])
                else:
                    values[0] = "*"
                with self.subTest(field=field, operation=operation):
                    self.assert_rejected(document)


class TestConnectionAndRuntimeSafety(ConfigCase):
    def test_manual_dataclass_construction_cannot_bypass_the_parser(self) -> None:
        config = load_source_config(TEMPLATE, environ=ENVIRONMENT)
        unsafe_parameters = (*config.connection._resolved_parameters, ("password", "hidden"))
        with self.assertRaises(SourceConfigError):
            dataclasses.replace(config.connection, _resolved_parameters=unsafe_parameters)
        with self.assertRaises(SourceConfigError):
            dataclasses.replace(
                config.connection,
                _resolved_parameters=tuple(reversed(config.connection._resolved_parameters)),
            )
        with self.assertRaises(SourceConfigError):
            dataclasses.replace(config.connection, sslmode="require")
        with self.assertRaises(SourceConfigError):
            dataclasses.replace(config.runtime, batch_size=True)
        with self.assertRaises(SourceConfigError):
            dataclasses.replace(config, projection=("*",))

        direct_document = template_document()
        direct_document["connection"] = {
            "mode": "direct",
            "host_env": "BRERC_SOURCE_HOST",
            "port_env": "BRERC_SOURCE_PORT",
            "database_env": "BRERC_SOURCE_DATABASE",
            "user_env": "BRERC_SOURCE_USER",
            "passfile_env": "BRERC_SOURCE_PASSFILE",
            "sslrootcert_env": "BRERC_SOURCE_SSLROOTCERT",
            "sslmode": "verify-full",
        }
        direct_document["runtime"]["expected_database"] = "brerc"
        direct_document["runtime"]["expected_role"] = "brerc_dashboard_reader"
        direct = self.load_document(direct_document)
        unsafe_host_parameters = tuple(
            (key, "postgresql://internal/brerc" if key == "host" else value)
            for key, value in direct.connection._resolved_parameters
        )
        with self.assertRaises(SourceConfigError):
            dataclasses.replace(
                direct.connection,
                _resolved_parameters=unsafe_host_parameters,
            )

    def test_weak_tls_inline_credentials_and_mixed_modes_are_rejected(self) -> None:
        document = template_document()
        document["connection"]["sslmode"] = "require"
        self.assert_rejected(document)

        document = template_document()
        document["connection"]["host_env"] = "BRERC_SOURCE_HOST"
        self.assert_rejected(document)

        document = template_document()
        document["connection"]["service_env"] = "postgresql://user:password@host/db"
        self.assert_rejected(document)

    def test_pgpassword_and_dsn_shaped_host_are_rejected(self) -> None:
        document = template_document()
        document["connection"]["passfile_env"] = "PGPASSWORD"
        self.assert_rejected(document)

        document = template_document()
        document["connection"] = {
            "mode": "direct",
            "host_env": "BRERC_SOURCE_HOST",
            "port_env": "BRERC_SOURCE_PORT",
            "database_env": "BRERC_SOURCE_DATABASE",
            "user_env": "BRERC_SOURCE_USER",
            "passfile_env": "BRERC_SOURCE_PASSFILE",
            "sslrootcert_env": "BRERC_SOURCE_SSLROOTCERT",
            "sslmode": "verify-full",
        }
        document["runtime"]["expected_database"] = "brerc"
        document["runtime"]["expected_role"] = "brerc_dashboard_reader"
        environment = {**ENVIRONMENT, "BRERC_SOURCE_HOST": "postgresql://internal/brerc"}
        with self.assertRaises(SourceConfigError):
            self.load_document(document, environ=environment)

    def test_direct_database_and_role_must_match_deployment_assertions(self) -> None:
        document = template_document()
        document["connection"] = {
            "mode": "direct",
            "host_env": "BRERC_SOURCE_HOST",
            "port_env": "BRERC_SOURCE_PORT",
            "database_env": "BRERC_SOURCE_DATABASE",
            "user_env": "BRERC_SOURCE_USER",
            "passfile_env": "BRERC_SOURCE_PASSFILE",
            "sslrootcert_env": "BRERC_SOURCE_SSLROOTCERT",
            "sslmode": "verify-full",
        }
        # The template's placeholders intentionally differ from the synthetic
        # environment; a deployed copy must explicitly bind both assertions.
        self.assert_rejected(document)

    def test_missing_or_invalid_environment_values_fail_without_disclosure(self) -> None:
        for environment in (
            {},
            {**ENVIRONMENT, "BRERC_SOURCE_PASSFILE": "relative/path"},
            {**ENVIRONMENT, "BRERC_SOURCE_PORT": "not-a-port"},
        ):
            document = template_document()
            if "BRERC_SOURCE_PORT" in environment:
                document["connection"] = {
                    "mode": "direct",
                    "host_env": "BRERC_SOURCE_HOST",
                    "port_env": "BRERC_SOURCE_PORT",
                    "database_env": "BRERC_SOURCE_DATABASE",
                    "user_env": "BRERC_SOURCE_USER",
                    "passfile_env": "BRERC_SOURCE_PASSFILE",
                    "sslrootcert_env": "BRERC_SOURCE_SSLROOTCERT",
                    "sslmode": "verify-full",
                }
            with (
                self.subTest(environment=environment),
                self.assertRaises(SourceConfigError) as caught,
            ):
                self.load_document(document, environ=environment)
            rendered = str(caught.exception)
            for value in environment.values():
                self.assertNotIn(value, rendered)

    def test_every_bounded_integer_rejects_bool_zero_negative_and_huge_values(self) -> None:
        fields = (
            "batch_size",
            "connect_timeout_seconds",
            "lock_timeout_ms",
            "statement_timeout_ms",
            "idle_in_transaction_session_timeout_ms",
            "total_timeout_seconds",
        )
        for field in fields:
            for value in (True, 0, -1, 10**12):
                document = template_document()
                document["runtime"][field] = value
                with self.subTest(field=field, value=value):
                    self.assert_rejected(document)

    def test_statement_timeout_cannot_exceed_total_timeout(self) -> None:
        document = template_document()
        document["runtime"]["statement_timeout_ms"] = 120_000
        document["runtime"]["total_timeout_seconds"] = 60
        self.assert_rejected(document)

    def test_runtime_labels_are_not_interpreted_as_approval(self) -> None:
        document = template_document()
        document["runtime"]["source_environment"] = "../../production"
        self.assert_rejected(document)


if __name__ == "__main__":
    unittest.main()
