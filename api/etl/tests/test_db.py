"""Unit tests for etl/db.py's connection URL resolution."""

import os
from unittest.mock import patch

import pytest

from etl.db import _build_destination_database_url, _build_source_database_url

YAML_DESTINATION = {
    "dbhostname": "yaml-host",
    "port": 5555,
    "dbname": "yaml_db",
    "user": "yaml_user",
    "password": "yaml_pass",
}

YAML_CONNECTION = {
    "dbhostname": "yaml-source-host",
    "port": 5556,
    "dbname": "yaml_source_db",
    "user": "yaml_source_user",
    "password": "yaml_source_pass",
}


# --- _build_destination_database_url tests ---
# Every test here explicitly patches etl.db.CONFIG rather than relying on
# whatever real config/safety.yaml happens to be on the machine running the
# suite — otherwise these silently pick up (and can leak into test output)
# real credentials from a developer's own machine.


def test_build_destination_database_url_prefers_yaml_when_set():
    # safety.yaml is the normal way to configure this; the env var is only
    # an override, so yaml must win when both are present.
    with patch.dict(
        os.environ,
        {"DESTINATION_DATABASE_URL": "postgresql://etl:pw@dest-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("etl.db.CONFIG", {"destination": YAML_DESTINATION}):
            result = _build_destination_database_url()

    assert result == "postgresql://yaml_user:yaml_pass@yaml-host:5555/yaml_db"


def test_build_destination_database_url_falls_back_to_env_var_when_yaml_unset():
    with patch.dict(
        os.environ,
        {"DESTINATION_DATABASE_URL": "postgresql://etl:pw@dest-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("etl.db.CONFIG", {"destination": {}}):
            result = _build_destination_database_url()

    assert result == "postgresql://etl:pw@dest-host:5432/brerc_ui"


def test_build_destination_database_url_ignores_generic_database_url():
    # Confirms the ETL never silently reuses the public API's DATABASE_URL
    # (app/db.py) for its own writes, even when DESTINATION_DATABASE_URL isn't
    # set — see etl/db.py's docstring for why sharing that variable between
    # the two would be dangerous: it either breaks ETL writes against a
    # read-only role, or tempts someone into widening DATABASE_URL's
    # permissions and unknowingly handing the public API write access too.
    with patch.dict(
        os.environ,
        {"DATABASE_URL": "postgresql://api_readonly:pw@api-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("etl.db.CONFIG", {"destination": YAML_DESTINATION}):
            result = _build_destination_database_url()

    assert "api-host" not in result
    assert result == "postgresql://yaml_user:yaml_pass@yaml-host:5555/yaml_db"


def test_build_destination_database_url_raises_when_unconfigured():
    # Fails closed: no yaml credentials and no env var must raise, not
    # silently connect as postgres/postgres.
    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.db.CONFIG", {"destination": {}}):
            with pytest.raises(RuntimeError, match="No destination database credentials"):
                _build_destination_database_url()


# --- _build_source_database_url tests ---


def test_build_source_database_url_prefers_yaml_when_set():
    with patch.dict(
        os.environ,
        {"SOURCE_DATABASE_URL": "postgresql://src:pw@source-host:5432/brerc_source"},
        clear=True,
    ):
        with patch("etl.db._CONNECTION", YAML_CONNECTION):
            result = _build_source_database_url()

    assert result == "postgresql://yaml_source_user:yaml_source_pass@yaml-source-host:5556/yaml_source_db"


def test_build_source_database_url_falls_back_to_env_var_when_yaml_unset():
    with patch.dict(
        os.environ,
        {"SOURCE_DATABASE_URL": "postgresql://src:pw@source-host:5432/brerc_source"},
        clear=True,
    ):
        with patch("etl.db._CONNECTION", {}):
            result = _build_source_database_url()

    assert result == "postgresql://src:pw@source-host:5432/brerc_source"


def test_build_source_database_url_raises_when_unconfigured():
    # Fails closed: a CSV-mode setup never calls this at all (see
    # get_source_connection()'s docstring), so this only matters for
    # database-mode setups, which must not silently fall back to
    # postgres/postgres either.
    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.db._CONNECTION", {}):
            with pytest.raises(RuntimeError, match="No source database credentials"):
                _build_source_database_url()
