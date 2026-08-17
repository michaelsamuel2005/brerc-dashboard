"""Unit tests for app/db.py's connection URL resolution."""

import os
from unittest.mock import patch

import pytest

from app.db import _build_database_url


def test_build_database_url_uses_env_var():
    with patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://ro_user:pw@api-host:5432/brerc_ui"},
        clear=True,
    ):
        result = _build_database_url()

    assert result == "postgresql://ro_user:pw@api-host:5432/brerc_ui"


def test_build_database_url_falls_back_to_yaml_when_unset():
    with patch.dict(os.environ, {}, clear=True):
        with patch(
            "app.db._get_destination",
            return_value={
                "dbhostname": "yaml-host",
                "port": 5555,
                "dbname": "yaml_db",
                "user": "yaml_user",
                "password": "yaml_pass",
            },
        ):
            result = _build_database_url()

    assert result == "postgresql://yaml_user:yaml_pass@yaml-host:5555/yaml_db"


def test_build_database_url_raises_when_unconfigured():
    # Fails closed: no env var and no safety.yaml credentials must raise,
    # not silently connect as postgres/postgres.
    with patch.dict(os.environ, {}, clear=True):
        with patch("app.db._get_destination", return_value={}):
            with pytest.raises(RuntimeError, match="No database credentials"):
                _build_database_url()
