#!/usr/bin/env python3
"""Render inert templates with synthetic paths and verify them on Linux."""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# systemd-analyze accepts an integer percentage even though it renders exposure
# on a 0.0-10.0 scale. Current reviewed templates score 3.2 or better on the
# Ubuntu 24.04 baseline; 40 (rendered as 4.0) is the regression boundary.
MAXIMUM_EXPOSURE_LEVEL = "40"


class SystemdTemplateInvalid(RuntimeError):
    """A template cannot be rendered or systemd rejected it."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    return parser


def _render(
    text: str,
    *,
    artifact: Path,
    refresh: Path,
    initial: Path,
    approval_helper: Path,
) -> str:
    identity = pwd.getpwuid(os.getuid())
    group = grp.getgrgid(identity.pw_gid)
    release_path = "/opt/brerc-dashboard/releases/REPLACE_WITH_APPROVED_ARTIFACT_ID"
    replacements = {
        release_path: str(artifact),
        "REPLACE_WITH_APPROVED_ARTIFACT_ID": "ci-systemd-verify",
        "/etc/brerc/refresh": str(refresh),
        "/etc/brerc/initial-approval": str(initial),
        "/usr/local/libexec/brerc/consume-initial-approval.py": str(approval_helper),
        "User=brerc-loader": f"User={identity.pw_name}",
        "Group=brerc-loader": f"Group={group.gr_name}",
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    if "REPLACE_WITH_" in text:
        raise SystemdTemplateInvalid
    return text


def _run(command: list[str]) -> str:
    # Every argv element is assembled above from fixed systemd commands and
    # paths inside this helper's private TemporaryDirectory.
    completed = subprocess.run(  # noqa: S603
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout)
        raise SystemdTemplateInvalid
    return completed.stdout


def verify(repo_root: Path) -> None:
    if not sys.platform.startswith("linux") or shutil.which("systemd-analyze") is None:
        raise SystemdTemplateInvalid
    templates = (
        repo_root / "deploy/initial/brerc-loader-initial.service.example",
        repo_root / "deploy/initial/brerc-loader-initial-quarantine.service.example",
        repo_root / "deploy/refresh/brerc-loader-refresh.service.example",
        repo_root / "deploy/refresh/brerc-loader-refresh-approval-guard.service.example",
        repo_root / "deploy/refresh/brerc-loader-refresh-quarantine.service.example",
        repo_root / "deploy/refresh/brerc-loader-refresh.timer.example",
    )
    if not all(path.is_file() for path in templates):
        raise SystemdTemplateInvalid

    with tempfile.TemporaryDirectory(prefix="brerc-systemd-verify-") as temporary:
        root = Path(temporary)
        artifact = root / "artifact"
        refresh = root / "refresh"
        initial = root / "initial-approval"
        approval_helper = root / "root-helper/consume-initial-approval.py"
        units = root / "units"
        (artifact / "bin").mkdir(parents=True)
        approval_helper.parent.mkdir(parents=True)
        refresh.mkdir()
        initial.mkdir()
        units.mkdir()

        loader = artifact / "bin/brerc-load"
        loader.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        loader.chmod(0o755)
        shutil.copyfile(
            repo_root / "deploy/initial/consume_initial_approval.py",
            approval_helper,
        )
        for name in (
            "loader.configuration.yaml",
            "source.configuration.yaml",
            "publication-policy.approved.json",
            "species-dictionary.approved.csv",
            "loader-runtime.env",
            "pg_service.conf",
            "source.pgpass",
            "target.pgpass",
            "source-ca.pem",
            "target-ca.pem",
        ):
            placeholder = refresh / name
            placeholder.write_text("synthetic-systemd-verification\n", encoding="utf-8")

        rendered: list[Path] = []
        for template in templates:
            destination = units / template.name.removesuffix(".example")
            destination.write_text(
                _render(
                    template.read_text(encoding="utf-8"),
                    artifact=artifact,
                    refresh=refresh,
                    initial=initial,
                    approval_helper=approval_helper,
                ),
                encoding="utf-8",
            )
            rendered.append(destination)

        _run(["systemd-analyze", "verify", *(str(path) for path in rendered)])
        for service in (path for path in rendered if path.suffix == ".service"):
            report = _run(
                [
                    "systemd-analyze",
                    "security",
                    "--offline=yes",
                    "--no-pager",
                    f"--threshold={MAXIMUM_EXPOSURE_LEVEL}",
                    str(service),
                ]
            )
            sys.stdout.write(f"=== systemd security: {service.name} ===\n{report}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify(args.repo_root.resolve())
    except (OSError, SystemdTemplateInvalid):
        sys.stderr.write('{"code":"SYSTEMD_TEMPLATE_INVALID","status":"failed"}\n')
        return 2
    sys.stdout.write(json.dumps({"status": "verified", "templates": 6}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
