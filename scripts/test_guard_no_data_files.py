"""Regression tests for the tracked-data guard."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.guard_no_data_files import check


class TestFixtureDirectoryIsNotExempt(unittest.TestCase):
    def test_force_added_workbook_in_fixture_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            workbook = repo / "web/src/test/fixtures/client.xlsx"
            workbook.parent.mkdir(parents=True)
            workbook.write_bytes(b"synthetic regression fixture")

            subprocess.run(
                ["git", "init", "--quiet", str(repo)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "add",
                    "-f",
                    "web/src/test/fixtures/client.xlsx",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(check(str(repo)), ["web/src/test/fixtures/client.xlsx"])

    def test_dataset_directory_and_renamed_binaries_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            tracked = {
                "survey.GDB/timestamps": b"ordinary-looking member",
                "notes.txt": b"PK\x03\x04renamed workbook",
                "export.txt": b"unique_no,scientific_name,grid_ref,comments\n1,Example,ST57,x\n",
                "cache.bin": b"SQLite format 3\x00renamed database",
                "legacy.bin": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1renamed workbook",
                "README.md": b"# Safe documentation\n",
            }
            for relative_path, contents in tracked.items():
                target = repo / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)

            subprocess.run(
                ["git", "init", "--quiet", str(repo)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "add", "-f", "--", *tracked],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                check(str(repo)),
                [
                    "cache.bin",
                    "export.txt",
                    "legacy.bin",
                    "notes.txt",
                    "survey.GDB/timestamps",
                ],
            )

    def test_force_added_live_view_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            tracked = {
                "evidence/source.brerc-view-capture.json": b'{"view_definition":"internal"}',
                "evidence/source.brerc-view-definition.sql": b"SELECT internal_table",
                "evidence/source.brerc-view-approval.pending.json": b'{"status":"pending"}',
                "evidence/source.brerc-view-approval.json": b'{"approvedBy":"A Person"}',
                "docs/BRERC-postgres db for 180dc-310726-161446.pdf": b"internal view PDF",
                "contracts/public-reference.json": b'{"sha256":"safe non-reversible hash"}',
            }
            for relative_path, contents in tracked.items():
                target = repo / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)

            subprocess.run(
                ["git", "init", "--quiet", str(repo)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "add", "-f", "--", *tracked],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                check(str(repo)),
                [
                    "docs/BRERC-postgres db for 180dc-310726-161446.pdf",
                    "evidence/source.brerc-view-approval.json",
                    "evidence/source.brerc-view-approval.pending.json",
                    "evidence/source.brerc-view-capture.json",
                    "evidence/source.brerc-view-definition.sql",
                ],
            )

    def test_force_added_connector_configuration_and_credentials_are_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            tracked = {
                "api/configuration.yaml": b"connection: internal",
                "api/loader.configuration.yaml": b"target: internal",
                ".pgpass": b"host:port:database:user:password",
                "ops/pgpass.conf": b"host:port:database:user:password",
                "ops/.pg_service.conf": b"[brerc]\nhost=internal",
                "ops/brerc-source.pgpass": b"secret",
                "ops/brerc-source.pg_service.conf": b"internal metadata",
                "ops/brerc-source-client.key": b"private key",
                "ops/brerc-source-client.crt": b"client identity",
                "ops/renamed-private.key": b"private key",
                "ops/renamed.pgpass": b"secret",
                "ops/team.pg_service.conf": b"internal metadata",
                "ops/innocent-looking.pem": b"-----BEGIN PRIVATE KEY-----\nsecret",
                "api/configuration.example.yaml": b"credential-free template",
                "ops/brerc-source-root-ca.crt": b"public CA certificate",
            }
            for relative_path, contents in tracked.items():
                target = repo / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)

            subprocess.run(
                ["git", "init", "--quiet", str(repo)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "add", "-f", "--", *tracked],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                check(str(repo)),
                [
                    ".pgpass",
                    "api/configuration.yaml",
                    "api/loader.configuration.yaml",
                    "ops/.pg_service.conf",
                    "ops/brerc-source-client.crt",
                    "ops/brerc-source-client.key",
                    "ops/brerc-source.pg_service.conf",
                    "ops/brerc-source.pgpass",
                    "ops/innocent-looking.pem",
                    "ops/pgpass.conf",
                    "ops/renamed-private.key",
                    "ops/renamed.pgpass",
                    "ops/team.pg_service.conf",
                ],
            )


if __name__ == "__main__":
    unittest.main()
