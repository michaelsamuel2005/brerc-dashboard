"""Unit tests for etl/db.py's connection URL resolution."""

import os
from unittest.mock import patch

from etl.db import _build_destination_database_url

YAML_DESTINATION = {
    "dbhostname": "yaml-host",
    "port": 5555,
    "dbname": "yaml_db",
    "user": "yaml_user",
    "password": "yaml_pass",
}


def test_build_destination_database_url_uses_env_var():
    with patch.dict(
        os.environ,
        {"DESTINATION_DATABASE_URL": "postgresql://etl:pw@dest-host:5432/brerc_ui"},
        clear=True,
    ):
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


def test_build_destination_database_url_falls_back_to_yaml_when_unset():
    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.db.CONFIG", {"destination": YAML_DESTINATION}):
            result = _build_destination_database_url()

    assert result == "postgresql://yaml_user:yaml_pass@yaml-host:5555/yaml_db"
