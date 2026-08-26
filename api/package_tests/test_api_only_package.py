"""Build-time regressions for the public API's isolated package boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from email.parser import BytesParser
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


def _build_app_only_wheel(tmp_path: Path) -> Path:
    context = tmp_path / "context"
    context.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(API_ROOT / name, context / name)
    shutil.copytree(API_ROOT / "app", context / "app")

    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    environment = {
        **os.environ,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        cwd=context,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    wheels = tuple(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_isolated_context_packages_the_complete_app_and_no_write_modules(tmp_path: Path) -> None:
    wheel = _build_app_only_wheel(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))

    assert "app/__init__.py" in names
    assert "app/main.py" in names
    assert "app/routers/species.py" in names
    for forbidden in ("etl/", "brerc_loader/", "brerc_source/"):
        assert not any(name.startswith(forbidden) for name in names)

    requirements = tuple(metadata.get_all("Requires-Dist", []))
    for pin in PINNED_API_REQUIREMENTS:
        assert any(requirement.startswith(f"{pin};") for requirement in requirements)

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
        "PYTHONPATH": str(wheel),
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
