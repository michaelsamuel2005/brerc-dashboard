"""Static checks for the inert, manually approved first-load example."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
INITIAL = REPOSITORY / "deploy" / "initial"
SERVICE = INITIAL / "brerc-loader-initial.service.example"
QUARANTINE = INITIAL / "brerc-loader-initial-quarantine.service.example"
RUNBOOK = INITIAL / "README.md"
REFRESH = REPOSITORY / "deploy" / "refresh" / "brerc-loader-refresh.service.example"
FAILED_EVIDENCE_QUERY = REPOSITORY / "deploy" / "validation" / "failed_attempt_evidence_query.sql"
RELEASE_EVIDENCE_QUERY = REPOSITORY / "deploy" / "validation" / "release_evidence_query.sql"


def directives(text: str, name: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(f"{name}=")]


class InitialLoaderDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = SERVICE.read_text(encoding="utf-8")
        cls.quarantine = QUARANTINE.read_text(encoding="utf-8")
        cls.refresh = REFRESH.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")
        cls.failed_evidence_query = FAILED_EVIDENCE_QUERY.read_text(encoding="utf-8")
        cls.release_evidence_query = RELEASE_EVIDENCE_QUERY.read_text(encoding="utf-8")

    def test_only_inert_manual_and_quarantine_examples_are_tracked(self) -> None:
        self.assertTrue(SERVICE.is_file())
        self.assertTrue(QUARANTINE.is_file())
        self.assertEqual(sorted(INITIAL.glob("*.service")), [])
        self.assertEqual(sorted(INITIAL.glob("*.timer*")), [])
        self.assertNotIn("[Install]", self.service)
        self.assertEqual(directives(self.service, "Restart"), ["Restart=no"])
        self.assertIn("there is no timer or automatic retry", self.runbook)
        self.assertIn("Checking out this repository installs\nnothing", self.runbook)

    def test_any_failed_start_removes_only_the_initial_marker(self) -> None:
        self.assertIn("OnFailure=brerc-loader-initial-quarantine.service", self.service)
        self.assertEqual(
            directives(self.quarantine, "ExecStart"),
            ["ExecStart=/usr/bin/rm -f -- /etc/brerc/initial-approval/APPROVED_TO_INITIAL"],
        )
        self.assertNotIn("[Install]", self.quarantine)
        self.assertNotIn("/bin/sh", self.quarantine)
        self.assertNotIn("*", "\n".join(directives(self.quarantine, "ExecStart")))
        for directive in (
            "User=root",
            "Group=root",
            "Restart=no",
            "PrivateNetwork=true",
            "ProtectSystem=strict",
            "ReadWritePaths=/etc/brerc/initial-approval",
            "CapabilityBoundingSet=",
            "RestrictAddressFamilies=AF_UNIX",
        ):
            self.assertIn(directive, self.quarantine)

    def test_service_invokes_only_initial_without_a_wrapper(self) -> None:
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
        self.assertEqual(
            directives(self.service, "ExecStartPre"),
            [
                *prerequisite_checks,
                "ExecStartPre=!/usr/bin/env -i /usr/bin/python3 -I "
                "/usr/local/libexec/brerc/consume-initial-approval.py "
                "--expected-artifact-id REPLACE_WITH_APPROVED_ARTIFACT_ID",
            ],
        )
        self.assertEqual(
            directives(self.service, "ExecStart"),
            [
                "ExecStart=/opt/brerc-dashboard/releases/REPLACE_WITH_APPROVED_ARTIFACT_ID/"
                "bin/brerc-load initial "
                "--config /etc/brerc/refresh/loader.configuration.yaml"
            ],
        )
        exec_lines = [line for line in self.service.splitlines() if line.startswith("Exec")]
        for forbidden in (" refresh", " incremental", "--force", "nightly_job", "/bin/sh", "|"):
            self.assertNotIn(forbidden, "\n".join(exec_lines))
        self.assertEqual(directives(self.service, "Type"), ["Type=oneshot"])
        self.assertEqual(directives(self.service, "RemainAfterExit"), ["RemainAfterExit=yes"])

    def test_distinct_manual_approval_is_required_but_not_overclaimed(self) -> None:
        plain_runbook = self.runbook.replace("*", "").lower()
        normalised_runbook = " ".join(self.runbook.split())
        self.assertEqual(directives(self.service, "ConditionPathExists"), [])
        self.assertIn("missing or invalid marker fails the unit", plain_runbook)
        self.assertNotIn("APPROVED_TO_SCHEDULE", self.service)
        self.assertNotIn("ConditionPathIsExecutable=", self.service)
        self.assertNotIn("AssertFile", self.service)
        self.assertIn("consume-initial-approval.py", self.service)
        self.assertNotIn("/deploy/initial/consume_initial_approval.py", self.service)
        self.assertNotIn("/opt/brerc-dashboard/current", self.service)
        self.assertIn("REPLACE_WITH_APPROVED_ARTIFACT_ID", self.service)
        self.assertIn("single-use", plain_runbook)
        self.assertIn("time-limited", plain_runbook)
        self.assertIn("consum", plain_runbook)
        self.assertIn("--expected-artifact-id REPLACE_WITH_APPROVED_ARTIFACT_ID", self.service)
        self.assertNotIn("not an automatically consumed token", plain_runbook)
        self.assertNotIn("remove it immediately after every start attempt", plain_runbook)
        self.assertIn("A retry requires investigation, a new approval", normalised_runbook)
        self.assertIn("refuses `initial` once an active release exists", normalised_runbook)
        self.assertEqual(
            directives(self.service, "ReadWritePaths"),
            ["ReadWritePaths=/etc/brerc/initial-approval"],
        )

    def test_external_inputs_and_unprivileged_runtime_match_refresh(self) -> None:
        for key in (
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
        self.assertEqual(
            directives(self.service, "ExecStartPre")[:-1],
            directives(self.refresh, "ExecStartPre"),
        )
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
            "systemd-analyze security",
            "--threshold=40 --no-pager",
            "DropInPaths=` to be empty",
            'systemctl cat "$unit"',
            'systemctl show "$unit" --property=FragmentPath --property=DropInPaths',
            "/etc/systemd/system/brerc-loader-initial-quarantine.service",
            "/usr/local/libexec/brerc/consume-initial-approval.py",
            "root-owned and not writable by any non-root identity",
            "approved standalone-helper digest",
            "empty environment",
            "root:root` mode `0400",
            '"schemaVersion":1',
            "no longer than four hours",
            "If approval is withdrawn before start",
            "withdrawal arrives after `ExecStartPre` consumed the marker",
            "operator-initiated stop",
            "do not claim verified zero-job evidence",
            "marker stays absent through loader success",
            "OnFailure` quarantine removes that exact path",
            "Never source the",
            "browser mocks disabled",
            '`mode:"initial"`',
            "database/API identity as authoritative",
            "failed_attempt_evidence_query.sql",
            "verify_failed_attempt_evidence.py",
            'previous_invocation_id="$( systemctl show "$unit"',
            'systemctl start --no-block "$unit"',
            "--property=Job --value",
            'database_window_start="$( psql',
            'database_window_end="$( psql',
            "within 60 seconds",
            "one dedicated root Bash shell",
            "set -euo pipefail",
            "set -C",
            "does not already exist",
            "umask 077",
            'mkdir -m 0700 -- "$evidence"',
            'chown root:root -- "$evidence"',
            '"$evidence/database-window.json"',
            "--database-window-json",
            "--unit-properties",
            "--journal-json",
            "--expected-environment-id",
            "--expected-database",
            "--expected-role",
            "--expected-window-start",
            "--expected-window-end",
            'YYYY-MM-DD\\"T\\"HH24:MI:SS.US\\"Z\\"',
            "multiple jobs",
            "a prerequisite or execution failure",
            "systemd `Assert*` failures do not activate `OnFailure`",
            "inactive cleanup debt",
            "immutable/single-use evidence system",
            "`active (exited)`",
            "--timestamp=unix",
            "InactiveExitTimestamp",
            "StateChangeTimestamp",
            "systemctl stop brerc-loader-initial.service",
            "only the separately approved full-snapshot `refresh` path",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, normalised_runbook)

    def test_runbook_checks_the_exact_root_helper_python_version(self) -> None:
        normalised_runbook = " ".join(self.runbook.split())
        self.assertIn("exact system interpreter used by `ExecStartPre`", normalised_runbook)
        self.assertIn("requires Python 3.10 or newer", normalised_runbook)
        self.assertIn("test -x /usr/bin/python3", normalised_runbook)
        self.assertIn("sys.version_info < (3, 10)", normalised_runbook)

    def test_failure_query_is_time_bounded_and_privacy_safe(self) -> None:
        for required in (
            "serve.etl_job_status",
            "serve.etl_release_status",
            ":'window_start'::timestamp with time zone",
            ":'window_end'::timestamp with time zone",
            ":'load_mode'::text",
            "'jobCount'",
            "'failureCode'",
            "'cleanupPending'",
            "\\gset",
            "IN ('initial', 'refresh')",
            "interval '4 hours'",
            "serve.etl_monitor_identity",
            "current_database()::text = :'expected_database'::text",
            "current_setting('transaction_read_only') = 'on'",
            "ARRAY['brerc_monitor']::text[]",
            "'environmentId'",
            "'effectiveRoles'",
            "'directRoles'",
        ):
            self.assertIn(required, self.failed_evidence_query)
        for forbidden in (
            "loader_control.",
            "publication.",
            "source_disposition",
            "source_key_token",
            "easting",
            "northing",
            "grid_ref",
            "comments",
        ):
            self.assertNotIn(forbidden, self.failed_evidence_query.lower())

    def test_success_query_binds_the_approved_monitor_target_and_session(self) -> None:
        for required in (
            "serve.etl_release_evidence",
            "serve.etl_monitor_identity",
            "current_database()::text = :'expected_database'::text",
            "current_user::text = :'expected_role'::text",
            "session_user::text = :'expected_role'::text",
            "current_setting('transaction_read_only') = 'on'",
            "ARRAY['brerc_monitor']::text[]",
            ":'expected_environment_id'::uuid",
            "'startedAt'",
            "'finishedAt'",
            "\\gset",
        ):
            self.assertIn(required, self.release_evidence_query)


if __name__ == "__main__":
    unittest.main()
