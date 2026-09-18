"""Static checks for the inert, manually approved first-load example."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
INITIAL = REPOSITORY / "deploy" / "initial"
SERVICE = INITIAL / "brerc-loader-initial.service.example"
RUNBOOK = INITIAL / "README.md"
REFRESH = REPOSITORY / "deploy" / "refresh" / "brerc-loader-refresh.service.example"


def directives(text: str, name: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(f"{name}=")]


class InitialLoaderDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = SERVICE.read_text(encoding="utf-8")
        cls.refresh = REFRESH.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")

    def test_only_an_inert_manual_service_example_is_tracked(self) -> None:
        self.assertTrue(SERVICE.is_file())
        self.assertEqual(sorted(INITIAL.glob("*.service")), [])
        self.assertEqual(sorted(INITIAL.glob("*.timer*")), [])
        self.assertNotIn("[Install]", self.service)
        self.assertEqual(directives(self.service, "Restart"), ["Restart=no"])
        self.assertIn("there is no timer or automatic retry", self.runbook)
        self.assertIn("Checking out this repository installs\nnothing", self.runbook)

    def test_service_invokes_only_initial_without_a_wrapper(self) -> None:
        exec_lines = [line for line in self.service.splitlines() if line.startswith("Exec")]
        self.assertEqual(
            exec_lines,
            [
                "ExecStartPre=+/usr/bin/python3 "
                "/opt/brerc-dashboard/releases/REPLACE_WITH_APPROVED_ARTIFACT_ID/"
                "deploy/initial/consume_initial_approval.py",
                "ExecStart=/opt/brerc-dashboard/releases/REPLACE_WITH_APPROVED_ARTIFACT_ID/"
                "bin/brerc-load initial "
                "--config /etc/brerc/refresh/loader.configuration.yaml"
            ],
        )
        for forbidden in (" refresh", " incremental", "--force", "nightly_job", "/bin/sh", "|"):
            self.assertNotIn(forbidden, "\n".join(exec_lines))
        self.assertEqual(directives(self.service, "Type"), ["Type=oneshot"])

    def test_distinct_manual_approval_is_required_but_not_overclaimed(self) -> None:
        plain_runbook = self.runbook.replace("*", "").lower()
        normalised_runbook = " ".join(self.runbook.split())
        self.assertEqual(directives(self.service, "ConditionPathExists"), [])
        self.assertIn("missing or invalid marker fails the unit", plain_runbook)
        self.assertNotIn("APPROVED_TO_SCHEDULE", self.service)
        self.assertNotIn("ConditionPathIsExecutable=", self.service)
        self.assertIn("consume_initial_approval.py", self.service)
        self.assertNotIn("/opt/brerc-dashboard/current", self.service)
        self.assertIn("REPLACE_WITH_APPROVED_ARTIFACT_ID", self.service)
        self.assertIn("single-use", plain_runbook)
        self.assertIn("consum", plain_runbook)
        self.assertNotIn("not an automatically consumed token", plain_runbook)
        self.assertNotIn("remove it immediately after every start attempt", plain_runbook)
        self.assertIn("A retry requires investigation, a new approval", normalised_runbook)
        self.assertIn(
            "refuses `initial` once an active release exists", normalised_runbook
        )
        self.assertEqual(
            directives(self.service, "ReadWritePaths"),
            ["ReadWritePaths=/etc/brerc/initial-approval"],
        )

    def test_external_inputs_and_unprivileged_runtime_match_refresh(self) -> None:
        for key in (
            "AssertFileIsExecutable",
            "AssertFileNotEmpty",
            "User",
            "Group",
            "UMask",
            "WorkingDirectory",
            "Environment",
            "EnvironmentFile",
            "UnsetEnvironment",
            "TimeoutStartSec",
            "TimeoutStopSec",
            "KillMode",
            "StandardOutput",
            "StandardError",
        ):
            with self.subTest(key=key):
                self.assertEqual(directives(self.service, key), directives(self.refresh, key))
        self.assertNotIn("PGPASSWORD=", self.service)
        self.assertNotIn("postgresql://", self.service.lower())
        self.assertIsNone(
            re.search(r"^BRERC_(?:PUBLIC_ID|RECONCILIATION)_SECRET=", self.service, re.MULTILINE)
        )

    def test_hardening_is_identical_to_the_refresh_service(self) -> None:
        for key in (
            "NoNewPrivileges",
            "PrivateTmp",
            "PrivateDevices",
            "ProtectSystem",
            "ProtectHome",
            "ReadOnlyPaths",
            "ProtectKernelTunables",
            "ProtectKernelModules",
            "ProtectKernelLogs",
            "ProtectControlGroups",
            "ProtectClock",
            "ProtectHostname",
            "ProtectProc",
            "ProcSubset",
            "RestrictNamespaces",
            "RestrictRealtime",
            "RestrictSUIDSGID",
            "LockPersonality",
            "MemoryDenyWriteExecute",
            "CapabilityBoundingSet",
            "AmbientCapabilities",
            "SystemCallArchitectures",
            "RestrictAddressFamilies",
            "RemoveIPC",
            "LimitCORE",
        ):
            with self.subTest(key=key):
                self.assertEqual(directives(self.service, key), directives(self.refresh, key))

    def test_runbook_covers_preflight_outcome_and_retry_boundary(self) -> None:
        normalised_runbook = " ".join(self.runbook.split())
        for phrase in (
            "no active release",
            "network-dark acceptance destination",
            "initial bounds",
            "systemd-analyze verify",
            "root:root` mode `0400",
            "It stays absent after success, failure, timeout, cancellation",
            "Never source the",
            "browser mocks disabled",
            '`mode:"initial"`',
            "no active release was published",
            "inactive cleanup debt",
            "only the separately approved full-snapshot `refresh` path",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalised_runbook)


if __name__ == "__main__":
    unittest.main()
