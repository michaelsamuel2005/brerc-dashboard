"""Static acceptance checks for the inert production refresh templates."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
DEPLOYMENT = REPOSITORY / "deploy" / "refresh"
SERVICE = DEPLOYMENT / "brerc-loader-refresh.service.example"
APPROVAL_GUARD = DEPLOYMENT / "brerc-loader-refresh-approval-guard.service.example"
QUARANTINE = DEPLOYMENT / "brerc-loader-refresh-quarantine.service.example"
TIMER = DEPLOYMENT / "brerc-loader-refresh.timer.example"
ENVIRONMENT = DEPLOYMENT / "loader-runtime.env.example"
RUNBOOK = DEPLOYMENT / "README.md"


def directives(text: str, name: str) -> list[str]:
    prefix = f"{name}="
    return [line for line in text.splitlines() if line.startswith(prefix)]


class RefreshSchedulerDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = SERVICE.read_text(encoding="utf-8")
        cls.approval_guard = APPROVAL_GUARD.read_text(encoding="utf-8")
        cls.quarantine = QUARANTINE.read_text(encoding="utf-8")
        cls.timer = TIMER.read_text(encoding="utf-8")
        cls.environment = ENVIRONMENT.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")

    def test_only_inert_example_units_are_tracked(self) -> None:
        self.assertTrue(SERVICE.is_file())
        self.assertTrue(APPROVAL_GUARD.is_file())
        self.assertTrue(QUARANTINE.is_file())
        self.assertTrue(TIMER.is_file())
        self.assertFalse((DEPLOYMENT / "brerc-loader-refresh.service").exists())
        self.assertFalse((DEPLOYMENT / "brerc-loader-refresh-approval-guard.service").exists())
        self.assertFalse((DEPLOYMENT / "brerc-loader-refresh-quarantine.service").exists())
        self.assertFalse((DEPLOYMENT / "brerc-loader-refresh.timer").exists())
        self.assertIn("neither install nor enable", self.runbook)
        self.assertIn("APPROVED_TO_SCHEDULE", self.service)
        self.assertNotIn("ConditionPathIsExecutable=", self.service)

    def test_refresh_failure_invokes_the_inert_quarantine_unit(self) -> None:
        self.assertIn("OnFailure=brerc-loader-refresh-quarantine.service", self.service)
        self.assertIn("EXAMPLE ONLY", self.quarantine)
        self.assertNotIn("[Install]", self.quarantine)
        self.assertIn("do not enable it independently", self.runbook)

    def test_approval_guard_disarms_soft_reboot_suspend_and_shutdown(self) -> None:
        self.assertIn(
            "BindsTo=brerc-loader-refresh-approval-guard.service",
            self.timer,
        )
        self.assertIn(
            "After=brerc-loader-refresh-approval-guard.service",
            self.timer,
        )
        for target in ("sleep.target", "systemd-soft-reboot.service"):
            self.assertIn(target, self.approval_guard)
        self.assertIn("shutdown.target", self.approval_guard)
        self.assertEqual(
            directives(self.approval_guard, "ExecStart"),
            ["ExecStart=/usr/bin/test -d /run/brerc/refresh"],
        )
        self.assertEqual(
            directives(self.approval_guard, "ExecStop"),
            ["ExecStop=/usr/bin/rm -f -- /run/brerc/refresh/APPROVED_TO_SCHEDULE"],
        )
        self.assertIn("RemainAfterExit=yes", self.approval_guard)
        self.assertNotIn("/bin/sh", self.approval_guard)
        self.assertNotIn("/bin/bash", self.approval_guard)

    def test_approval_guard_is_root_owned_hardened_and_offline(self) -> None:
        for directive in (
            "User=root",
            "Group=root",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "PrivateDevices=true",
            "PrivateNetwork=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ReadWritePaths=-/run/brerc/refresh",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "RestrictNamespaces=true",
            "RestrictSUIDSGID=true",
            "MemoryDenyWriteExecute=true",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestrictAddressFamilies=AF_UNIX",
        ):
            self.assertIn(directive, self.approval_guard)

    def test_quarantine_removes_only_the_schedule_approval_marker(self) -> None:
        exec_lines = [line for line in self.quarantine.splitlines() if line.startswith("Exec")]
        self.assertEqual(
            exec_lines,
            ["ExecStart=/usr/bin/rm -f -- /run/brerc/refresh/APPROVED_TO_SCHEDULE"],
        )
        self.assertNotIn("/bin/sh", self.quarantine)
        self.assertNotIn("/bin/bash", self.quarantine)
        self.assertNotIn("*", "\n".join(exec_lines))
        self.assertIn("User=root", self.quarantine)
        self.assertIn("Group=root", self.quarantine)
        self.assertIn("Restart=no", self.quarantine)

    def test_quarantine_is_hardened_and_has_no_network_access(self) -> None:
        for directive in (
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "PrivateDevices=true",
            "PrivateNetwork=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ReadWritePaths=-/run/brerc/refresh",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "RestrictNamespaces=true",
            "RestrictSUIDSGID=true",
            "MemoryDenyWriteExecute=true",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "RestrictAddressFamilies=AF_UNIX",
        ):
            self.assertIn(directive, self.quarantine)

    def test_service_invokes_only_the_atomic_full_snapshot_refresh(self) -> None:
        prerequisite_checks = [
            "ExecStartPre=/usr/bin/test -x /opt/brerc-dashboard/releases/"
            "REPLACE_WITH_APPROVED_ARTIFACT_ID/bin/brerc-load",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/loader.configuration.yaml",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/source.configuration.yaml",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/publication-policy.approved.json",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/species-dictionary.approved.csv",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/loader-runtime.env",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/pg_service.conf",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/source.pgpass",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/target.pgpass",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/source-ca.pem",
            "ExecStartPre=/usr/bin/test -s /etc/brerc/refresh/target-ca.pem",
        ]
        self.assertEqual(directives(self.service, "ExecStartPre"), prerequisite_checks)
        self.assertEqual(
            directives(self.service, "ExecStart"),
            [
                "ExecStart=/opt/brerc-dashboard/releases/REPLACE_WITH_APPROVED_ARTIFACT_ID/"
                "bin/brerc-load refresh "
                "--config /etc/brerc/refresh/loader.configuration.yaml"
            ],
        )
        exec_lines = [line for line in self.service.splitlines() if line.startswith("Exec")]
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
            "ConditionPathExists=/run/brerc/refresh/APPROVED_TO_SCHEDULE",
        ):
            self.assertIn(directive, self.service)
        self.assertNotIn("AssertFile", self.service)

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
            "LimitCORE=0",
        ):
            self.assertIn(directive, self.service)

    def test_timer_has_safe_no_catch_up_default_and_unapproved_cadence(self) -> None:
        self.assertIn("OnCalendar=*-*-* 02:30:00 UTC", self.timer)
        self.assertIn("Persistent=false", self.timer)
        self.assertIn("Unit=brerc-loader-refresh.service", self.timer)
        self.assertIn("illustrative, not approved", self.timer)
        self.assertIn("catch-up behaviour", self.timer)
        self.assertIn("does not catch up missed runs", self.timer)

    def test_schedule_approval_is_disarmed_across_all_host_transitions(self) -> None:
        normalised_runbook = " ".join(self.runbook.split())
        self.assertIn(
            "ConditionPathExists=/run/brerc/refresh/APPROVED_TO_SCHEDULE",
            self.service,
        )
        self.assertNotIn("/etc/brerc/refresh/APPROVED_TO_SCHEDULE", self.service)
        self.assertIn("systemd soft reboot preserves `/run`", normalised_runbook)
        self.assertIn("suspend or hibernate", normalised_runbook)
        self.assertIn("must never be recreated automatically", normalised_runbook)
        self.assertIn("stops the timer before sleep", normalised_runbook)
        self.assertIn(
            "An enabled timer may be started again by `timers.target`", normalised_runbook
        )
        self.assertIn("inspect and stop any timer restarted by `timers.target`", normalised_runbook)

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
        normalised_runbook = " ".join(self.runbook.split())
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
            "Re-arming is a new production decision",
            "Never use a wildcard",
            "empty `DropInPaths=`",
            "any override or unexpected drop-in blocks activation",
            "Before any controlled publication attempt",
            "systemctl daemon-reload",
            "path mismatch or digest mismatch blocks this controlled attempt",
            "--threshold=40 --no-pager",
            'database_window_start="$( psql',
            'database_window_end="$( psql',
            "/etc/brerc/operator/pg_service.conf",
            "sole direct/effective group is `brerc_monitor`",
            "one dedicated root Bash shell",
            "set -euo pipefail",
            "set -C",
            "does not already exist",
            "umask 077",
            'mkdir -m 0700 -- "$evidence"',
            'chown root:root -- "$evidence"',
            "failed_attempt_evidence_query.sql",
            "verify_failed_attempt_evidence.py",
            'previous_invocation_id="$( systemctl show "$unit"',
            'systemctl start --no-block "$unit"',
            "--property=Job --value",
            "--set=load_mode=refresh",
            "--expected-environment-id",
            "--expected-database",
            "--expected-role",
            "--expected-window-start",
            "--expected-window-end",
            "unattended scheduled failure",
            "SCHEDULED_WINDOW_START_UTC",
            "EXACT_FAILED_INVOCATION_ID",
            "do not claim a zero-job result",
            "**before** any `systemctl reset-failed`, restart or host reboot",
            "a reboot is not supported by this recovery path",
            "systemd `Assert*` directives",
            '"$evidence/database-window.json"',
            "--database-window-json",
            "--unit-properties",
            "--journal-json",
            "immutable/single-use evidence system",
            "within 60 seconds",
            "operator-initiated stop",
            "approval guard",
            "/etc/systemd/system/brerc-loader-refresh-approval-guard.service",
            "all four units",
            "all three services",
            "systemctl disable --now brerc-loader-refresh.timer",
            "systemctl stop brerc-loader-refresh-approval-guard.service",
            "--timestamp=unix",
            "InactiveExitTimestamp",
            "StateChangeTimestamp",
            'YYYY-MM-DD\\"T\\"HH24:MI:SS.US\\"Z\\"',
        )
        for phrase in required_phrases:
            self.assertIn(phrase, normalised_runbook)


if __name__ == "__main__":
    unittest.main()
