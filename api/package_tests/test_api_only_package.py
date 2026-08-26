"""Build-time regressions for the public API's isolated package boundary."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
PINNED_API_REQUIREMENTS = (
    "fastapi==0.141.1",
    "uvicorn[standard]==0.46.0",
    "psycopg[binary]==3.3.4",
    "python-dotenv==1.0.1",
    "pydantic==2.12.4",
    "httpx==0.28.1",
)


def _api_requirements_from_project() -> tuple[str, ...]:
    """Read the API extra without adding a TOML dependency on Python 3.10."""

    pyproject = (API_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    optional_dependencies = pyproject.partition("[project.optional-dependencies]")[2]
    optional_dependencies = optional_dependencies.partition("\n[")[0]
    match = re.search(r"(?ms)^api\s*=\s*(\[.*?^\])", optional_dependencies)
    assert match is not None
    requirements = ast.literal_eval(match.group(1))
    assert isinstance(requirements, list)
    assert all(isinstance(requirement, str) for requirement in requirements)
    return tuple(requirements)


def _build_app_only_runtime_archive(tmp_path: Path) -> tuple[Path, set[str]]:
    """Reproduce the source boundary used by the public API container.

    The Docker image copies ``app/`` directly; it does not install the combined
    repository wheel. Keeping this regression test on the same boundary also
    makes it independent of a runner's ambient PEP 517 backend installation.
    """

    source_files = tuple(sorted((API_ROOT / "app").rglob("*.py")))
    expected_names = {source.relative_to(API_ROOT).as_posix() for source in source_files}
    archive_path = tmp_path / "brerc-api-runtime.zip"
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in source_files:
            archive.write(source, source.relative_to(API_ROOT).as_posix())
    return archive_path, expected_names


def test_isolated_runtime_contains_the_complete_app_and_no_write_modules(tmp_path: Path) -> None:
    runtime_archive, expected_names = _build_app_only_runtime_archive(tmp_path)
    with zipfile.ZipFile(runtime_archive) as archive:
        names = set(archive.namelist())

    assert names == expected_names
    assert "app/__init__.py" in names
    assert "app/main.py" in names
    assert "app/routers/species.py" in names
    for forbidden in ("etl/", "brerc_loader/", "brerc_source/"):
        assert not any(name.startswith(forbidden) for name in names)

    assert _api_requirements_from_project() == PINNED_API_REQUIREMENTS

    probe = """
import importlib.abc
import sys

class BlockWritePackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition('.')[0]
        if root in {'etl', 'brerc_loader', 'brerc_source'}:
            raise ModuleNotFoundError('write package blocked', name=root)
        return None

sys.meta_path.insert(0, BlockWritePackages())
import app.main
assert not {'etl', 'brerc_loader', 'brerc_source'}.intersection(sys.modules)
"""
    environment = {
        **os.environ,
        "APP_ENV": "prod",
        "PYTHONPATH": str(runtime_archive),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_docker_context_and_runtime_are_api_only_and_unprivileged() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (API_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY app ./app" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "APP_ENV=prod" in dockerfile
    assert 'd["project"]["optional-dependencies"]["api"]' not in dockerfile
    assert "d['project']['optional-dependencies']['api']" in dockerfile
    for forbidden in (
        "COPY etl",
        "COPY brerc_loader",
        "COPY brerc_source",
        "COPY db",
        "COPY requirements.txt",
        'pip install --no-cache-dir ".[',
    ):
        assert forbidden not in dockerfile

    rules = tuple(
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert rules[0] == "*"
    assert set(rules[1:]) == {
        "!pyproject.toml",
        "!app/",
        "!app/**/",
        "!app/*.py",
        "!app/**/*.py",
    }
