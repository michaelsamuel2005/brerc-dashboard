"""Unit tests for app/db.py's connection URL resolution."""

import os
from unittest.mock import patch

import pytest

from app.db import _build_database_url

YAML_API_READONLY = {
    "dbhostname": "yaml-host",
    "port": 5555,
    "dbname": "yaml_db",
    "user": "yaml_user",
    "password": "yaml_pass",
}


def test_build_database_url_prefers_yaml_when_set():
    # safety.yaml is the normal way to configure this; DATABASE_URL is only
    # an override, so yaml must win when both are present.
    with patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://ro_user:pw@api-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("app.db._get_api_readonly", return_value=YAML_API_READONLY):
            result = _build_database_url()

    assert result == "postgresql://yaml_user:yaml_pass@yaml-host:5555/yaml_db"


def test_build_database_url_falls_back_to_env_var_when_yaml_unset():
    with patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://ro_user:pw@api-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("app.db._get_api_readonly", return_value={}):
            result = _build_database_url()

    assert result == "postgresql://ro_user:pw@api-host:5432/brerc_ui"


def test_build_database_url_raises_when_unconfigured():
    # Fails closed: no yaml credentials and no env var must raise, not
    # silently connect as postgres/postgres.
    with patch.dict(os.environ, {}, clear=True):
        with patch("app.db._get_api_readonly", return_value={}):
            with pytest.raises(RuntimeError, match="No database credentials"):
                _build_database_url()


def test_build_database_url_ignores_etl_write_credentials():
    # The bug this pins: api_readonly must be a distinct block from
    # 'destination' (the ETL's write-capable credentials). If app/db.py ever
    # falls back to reading 'destination', the "read-only" API silently
    # starts connecting with write credentials on any host where yaml wins.
    with patch.dict(os.environ, {}, clear=True):
        with patch("app.db.get_config") as mock_config:
            mock_config.return_value = {
                "destination": {
                    "dbhostname": "etl-host",
                    "dbname": "brerc_ui",
                    "user": "etl_write",
                    "password": "etl_write_pw",
                },
                "api_readonly": {
                    "dbhostname": "etl-host",
                    "dbname": "brerc_ui",
                    "user": "brerc_api_ro",
                    "password": "ro_pw",
                },
            }
            result = _build_database_url()

    assert result == "postgresql://brerc_api_ro:ro_pw@etl-host:5432/brerc_ui"
