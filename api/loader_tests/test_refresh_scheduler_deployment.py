"""Static acceptance checks for the inert production refresh templates."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
DEPLOYMENT = REPOSITORY / "deploy" / "refresh"
SERVICE = DEPLOYMENT / "brerc-loader-refresh.service.example"
TIMER = DEPLOYMENT / "brerc-loader-refresh.timer.example"
ENVIRONMENT = DEPLOYMENT / "loader-runtime.env.example"
RUNBOOK = DEPLOYMENT / "README.md"


class RefreshSchedulerDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = SERVICE.read_text(encoding="utf-8")
        cls.timer = TIMER.read_text(encoding="utf-8")
        cls.environment = ENVIRONMENT.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")

    def test_only_inert_example_units_are_tracked(self) -> None:
        self.assertTrue(SERVICE.is_file())
        self.assertTrue(TIMER.is_file())
        self.assertFalse((DEPLOYMENT / "brerc-loader-refresh.service").exists())
        self.assertFalse((DEPLOYMENT / "brerc-loader-refresh.timer").exists())
        self.assertIn("neither install nor enable", self.runbook)
        self.assertIn("APPROVED_TO_SCHEDULE", self.service)
        self.assertNotIn("ConditionPathIsExecutable=", self.service)

    def test_service_invokes_only_the_atomic_full_snapshot_refresh(self) -> None:
        exec_lines = [line for line in self.service.splitlines() if line.startswith("Exec")]
        self.assertEqual(
            exec_lines,
            [
                "ExecStart=/opt/brerc-dashboard/current/bin/brerc-load refresh "
                "--config /etc/brerc/refresh/loader.configuration.yaml"
            ],
        )
        forbidden = (
            "nightly_job",
            " incremental",
            " initial",
            "--force",
            "/bin/sh",
            "/bin/bash",
            "bash -",
            "|",
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, "\n".join(exec_lines))
        self.assertIn("Type=oneshot", self.service)
        self.assertIn("Restart=no", self.service)
        self.assertIn("TimeoutStartSec=2h15m", self.service)

    def test_service_uses_a_fixed_unprivileged_identity_and_external_inputs(self) -> None:
        for directive in (
            "User=brerc-loader",
            "Group=brerc-loader",
            "UMask=0077",
            "EnvironmentFile=/etc/brerc/refresh/loader-runtime.env",
            "UnsetEnvironment=PGPASSWORD",
            "ConditionPathExists=/etc/brerc/refresh/APPROVED_TO_SCHEDULE",
            "AssertFileIsExecutable=/opt/brerc-dashboard/current/bin/brerc-load",
            "AssertFileNotEmpty=/etc/brerc/refresh/loader.configuration.yaml",
            "AssertFileNotEmpty=/etc/brerc/refresh/source.configuration.yaml",
            "AssertFileNotEmpty=/etc/brerc/refresh/publication-policy.approved.json",
            "AssertFileNotEmpty=/etc/brerc/refresh/species-dictionary.approved.csv",
        ):
            self.assertIn(directive, self.service)

    def test_service_retains_the_required_hardening(self) -> None:
        for directive in (
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "PrivateDevices=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "RestrictNamespaces=true",
            "RestrictSUIDSGID=true",
            "MemoryDenyWriteExecute=true",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        ):
            self.assertIn(directive, self.service)

    def test_timer_is_persistent_but_its_cadence_is_explicitly_unapproved(self) -> None:
        self.assertIn("OnCalendar=*-*-* 02:30:00 UTC", self.timer)
        self.assertIn("Persistent=true", self.timer)
        self.assertIn("Unit=brerc-loader-refresh.service", self.timer)
        self.assertIn("illustrative, not approved", self.timer)
        self.assertIn("catch-up behaviour", self.timer)

    def test_environment_template_is_external_and_credential_free(self) -> None:
        required = (
            "PGSERVICEFILE=/etc/brerc/refresh/pg_service.conf",
            "BRERC_SOURCE_SERVICE=REPLACE_WITH_APPROVED_SOURCE_SERVICE",
            "BRERC_SOURCE_PASSFILE=/etc/brerc/refresh/source.pgpass",
            "BRERC_SOURCE_SSLROOTCERT=/etc/brerc/refresh/source-ca.pem",
            "BRERC_TARGET_SERVICE=REPLACE_WITH_APPROVED_TARGET_SERVICE",
            "BRERC_TARGET_PASSFILE=/etc/brerc/refresh/target.pgpass",
            "BRERC_TARGET_SSLROOTCERT=/etc/brerc/refresh/target-ca.pem",
            "BRERC_PUBLIC_ID_SECRET=",
            "BRERC_RECONCILIATION_SECRET=",
        )
        for line in required:
            self.assertIn(line, self.environment)
        self.assertNotIn("PGPASSWORD=", self.environment)
        self.assertNotIn("postgresql://", self.environment.lower())
        self.assertIsNone(
            re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.environment)
        )
        secret_values = re.findall(
            r"^BRERC_(?:PUBLIC_ID|RECONCILIATION)_SECRET=(.*)$",
            self.environment,
            flags=re.MULTILINE,
        )
        self.assertEqual(secret_values, ["", ""])

    def test_runbook_covers_preflight_evidence_rollback_and_human_approvals(self) -> None:
        required_phrases = (
            "## Preflight and first controlled refresh",
            "## Acceptance evidence",
            "## Failure and rollback",
            "production host and accountable operator",
            "exact cadence, UTC maintenance window",
            "notification transport, recipients",
            "missed-run/dead-man monitor",
            "browser mocks disabled",
            "previous release is still active",
            "Never source the environment file",
        )
        for phrase in required_phrases:
            self.assertIn(phrase, self.runbook)


if __name__ == "__main__":
    unittest.main()
