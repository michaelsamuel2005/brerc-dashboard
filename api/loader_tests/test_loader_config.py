"""Fail-closed tests for the release loader's target configuration."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from brerc_loader.config import (
    BRERC_TARGET_APPLICATION_NAME,
    MAX_CONFIG_BYTES,
    MAX_PUBLICATION_POLICY_BYTES,
    MAX_SPECIES_DICTIONARY_BYTES,
    LoaderConfigurationError,
    load_loader_config,
)

API_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = API_ROOT / "loader.configuration.example.yaml"
DICTIONARY_ARTIFACT = (
    b"SPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE,EXTRA\nSYNTH-1,Synthetic alpha,Alpha,No,ignored\n"
)

ENVIRONMENT = {
    "BRERC_TARGET_SERVICE": "brerc-ui-writer",
    "PGSERVICEFILE": "/run/secrets/brerc/target-pg-service.conf",
    "BRERC_TARGET_PASSFILE": "/run/secrets/brerc/target.pgpass",
    "BRERC_TARGET_SSLROOTCERT": "/run/secrets/brerc/target-root.crt",
    "BRERC_RECONCILIATION_SECRET": "r" * 32,
    "BRERC_PUBLIC_ID_SECRET": "p" * 32,
    "BRERC_TARGET_HOST": "ui-db.example.invalid",
    "BRERC_TARGET_PORT": "5432",
    "BRERC_TARGET_DATABASE": "brerc_ui",
    "BRERC_TARGET_USER": "brerc_release_loader",
}


def template_document() -> dict[str, object]:
    document = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    # The checked-in template is intentionally non-runnable until BRERC has
    # approved real activation bounds. Tests supply explicit synthetic bounds.
    document["runtime"]["initial_min_source_rows"] = 1
    document["runtime"]["initial_max_source_rows"] = 10_000_000
    document["runtime"]["expected_target_environment_id"] = "11111111-1111-4111-8111-111111111111"
    return document


def direct_document() -> dict[str, object]:
    document = template_document()
    document["runtime"]["expected_target_database"] = "brerc_ui"
    document["runtime"]["expected_target_role"] = "brerc_release_loader"
    document["target_connection"] = {
        "mode": "direct",
        "host_env": "BRERC_TARGET_HOST",
        "port_env": "BRERC_TARGET_PORT",
        "database_env": "BRERC_TARGET_DATABASE",
        "user_env": "BRERC_TARGET_USER",
        "passfile_env": "BRERC_TARGET_PASSFILE",
        "sslrootcert_env": "BRERC_TARGET_SSLROOTCERT",
        "sslmode": "verify-full",
    }
    return document


class ConfigCase(unittest.TestCase):
    def load_document(
        self,
        document: object,
        *,
        environ: dict[str, str] | None = None,
        policy_artifact: bytes = b'{"policy":"synthetic-test-only"}\n',
        dictionary_artifact: bytes = DICTIONARY_ARTIFACT,
    ):
        with tempfile.TemporaryDirectory() as temporary_directory:
            document = copy.deepcopy(document)
            if isinstance(document, dict) and isinstance(document.get("publication"), dict):
                publication = document["publication"]
                artifact_path = Path(temporary_directory, "approved-policy.json")
                artifact_path.write_bytes(policy_artifact)
                if publication.get("policy_path") == "/etc/brerc/publication-policy.approved.json":
                    publication["policy_path"] = str(artifact_path)
                if publication.get("expected_sha256") == "0" * 64:
                    publication["expected_sha256"] = hashlib.sha256(policy_artifact).hexdigest()
            if isinstance(document, dict) and isinstance(document.get("species_dictionary"), dict):
                dictionary = document["species_dictionary"]
                dictionary_path = Path(temporary_directory, "approved-species.csv")
                dictionary_path.write_bytes(dictionary_artifact)
                if dictionary.get("csv_path") == "/etc/brerc/species-dictionary.approved.csv":
                    dictionary["csv_path"] = str(dictionary_path)
                if dictionary.get("expected_raw_sha256") == "0" * 64:
                    dictionary["expected_raw_sha256"] = hashlib.sha256(
                        dictionary_artifact
                    ).hexdigest()
            path = Path(temporary_directory, "loader.yaml")
            path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            return load_loader_config(
                path,
                environ=ENVIRONMENT if environ is None else environ,
            )

    def load_text(
        self,
        text: str,
        *,
        environ: dict[str, str] | None = None,
        policy_artifact: bytes = b'{"policy":"synthetic-test-only"}\n',
        dictionary_artifact: bytes = DICTIONARY_ARTIFACT,
    ):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_path = Path(temporary_directory, "approved-policy.json")
            artifact_path.write_bytes(policy_artifact)
            dictionary_path = Path(temporary_directory, "approved-species.csv")
            dictionary_path.write_bytes(dictionary_artifact)
            text = text.replace(
                "/etc/brerc/publication-policy.approved.json",
                str(artifact_path),
            )
            text = text.replace(
                'expected_sha256: "' + "0" * 64 + '"',
                'expected_sha256: "' + hashlib.sha256(policy_artifact).hexdigest() + '"',
            )
            text = text.replace(
                "/etc/brerc/species-dictionary.approved.csv",
                str(dictionary_path),
            )
            text = text.replace(
                'expected_raw_sha256: "' + "0" * 64 + '"',
                'expected_raw_sha256: "' + hashlib.sha256(dictionary_artifact).hexdigest() + '"',
            )
            text = text.replace("REPLACE_WITH_APPROVED_INITIAL_MINIMUM", "1")
            text = text.replace("REPLACE_WITH_APPROVED_INITIAL_MAXIMUM", "10000000")
            path = Path(temporary_directory, "loader.yaml")
            path.write_text(text, encoding="utf-8")
            return load_loader_config(
                path,
                environ=ENVIRONMENT if environ is None else environ,
            )

    def assert_rejected(
        self,
        document: object,
        *,
        environ: dict[str, str] | None = None,
    ) -> None:
        with self.assertRaises(LoaderConfigurationError):
            self.load_document(document, environ=environ)


class TestValidConfiguration(ConfigCase):
    def test_service_template_is_complete_and_secrets_are_redacted(self) -> None:
        raw_template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(
            raw_template["runtime"]["initial_min_source_rows"],
            "REPLACE_WITH_APPROVED_INITIAL_MINIMUM",
        )
        self.assertEqual(
            raw_template["runtime"]["initial_max_source_rows"],
            "REPLACE_WITH_APPROVED_INITIAL_MAXIMUM",
        )
        self.assertEqual(
            raw_template["runtime"]["expected_target_environment_id"],
            "REPLACE_WITH_TARGET_ENVIRONMENT_UUID",
        )
        config = self.load_document(template_document())
        self.assertEqual(config.version, "brerc-loader-v2")
        self.assertEqual(config.runtime.batch_size, 5000)
        self.assertEqual(config.runtime.initial_min_source_rows, 1)
        self.assertEqual(config.runtime.initial_max_source_rows, 10_000_000)
        self.assertEqual(config.target_connection.mode, "service")
        self.assertEqual(
            config.source_config_path,
            Path("/etc/brerc/source.configuration.yaml"),
        )
        parameters = config.target_connection.parameters()
        self.assertEqual(next(iter(parameters)), "service")
        self.assertEqual(parameters["service"], "brerc-ui-writer")
        self.assertEqual(parameters["sslmode"], "verify-full")
        self.assertEqual(parameters["application_name"], BRERC_TARGET_APPLICATION_NAME)
        self.assertEqual(parameters["connect_timeout"], 15)
        self.assertNotIn("password", parameters)
        self.assertNotIn("dsn", parameters)
        self.assertEqual(config.reconciliation.secret_bytes(), b"r" * 32)
        self.assertEqual(config.publication.public_id_secret_bytes(), b"p" * 32)
        self.assertEqual(
            config.publication.artifact_bytes(),
            b'{"policy":"synthetic-test-only"}\n',
        )
        self.assertEqual(config.species_dictionary.artifact_bytes(), DICTIONARY_ARTIFACT)
        self.assertEqual(
            config.species_dictionary.expected_raw_sha256,
            hashlib.sha256(DICTIONARY_ARTIFACT).hexdigest(),
        )

        rendered = " ".join(
            (
                repr(config),
                repr(config.runtime),
                repr(config.target_connection),
                repr(config.reconciliation),
                repr(config.publication),
                repr(config.species_dictionary),
            )
        )
        for secret_or_infrastructure_value in ENVIRONMENT.values():
            self.assertNotIn(secret_or_infrastructure_value, rendered)
        self.assertNotIn("/etc/brerc/source.configuration.yaml", rendered)
        self.assertNotIn("REPLACE_WITH_UI_DATABASE_NAME", rendered)
        self.assertNotIn("REPLACE_WITH_LOADER_WRITE_ROLE", rendered)
        self.assertNotIn("11111111-1111-4111-8111-111111111111", rendered)
        self.assertNotIn("species-dictionary.approved.csv", rendered)
        self.assertNotIn(hashlib.sha256(DICTIONARY_ARTIFACT).hexdigest(), rendered)

    def test_connection_parameters_are_a_fresh_copy(self) -> None:
        config = self.load_document(template_document())
        first = config.target_connection.parameters()
        first["service"] = "changed"
        self.assertEqual(
            config.target_connection.parameters()["service"],
            "brerc-ui-writer",
        )

    def test_service_file_and_ambient_password_are_rechecked_before_connect(self) -> None:
        connection = self.load_document(template_document()).target_connection
        connection.assert_process_environment({"PGSERVICEFILE": ENVIRONMENT["PGSERVICEFILE"]})
        for process_environment in (
            {},
            {"PGSERVICEFILE": "/different/private/path"},
            {
                "PGSERVICEFILE": ENVIRONMENT["PGSERVICEFILE"],
                "PGPASSWORD": "introduced-after-config-load",
            },
        ):
            with self.subTest(process_environment=process_environment):
                with self.assertRaises(LoaderConfigurationError) as raised:
                    connection.assert_process_environment(process_environment)
                self.assertNotIn("different", str(raised.exception))
                self.assertNotIn("introduced", str(raised.exception))

    def test_direct_tcp_mode_is_explicit_and_target_bound(self) -> None:
        config = self.load_document(direct_document())
        parameters = config.target_connection.parameters()
        self.assertEqual(parameters["host"], "ui-db.example.invalid")
        self.assertEqual(parameters["port"], 5432)
        self.assertEqual(parameters["dbname"], "brerc_ui")
        self.assertEqual(parameters["user"], "brerc_release_loader")
        self.assertNotIn("service", parameters)
        config.target_connection.assert_process_environment({})

    def test_base_package_import_does_not_import_yaml_or_a_database_driver(self) -> None:
        script = (
            "import sys; "
            f"sys.path.insert(0, {str(API_ROOT)!r}); "
            "import brerc_loader; "
            "assert 'yaml' not in sys.modules; "
            "assert not any(n == 'psycopg' or n.startswith('psycopg.') "
            "for n in sys.modules)"
        )
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and literal script
            [sys.executable, "-I", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class TestRestrictedYaml(ConfigCase):
    def test_duplicate_alias_anchor_tag_and_multiple_documents_are_rejected(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        bad_documents = (
            template + "\nloader_config_version: duplicate\n",
            template + "\nprobe: &hidden value\n",
            template + "\nprobe: *hidden\n",
            template + "\nprobe: !!python/name:os.system\n",
            template + "\n---\n{}\n",
        )
        for text in bad_documents:
            with self.subTest(text=text[-40:]), self.assertRaises(LoaderConfigurationError):
                self.load_text(text)

    def test_parser_and_filesystem_failures_never_echo_private_input(self) -> None:
        private_text = "password: [private-value"
        with self.assertRaises(LoaderConfigurationError) as raised:
            self.load_text(private_text)
        self.assertNotIn("private-value", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

        private_path = "/controlled/internal/secret/loader.yaml"
        with self.assertRaises(LoaderConfigurationError) as raised:
            load_loader_config(private_path, environ=ENVIRONMENT)
        self.assertNotIn(private_path, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_only_canonical_integer_spelling_is_typed(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        for replacement in ("batch_size: 05_000", "batch_size: 0x1388"):
            with self.subTest(replacement=replacement), self.assertRaises(LoaderConfigurationError):
                self.load_text(template.replace("batch_size: 5000", replacement))

    def test_empty_invalid_utf8_and_oversized_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory, "loader.yaml")
            for payload in (b"", b"\xff", b"x" * (MAX_CONFIG_BYTES + 1)):
                with self.subTest(length=len(payload)):
                    path.write_bytes(payload)
                    with self.assertRaises(LoaderConfigurationError):
                        load_loader_config(path, environ=ENVIRONMENT)


class TestExactContractAndSecrets(ConfigCase):
    def test_unknown_root_nested_password_dsn_and_bypass_keys_are_rejected(self) -> None:
        for path, value in (
            (("force",), True),
            (("runtime", "skip_validation"), True),
            (("target_connection", "password"), "must-not-be-accepted"),
            (("target_connection", "dsn"), "postgresql://private"),
            (("reconciliation", "secret"), "must-not-be-accepted"),
            (("publication", "public_id_secret"), "must-not-be-accepted"),
            (("species_dictionary", "raw_sha256"), "f" * 64),
        ):
            document = template_document()
            target = document
            for component in path[:-1]:
                target = target[component]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assert_rejected(document)

    def test_pgpassword_missing_values_and_unbounded_values_are_rejected(self) -> None:
        environment_mutations = (
            {**ENVIRONMENT, "PGPASSWORD": "private"},
            {**ENVIRONMENT, "PGPASSWORD": ""},
            {key: value for key, value in ENVIRONMENT.items() if key != "BRERC_TARGET_PASSFILE"},
            {**ENVIRONMENT, "BRERC_TARGET_SERVICE": "x" * 4097},
            {**ENVIRONMENT, "BRERC_TARGET_SERVICE": "has newline\n"},
        )
        for environment in environment_mutations:
            with self.subTest(keys=tuple(environment)):
                self.assert_rejected(template_document(), environ=environment)

    def test_reconciliation_secret_is_required_and_at_least_32_utf8_bytes(self) -> None:
        for environment in (
            {
                key: value
                for key, value in ENVIRONMENT.items()
                if key != "BRERC_RECONCILIATION_SECRET"
            },
            {**ENVIRONMENT, "BRERC_RECONCILIATION_SECRET": "x" * 31},
        ):
            with self.subTest(environment=tuple(environment)):
                self.assert_rejected(template_document(), environ=environment)

        unicode_secret = {**ENVIRONMENT, "BRERC_RECONCILIATION_SECRET": "£" * 16}
        config = self.load_document(template_document(), environ=unicode_secret)
        self.assertEqual(len(config.reconciliation.secret_bytes()), 32)

    def test_public_id_secret_is_required_long_and_independent(self) -> None:
        missing = {
            key: value for key, value in ENVIRONMENT.items() if key != "BRERC_PUBLIC_ID_SECRET"
        }
        for environment in (
            missing,
            {**ENVIRONMENT, "BRERC_PUBLIC_ID_SECRET": "x" * 31},
            {**ENVIRONMENT, "BRERC_PUBLIC_ID_SECRET": ENVIRONMENT["BRERC_RECONCILIATION_SECRET"]},
        ):
            with self.subTest(environment=tuple(environment)):
                self.assert_rejected(template_document(), environ=environment)

        document = template_document()
        document["publication"]["public_id_secret_env"] = next(
            key for key in ENVIRONMENT if key.startswith("BRERC_RECONCILIATION")
        )
        self.assert_rejected(document)

    def test_policy_artifact_is_absolute_bounded_and_exactly_digest_bound(self) -> None:
        exact = b'{\r\n  "policy": "synthetic"\r\n}\r\n'
        config = self.load_document(template_document(), policy_artifact=exact)
        self.assertEqual(config.publication.artifact_bytes(), exact)
        self.assertEqual(
            config.publication.expected_sha256,
            hashlib.sha256(exact).hexdigest(),
        )

        wrong_digest = template_document()
        wrong_digest["publication"]["expected_sha256"] = "f" * 64
        self.assert_rejected(wrong_digest)
        for artifact in (b"", b"x" * (MAX_PUBLICATION_POLICY_BYTES + 1)):
            with self.subTest(length=len(artifact)), self.assertRaises(LoaderConfigurationError):
                self.load_document(template_document(), policy_artifact=artifact)

        for policy_path in ("relative-policy.json", "/private/policy.yaml"):
            document = template_document()
            document["publication"]["policy_path"] = policy_path
            with self.subTest(policy_path=policy_path):
                self.assert_rejected(document)

    def test_dictionary_artifact_is_absolute_bounded_and_exactly_raw_digest_bound(self) -> None:
        exact = (
            b"\xef\xbb\xbfSPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE\r\n"
            b"SYNTH-1,Synthetic alpha,Alpha,No\r\n"
        )
        config = self.load_document(template_document(), dictionary_artifact=exact)
        self.assertEqual(config.species_dictionary.artifact_bytes(), exact)
        self.assertEqual(
            config.species_dictionary.expected_raw_sha256,
            hashlib.sha256(exact).hexdigest(),
        )
        self.assertEqual(MAX_SPECIES_DICTIONARY_BYTES, 128 * 1024 * 1024)

        wrong_digest = template_document()
        wrong_digest["species_dictionary"]["expected_raw_sha256"] = "f" * 64
        self.assert_rejected(wrong_digest)
        with self.assertRaises(LoaderConfigurationError):
            self.load_document(template_document(), dictionary_artifact=b"")
        with (
            mock.patch("brerc_loader.config.MAX_SPECIES_DICTIONARY_BYTES", 4),
            self.assertRaises(LoaderConfigurationError),
        ):
            self.load_document(template_document(), dictionary_artifact=b"12345")

        for csv_path in ("relative-species.csv", "/private/species.txt"):
            document = template_document()
            document["species_dictionary"]["csv_path"] = csv_path
            with self.subTest(csv_path=csv_path):
                self.assert_rejected(document)

    def test_initial_activation_bounds_are_positive_ordered_and_bounded(self) -> None:
        for minimum, maximum in (
            (0, 1),
            (1, 0),
            (20, 10),
            (1, 1_000_000_001),
            (True, 10),
        ):
            document = template_document()
            document["runtime"]["initial_min_source_rows"] = minimum
            document["runtime"]["initial_max_source_rows"] = maximum
            with self.subTest(minimum=minimum, maximum=maximum):
                self.assert_rejected(document)

    def test_paths_are_absolute_pairwise_distinct_and_not_the_source_config(self) -> None:
        mutations = (
            {**ENVIRONMENT, "BRERC_TARGET_PASSFILE": "relative.pgpass"},
            {
                **ENVIRONMENT,
                "BRERC_TARGET_SSLROOTCERT": ENVIRONMENT["BRERC_TARGET_PASSFILE"],
            },
            {
                **ENVIRONMENT,
                "PGSERVICEFILE": ENVIRONMENT["BRERC_TARGET_PASSFILE"],
            },
            {
                **ENVIRONMENT,
                "BRERC_TARGET_PASSFILE": "/etc/brerc/source.configuration.yaml",
            },
        )
        for environment in mutations:
            with self.subTest(environment=environment):
                self.assert_rejected(template_document(), environ=environment)

    def test_service_file_variable_and_tls_mode_are_fixed(self) -> None:
        for key, value in (
            ("service_file_env", "BRERC_TARGET_SERVICE_FILE"),
            ("sslmode", "require"),
        ):
            document = template_document()
            document["target_connection"][key] = value
            with self.subTest(key=key):
                self.assert_rejected(document)

    def test_direct_host_port_and_deployment_identity_are_bounded(self) -> None:
        mutations = (
            {**ENVIRONMENT, "BRERC_TARGET_HOST": "/private/socket/.s.PGSQL.5432"},
            {**ENVIRONMENT, "BRERC_TARGET_HOST": "postgresql://private/db"},
            {**ENVIRONMENT, "BRERC_TARGET_PORT": "0"},
            {**ENVIRONMENT, "BRERC_TARGET_PORT": "5432.0"},
            {**ENVIRONMENT, "BRERC_TARGET_DATABASE": "different_db"},
            {**ENVIRONMENT, "BRERC_TARGET_USER": "different_role"},
        )
        for environment in mutations:
            with self.subTest(environment=environment):
                self.assert_rejected(direct_document(), environ=environment)

    def test_target_environment_identity_must_be_canonical_and_non_nil(self) -> None:
        for value in (
            "00000000-0000-0000-0000-000000000000",
            "11111111111141118111111111111111",
            "11111111-1111-4111-8111-11111111111A",
            "not-a-uuid",
            123,
            None,
        ):
            document = template_document()
            document["runtime"]["expected_target_environment_id"] = value
            with self.subTest(value=value):
                self.assert_rejected(document)

    def test_manual_dataclass_changes_cannot_bypass_controls(self) -> None:
        config = self.load_document(template_document())
        connection = config.target_connection
        unsafe_parameters = (*connection._resolved_parameters, ("password", "private"))
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(connection, _resolved_parameters=unsafe_parameters)
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(connection, sslmode="require")
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(config.runtime, batch_size=True)
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(
                config.runtime,
                expected_target_environment_id="11111111-1111-4111-8111-111111111111",
            )
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(
                config.runtime,
                initial_min_source_rows=config.runtime.initial_max_source_rows + 1,
            )
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(
                config.reconciliation,
                _secret=b"short",
            )
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(config.publication, _artifact=b"changed")
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(config.publication, _public_id_secret=b"short")
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(config.species_dictionary, _artifact=b"changed")
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(config.species_dictionary, csv_path=Path("relative.csv"))
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(
                config,
                source_config_path=config.species_dictionary.csv_path,
            )
        with self.assertRaises(LoaderConfigurationError):
            dataclasses.replace(
                config,
                publication=dataclasses.replace(
                    config.publication,
                    public_id_secret_env=config.reconciliation.secret_env,
                    _public_id_secret=config.reconciliation.secret_bytes(),
                ),
            )


if __name__ == "__main__":
    unittest.main()
