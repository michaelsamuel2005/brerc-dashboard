"""Unit tests for app/db.py's connection URL resolution."""

import os
from unittest.mock import patch

import pytest
from psycopg.conninfo import conninfo_to_dict

from app.db import _build_database_url

YAML_API_READONLY = {
    "dbhostname": "yaml-host",
    "port": 5555,
    "dbname": "yaml_db",
    "user": "yaml_user",
    "password": "yaml_pass",
}


def test_build_database_url_prefers_yaml_when_set():
    # safety.yaml is the normal host configuration, so it wins when both are present.
    with patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://ro_user:pw@api-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("app.db._get_api_readonly", return_value=YAML_API_READONLY):
            result = _build_database_url()

    assert conninfo_to_dict(result) == {
        "user": "yaml_user",
        "password": "yaml_pass",
        "host": "yaml-host",
        "port": "5555",
        "dbname": "yaml_db",
    }


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


@pytest.mark.parametrize(
    "api_readonly",
    [
        {"user": "reader", "password": "secret", "dbname": "brerc_ui"},
    ],
)
def test_build_database_url_rejects_partial_yaml_credentials(api_readonly):
    with patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://env_reader:pw@env-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("app.db._get_api_readonly", return_value=api_readonly):
            with pytest.raises(RuntimeError, match="api_readonly block is incomplete"):
                _build_database_url()


@pytest.mark.parametrize("api_readonly", [{"user": "reader"}, {"password": "secret"}])
def test_build_database_url_rejects_one_sided_yaml_credentials(
    api_readonly,
):
    with patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://env_reader:pw@env-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("app.db._get_api_readonly", return_value=api_readonly):
            with pytest.raises(RuntimeError, match="api_readonly block is incomplete"):
                _build_database_url()


def test_build_database_url_quotes_reserved_characters():
    credentials = {
        **YAML_API_READONLY,
        "user": "reader@example",
        "password": "p@ss/word#100%'",
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch("app.db._get_api_readonly", return_value=credentials):
            result = conninfo_to_dict(_build_database_url())

    assert result["user"] == credentials["user"]
    assert result["password"] == credentials["password"]


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

    assert conninfo_to_dict(result) == {
        "user": "brerc_api_ro",
        "password": "ro_pw",
        "host": "etl-host",
        "port": "5432",
        "dbname": "brerc_ui",
    }


def test_build_database_url_rejects_destination_only_configuration():
    with patch.dict(os.environ, {}, clear=True):
        with patch(
            "app.db.get_config",
            return_value={
                "destination": {
                    "dbhostname": "etl-host",
                    "dbname": "brerc_ui",
                    "user": "etl_write",
                    "password": "etl_write_pw",
                }
            },
        ):
            with pytest.raises(RuntimeError, match="No database credentials"):
                _build_database_url()
