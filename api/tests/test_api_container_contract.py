"""Regression for the app-only FastAPI container package boundary."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


APP_DIR = Path(__file__).resolve().parents[1] / "app"


def test_app_database_config_works_without_etl_package(tmp_path):
    """The Docker image copies app/ but intentionally excludes the write-capable ETL."""
    shutil.copytree(APP_DIR, tmp_path / "app")
    probe = tmp_path / "probe.py"
    probe.write_text(
        """
import importlib.abc
import sys

class BlockEtl(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "etl" or fullname.startswith("etl."):
            raise ModuleNotFoundError("blocked container-only dependency", name="etl")
        return None

sys.meta_path.insert(0, BlockEtl())
from app.db import _build_database_url
assert _build_database_url() == "postgresql://reader:pw@db:5432/brerc_ui"
""",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "DATABASE_URL": "postgresql://reader:pw@db:5432/brerc_ui",
    }
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
