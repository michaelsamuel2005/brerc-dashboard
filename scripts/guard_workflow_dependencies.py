#!/usr/bin/env python3
"""Fail cheaply when a tracked workflow refers to a subsystem that is absent.

GitHub accepts a manually dispatched workflow even when every repository path
used by its shell steps is missing.  This explicit manifest keeps those local
dependencies reviewable and makes that otherwise silent failure visible on
every ordinary CI run, before a service or dependency is provisioned.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


WORKFLOW_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    ".github/workflows/ci.yml": (
        "api/connector_tests",
        "api/etl/tests",
        "api/pyproject.toml",
        "api/requirements-dev.txt",
        "api/scripts/guard_stdlib_only.py",
        "api/scripts/smoke_installed_package.py",
        "db/b0_staging_setup.sql",
        "db/b6_sample_data.sql",
        "db/b6_schema.sql",
        "db/b7_tiles.sql",
        "scripts/guard_no_data_files.py",
        "scripts/test_guard_no_data_files.py",
        "web/package-lock.json",
        "web/package.json",
        "web/playwright.config.ts",
    ),
    ".github/workflows/loader-scale-acceptance.yml": (
        "api/loader_tests",
        "api/loader_tests/postgres16_scale_source_fixture.sql",
        "api/loader_tests/setup_postgis16_destination.sh",
        "api/loader_tests/setup_postgres16_e2e_source.sh",
        "api/pyproject.toml",
        "api/scripts/run_loader_scale_acceptance.py",
        "db/migrations",
        "db/migrations/0001_publication_store.sql",
        "db/roles.sql",
        "docs/POSTGRES_LOADER_SCALE_ACCEPTANCE.md",
    ),
}


def check(repo_root: Path) -> list[str]:
    """Return stable, content-free descriptions of missing registrations/paths."""
    root = repo_root.resolve()
    workflows_dir = root / ".github" / "workflows"
    tracked_workflows = {
        path.relative_to(root).as_posix()
        for pattern in ("*.yml", "*.yaml")
        for path in workflows_dir.glob(pattern)
        if path.is_file()
    }
    problems = [
        f"unregistered workflow: {path}"
        for path in sorted(tracked_workflows - WORKFLOW_DEPENDENCIES.keys())
    ]
    problems.extend(
        f"registered workflow missing: {path}"
        for path in sorted(WORKFLOW_DEPENDENCIES.keys() - tracked_workflows)
    )
    for workflow, dependencies in sorted(WORKFLOW_DEPENDENCIES.items()):
        for dependency in dependencies:
            target = root / dependency
            if not target.exists():
                problems.append(f"{workflow}: missing dependency: {dependency}")
            elif target.is_dir() and not any(target.iterdir()):
                problems.append(f"{workflow}: empty dependency directory: {dependency}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    problems = check(args.repo_root)
    if problems:
        for problem in problems:
            print(f"WORKFLOW_DEPENDENCY_INVALID: {problem}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(WORKFLOW_DEPENDENCIES)} workflow dependency manifests are complete."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
