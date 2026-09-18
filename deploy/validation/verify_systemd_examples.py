#!/usr/bin/env python3
"""Fail-closed static checks for BRERC's example systemd units.

This validator has two deliberately separate layers:

* repository contract checks inspect the unmodified examples and enforce the
  reviewed identities, commands, immutable paths, loopback listeners,
  scheduling relationship and hardening directives; and
* ``--systemd-analyze`` renders non-installable copies in a temporary directory
  and asks the Linux systemd parser to verify their syntax and dependencies.

The rendered copies are never installed or started.  Passing this script proves
the repository-side unit contract on the CI Linux version; it does not replace
the target-host validation and controlled rehearsal in LINUX_ACCEPTANCE.md.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ARTIFACT_TOKEN = "REPLACE_WITH_APPROVED_ARTIFACT_ID"


@dataclass(frozen=True)
class UnitSpec:
    source: str
    installed_name: str
    kind: str


UNIT_SPECS = (
    UnitSpec(
        "deploy/production/brerc-public-api.service.example",
        "brerc-public-api.service",
        "public-api",
    ),
    UnitSpec(
        "deploy/production/brerc-run-dashboard.service.example",
        "brerc-run-dashboard.service",
        "run-dashboard",
    ),
    UnitSpec(
        "deploy/initial/brerc-loader-initial.service.example",
        "brerc-loader-initial.service",
        "initial",
    ),
    UnitSpec(
        "deploy/refresh/brerc-loader-refresh.service.example",
        "brerc-loader-refresh.service",
        "refresh",
    ),
    UnitSpec(
        "deploy/refresh/brerc-loader-refresh-quarantine.service.example",
        "brerc-loader-refresh-quarantine.service",
        "quarantine",
    ),
    UnitSpec(
        "deploy/refresh/brerc-loader-refresh.timer.example",
        "brerc-loader-refresh.timer",
        "timer",
    ),
)

DEPLOYMENT_MODE_TEMPLATES = (
    ("deploy/production/public-api.env.example", "APP_ENV"),
    ("deploy/production/run-dashboard.env.example", "DASHBOARD_ENV"),
)


COMMON_HARDENING = {
    "NoNewPrivileges": "true",
    "PrivateTmp": "true",
    "PrivateDevices": "true",
    "ProtectSystem": "strict",
    "ProtectHome": "true",
    "ProtectKernelTunables": "true",
    "ProtectKernelModules": "true",
    "ProtectKernelLogs": "true",
    "ProtectControlGroups": "true",
    "ProtectClock": "true",
    "ProtectHostname": "true",
    "ProtectProc": "invisible",
    "ProcSubset": "pid",
    "RestrictNamespaces": "true",
    "RestrictRealtime": "true",
    "RestrictSUIDSGID": "true",
    "LockPersonality": "true",
    "MemoryDenyWriteExecute": "true",
    "CapabilityBoundingSet": "",
    "AmbientCapabilities": "",
    "SystemCallArchitectures": "native",
    "RemoveIPC": "true",
    "LimitCORE": "0",
}


class UnitFile:
    """Small systemd parser that preserves repeated directives."""

    def __init__(self, text: str, source: str) -> None:
        self.text = text
        self.source = source
        self.sections: dict[str, dict[str, list[str]]] = {}
        self.problems: list[str] = []
        current_section: str | None = None

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                if not current_section:
                    self.problems.append(f"line {line_number}: empty section name")
                    continue
                self.sections.setdefault(current_section, {})
                continue
            if current_section is None:
                self.problems.append(
                    f"line {line_number}: directive appears before any section"
                )
                continue
            if "=" not in line:
                self.problems.append(f"line {line_number}: malformed directive")
                continue
            key, value = line.split("=", 1)
            if not key or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key):
                self.problems.append(
                    f"line {line_number}: invalid directive name {key!r}"
                )
                continue
            self.sections[current_section].setdefault(key, []).append(value)

    def values(self, section: str, key: str) -> list[str]:
        return self.sections.get(section, {}).get(key, [])

    def one(self, section: str, key: str) -> str | None:
        values = self.values(section, key)
        if len(values) == 1:
            return values[0]
        return None


def _expect_one(
    unit: UnitFile,
    problems: list[str],
    section: str,
    key: str,
    expected: str,
) -> None:
    values = unit.values(section, key)
    if values != [expected]:
        problems.append(
            f"[{section}] {key}= must be exactly {expected!r}; observed {values!r}"
        )


def _expect_absent(unit: UnitFile, problems: list[str], section: str, key: str) -> None:
    values = unit.values(section, key)
    if values:
        problems.append(f"[{section}] {key}= must be absent; observed {values!r}")


def _expect_values(
    unit: UnitFile,
    problems: list[str],
    section: str,
    key: str,
    expected: Iterable[str],
) -> None:
    expected_list = list(expected)
    values = unit.values(section, key)
    if values != expected_list:
        problems.append(
            f"[{section}] {key}= values must be {expected_list!r}; observed {values!r}"
        )


def _validate_service_common(unit: UnitFile, spec: UnitSpec) -> list[str]:
    problems = list(unit.problems)
    if set(unit.sections) - {"Unit", "Service", "Install"}:
        problems.append(
            "unexpected section(s): "
            + ", ".join(sorted(set(unit.sections) - {"Unit", "Service", "Install"}))
        )
    if "Unit" not in unit.sections or "Service" not in unit.sections:
        problems.append("service must contain [Unit] and [Service]")

    if "EXAMPLE ONLY." not in "\n".join(unit.text.splitlines()[:5]):
        problems.append("the first five lines must identify the unit as EXAMPLE ONLY")

    for key, expected in COMMON_HARDENING.items():
        _expect_one(unit, problems, "Service", key, expected)

    _expect_one(unit, problems, "Service", "UMask", "0077")
    _expect_one(unit, problems, "Service", "StandardOutput", "journal")
    _expect_one(unit, problems, "Service", "StandardError", "journal")

    expected_families = (
        "AF_UNIX" if spec.kind == "quarantine" else "AF_UNIX AF_INET AF_INET6"
    )
    _expect_one(
        unit,
        problems,
        "Service",
        "RestrictAddressFamilies",
        expected_families,
    )

    if "/current" in unit.text or "/releases/current" in unit.text:
        problems.append("mutable current paths are forbidden")
    if re.search(r"\b(?:docker-compose|Caddyfile|nightly_job|b6_schema)\b", unit.text):
        problems.append("legacy/demo deployment mechanisms are forbidden")

    for key in ("ExecStart", "ExecStartPre", "ExecStartPost"):
        for command in unit.values("Service", key):
            unprefixed = command.lstrip("-+!@:")
            if not unprefixed.startswith("/"):
                problems.append(f"[{key}] executable must use an absolute path")
            if re.search(r"(?:^|/)(?:ba|z|k|c)?sh(?:\s|$)|\s-c(?:\s|$)", command):
                problems.append(f"[{key}] must not invoke a shell")
            if any(token in command for token in (";", "&&", "||", "`", "$(")):
                problems.append(f"[{key}] contains shell control syntax")

    for value in unit.values("Service", "Environment"):
        name = value.split("=", 1)[0]
        if re.search(r"(?:PASSWORD|SECRET|TOKEN|DATABASE_URL)$", name):
            problems.append(f"credential-like value {name}= must not be inline")

    return problems


def _validate_public_api(unit: UnitFile, problems: list[str]) -> None:
    _expect_one(unit, problems, "Service", "Type", "simple")
    _expect_one(unit, problems, "Service", "User", "brerc-api")
    _expect_one(unit, problems, "Service", "Group", "brerc-api")
    _expect_one(unit, problems, "Service", "Restart", "on-failure")
    if unit.values("Service", "Environment").count("APP_ENV=prod") != 1:
        problems.append("public API must fix APP_ENV=prod in the unit")
    _expect_one(
        unit,
        problems,
        "Service",
        "UnsetEnvironment",
        "PGPASSWORD DATABASE_URL",
    )
    _expect_one(
        unit,
        problems,
        "Service",
        "EnvironmentFile",
        "/etc/brerc/production/api/public-api.env",
    )
    required_inputs = {
        "/etc/brerc/production/api/public-api.env",
        "/etc/brerc/production/api/pg_service.conf",
        "/etc/brerc/production/api/api.pgpass",
        "/etc/brerc/production/api/postgres-ca.pem",
    }
    asserted_inputs = set(unit.values("Unit", "AssertFileNotEmpty"))
    if not required_inputs.issubset(asserted_inputs):
        problems.append("public API must assert every service-mode input")
    _expect_absent(unit, problems, "Service", "ReadWritePaths")
    _expect_one(unit, problems, "Install", "WantedBy", "multi-user.target")
    command = unit.one("Service", "ExecStart") or ""
    required = (
        f"/opt/brerc-dashboard/releases/{ARTIFACT_TOKEN}/api-runtime/venv/bin/uvicorn ",
        "app.main:app",
        "--host 127.0.0.1",
        "--port 8000",
        "--proxy-headers",
        "--forwarded-allow-ips 127.0.0.1",
        "--no-access-log",
        "--no-server-header",
    )
    for fragment in required:
        if fragment not in command:
            problems.append(f"public API ExecStart must contain {fragment!r}")
    if any(fragment in command for fragment in ("0.0.0.0", "--reload", "[::]")):
        problems.append("public API must be loopback-only and must not use reload mode")
    if "/api-runtime" not in (unit.one("Service", "WorkingDirectory") or ""):
        problems.append("public API must run from the API-only runtime artifact")


def _validate_run_dashboard(unit: UnitFile, problems: list[str]) -> None:
    _expect_one(unit, problems, "Service", "Type", "simple")
    _expect_one(unit, problems, "Service", "User", "brerc-monitor-ui")
    _expect_one(unit, problems, "Service", "Group", "brerc-monitor-ui")
    _expect_one(unit, problems, "Service", "Restart", "on-failure")
    if unit.values("Service", "Environment").count("DASHBOARD_ENV=prod") != 1:
        problems.append("run dashboard must fix DASHBOARD_ENV=prod in the unit")
    _expect_one(
        unit,
        problems,
        "Service",
        "UnsetEnvironment",
        "PGPASSWORD RUN_DASHBOARD_DATABASE_URL",
    )
    _expect_values(
        unit,
        problems,
        "Service",
        "EnvironmentFile",
        (
            "/etc/brerc/production/monitor/run-dashboard.env",
            "/etc/brerc/production/monitor/run-dashboard.secrets.env",
        ),
    )
    _expect_absent(unit, problems, "Service", "ReadWritePaths")
    _expect_one(unit, problems, "Install", "WantedBy", "multi-user.target")
    command = unit.one("Service", "ExecStart") or ""
    required = (
        f"/opt/brerc-dashboard/releases/{ARTIFACT_TOKEN}/run-dashboard-runtime/venv/bin/uvicorn ",
        "app:app",
        "--host 127.0.0.1",
        "--port 8100",
        "--proxy-headers",
        "--forwarded-allow-ips 127.0.0.1",
        "--no-access-log",
        "--no-server-header",
    )
    for fragment in required:
        if fragment not in command:
            problems.append(f"run-dashboard ExecStart must contain {fragment!r}")
    if any(fragment in command for fragment in ("0.0.0.0", "--reload", "[::]")):
        problems.append(
            "run dashboard must be loopback-only and must not use reload mode"
        )


def _validate_initial(unit: UnitFile, problems: list[str]) -> None:
    _expect_one(unit, problems, "Service", "Type", "oneshot")
    _expect_one(unit, problems, "Service", "User", "brerc-loader")
    _expect_one(unit, problems, "Service", "Group", "brerc-loader")
    _expect_one(unit, problems, "Service", "Restart", "no")
    _expect_one(unit, problems, "Service", "UnsetEnvironment", "PGPASSWORD")
    _expect_one(
        unit,
        problems,
        "Service",
        "EnvironmentFile",
        "/etc/brerc/refresh/loader-runtime.env",
    )
    _expect_one(
        unit,
        problems,
        "Service",
        "ExecStartPre",
        "+/usr/bin/python3 "
        f"/opt/brerc-dashboard/releases/{ARTIFACT_TOKEN}/deploy/initial/"
        "consume_initial_approval.py",
    )
    _expect_one(
        unit,
        problems,
        "Service",
        "ExecStart",
        f"/opt/brerc-dashboard/releases/{ARTIFACT_TOKEN}/bin/brerc-load initial "
        "--config /etc/brerc/refresh/loader.configuration.yaml",
    )
    _expect_one(
        unit,
        problems,
        "Service",
        "ReadWritePaths",
        "/etc/brerc/initial-approval",
    )
    _expect_absent(unit, problems, "Unit", "ConditionPathExists")
    if "Install" in unit.sections:
        problems.append(
            "the one-time initial-load unit must not be installable/enabled"
        )


def _validate_refresh(unit: UnitFile, problems: list[str]) -> None:
    _expect_one(
        unit, problems, "Unit", "OnFailure", "brerc-loader-refresh-quarantine.service"
    )
    _expect_one(
        unit,
        problems,
        "Unit",
        "ConditionPathExists",
        "/etc/brerc/refresh/APPROVED_TO_SCHEDULE",
    )
    _expect_one(unit, problems, "Service", "Type", "oneshot")
    _expect_one(unit, problems, "Service", "User", "brerc-loader")
    _expect_one(unit, problems, "Service", "Group", "brerc-loader")
    _expect_one(unit, problems, "Service", "Restart", "no")
    _expect_one(unit, problems, "Service", "UnsetEnvironment", "PGPASSWORD")
    _expect_one(
        unit,
        problems,
        "Service",
        "EnvironmentFile",
        "/etc/brerc/refresh/loader-runtime.env",
    )
    _expect_one(
        unit,
        problems,
        "Service",
        "ExecStart",
        f"/opt/brerc-dashboard/releases/{ARTIFACT_TOKEN}/bin/brerc-load refresh "
        "--config /etc/brerc/refresh/loader.configuration.yaml",
    )
    _expect_absent(unit, problems, "Service", "ReadWritePaths")


def _validate_quarantine(unit: UnitFile, problems: list[str]) -> None:
    _expect_one(unit, problems, "Service", "Type", "oneshot")
    _expect_one(unit, problems, "Service", "User", "root")
    _expect_one(unit, problems, "Service", "Group", "root")
    _expect_one(unit, problems, "Service", "Restart", "no")
    _expect_one(unit, problems, "Service", "PrivateNetwork", "true")
    _expect_one(
        unit,
        problems,
        "Service",
        "ExecStart",
        "/usr/bin/rm -f -- /etc/brerc/refresh/APPROVED_TO_SCHEDULE",
    )
    _expect_one(
        unit,
        problems,
        "Service",
        "ReadWritePaths",
        "/etc/brerc/refresh",
    )
    _expect_absent(unit, problems, "Service", "EnvironmentFile")


def _validate_timer(unit: UnitFile) -> list[str]:
    problems = list(unit.problems)
    if set(unit.sections) != {"Unit", "Timer", "Install"}:
        problems.append("timer must contain only [Unit], [Timer] and [Install]")
    if "EXAMPLE ONLY." not in "\n".join(unit.text.splitlines()[:5]):
        problems.append("the first five lines must identify the timer as EXAMPLE ONLY")
    _expect_one(unit, problems, "Timer", "OnCalendar", "*-*-* 02:30:00 UTC")
    _expect_one(unit, problems, "Timer", "Persistent", "true")
    _expect_one(unit, problems, "Timer", "AccuracySec", "1min")
    _expect_one(unit, problems, "Timer", "RandomizedDelaySec", "0")
    _expect_one(
        unit,
        problems,
        "Timer",
        "Unit",
        "brerc-loader-refresh.service",
    )
    _expect_one(unit, problems, "Install", "WantedBy", "timers.target")
    if "/current" in unit.text or "nightly_job" in unit.text:
        problems.append("timer must not refer to mutable or legacy execution paths")
    return problems


def validate_unit_text(spec: UnitSpec, text: str) -> list[str]:
    unit = UnitFile(text, spec.source)
    if spec.kind == "timer":
        return _validate_timer(unit)

    problems = _validate_service_common(unit, spec)
    validators = {
        "public-api": _validate_public_api,
        "run-dashboard": _validate_run_dashboard,
        "initial": _validate_initial,
        "refresh": _validate_refresh,
        "quarantine": _validate_quarantine,
    }
    validators[spec.kind](unit, problems)

    if spec.kind != "quarantine" and ARTIFACT_TOKEN not in unit.text:
        problems.append("immutable artifact placeholder is required")
    return problems


def validate_repository(repo_root: Path) -> list[str]:
    problems: list[str] = []
    installed_names: set[str] = set()
    for spec in UNIT_SPECS:
        if spec.installed_name in installed_names:
            problems.append(f"duplicate installed unit name: {spec.installed_name}")
        installed_names.add(spec.installed_name)

        path = repo_root / spec.source
        if not path.is_file():
            problems.append(f"{spec.source}: required example is missing")
            continue
        for problem in validate_unit_text(spec, path.read_text(encoding="utf-8")):
            problems.append(f"{spec.source}: {problem}")

    for source, fixed_name in DEPLOYMENT_MODE_TEMPLATES:
        path = repo_root / source
        if not path.is_file():
            problems.append(f"{source}: required example is missing")
            continue
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw_line.strip()
            if (
                line
                and not line.startswith("#")
                and line.split("=", 1)[0] == fixed_name
            ):
                problems.append(
                    f"{source}:{line_number}: {fixed_name} must be fixed only in the unit; "
                    "EnvironmentFile values can override Environment="
                )
    return problems


def _render_for_systemd(repo_root: Path, output_dir: Path) -> list[Path]:
    """Render parser-only copies without weakening validation of originals."""

    rendered: list[Path] = []
    for spec in UNIT_SPECS:
        source = (repo_root / spec.source).read_text(encoding="utf-8")
        text = source.replace(ARTIFACT_TOKEN, "ci-systemd-static-validation")
        lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("ExecStartPre="):
                prefix = "+" if line.startswith("ExecStartPre=+") else ""
                line = f"ExecStartPre={prefix}/usr/bin/true"
            elif line.startswith("ExecStart="):
                line = "ExecStart=/usr/bin/true"
            elif line.startswith("User="):
                line = "User=root"
            elif line.startswith("Group="):
                line = "Group=root"
            elif line.startswith("WorkingDirectory="):
                line = "WorkingDirectory=/tmp"
            lines.append(line)
        destination = output_dir / spec.installed_name
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rendered.append(destination)
    return rendered


def run_systemd_analyze(repo_root: Path) -> None:
    executable = shutil.which("systemd-analyze")
    if not executable:
        raise RuntimeError("systemd-analyze is required for --systemd-analyze")
    if sys.platform != "linux":
        raise RuntimeError("--systemd-analyze must run on Linux")

    version = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    print(f"Linux parser: {version}")

    with tempfile.TemporaryDirectory(prefix="brerc-systemd-verify-") as temp:
        rendered = _render_for_systemd(repo_root, Path(temp))
        environment = os.environ.copy()
        environment.update(
            {
                "SYSTEMD_COLORS": "0",
                "SYSTEMD_URLIFY": "0",
                "SYSTEMD_PAGER": "cat",
            }
        )
        subprocess.run(
            [executable, "--man=no", "verify", *(str(path) for path in rendered)],
            check=True,
            env=environment,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to the root containing this script)",
    )
    parser.add_argument(
        "--systemd-analyze",
        action="store_true",
        help="also parse rendered copies with the host's systemd-analyze",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()
    problems = validate_repository(repo_root)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        print(
            f"systemd example validation failed with {len(problems)} problem(s)",
            file=sys.stderr,
        )
        return 1

    if args.systemd_analyze:
        try:
            run_systemd_analyze(repo_root)
        except (RuntimeError, subprocess.CalledProcessError) as error:
            print(
                f"ERROR: Linux systemd parser validation failed: {error}",
                file=sys.stderr,
            )
            return 1

    suffix = " and Linux systemd parser" if args.systemd_analyze else ""
    print(f"OK: 6 BRERC systemd examples passed the repository contract{suffix}.")
    print(
        "NOTE: target-host acceptance still requires deploy/validation/LINUX_ACCEPTANCE.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
