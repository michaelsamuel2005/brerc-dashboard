"""Unit tests for etl/db.py's connection URL resolution."""

import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from psycopg.conninfo import conninfo_to_dict

from etl.db import (
    _build_destination_database_url,
    _build_source_database_url,
    get_destination_connection,
    get_source_connection,
)

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


def test_etl_package_does_not_import_the_public_api_database_connection():
    """Keep ETL reads/writes isolated from the public API's read-only login."""
    etl_root = Path(__file__).resolve().parents[1]
    offenders = []

    for source_path in sorted(etl_root.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            imports_app_db = (isinstance(node, ast.ImportFrom) and node.module == "app.db") or (
                isinstance(node, ast.Import) and any(alias.name == "app.db" for alias in node.names)
            )
            if imports_app_db:
                offenders.append(f"{source_path.relative_to(etl_root)}:{node.lineno}")

    assert offenders == [], (
        "ETL code/tests must use etl.db destination connections, not the public "
        f"API's read-only app.db connection: {offenders}"
    )


# --- _build_destination_database_url tests ---
# Every test here explicitly patches etl.db.CONFIG rather than relying on
# whatever real config/safety.yaml happens to be on the machine running the
# suite — otherwise these silently pick up (and can leak into test output)
# real credentials from a developer's own machine.


def test_build_destination_database_url_prefers_yaml_when_set():
    # safety.yaml is the normal host configuration, so it wins when both are present.
    with patch.dict(
        os.environ,
        {"DESTINATION_DATABASE_URL": "postgresql://etl:pw@dest-host:5432/brerc_ui"},
        clear=True,
    ):
        with patch("etl.db.CONFIG", {"destination": YAML_DESTINATION}):
            result = _build_destination_database_url()

    assert conninfo_to_dict(result) == {
        "user": "yaml_user",
        "password": "yaml_pass",
        "host": "yaml-host",
        "port": "5555",
        "dbname": "yaml_db",
    }


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
    assert conninfo_to_dict(result)["user"] == "yaml_user"
    assert conninfo_to_dict(result)["host"] == "yaml-host"


def test_build_destination_database_url_raises_when_unconfigured():
    # Fails closed: no yaml credentials and no env var must raise, not
    # silently connect as postgres/postgres.
    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.db.CONFIG", {"destination": {}}):
            with pytest.raises(RuntimeError, match="No destination database credentials"):
                _build_destination_database_url()


@pytest.mark.parametrize(
    "destination",
    [
        {"user": "writer", "password": "secret", "dbname": "brerc_ui"},
    ],
)
def test_build_destination_database_url_rejects_partial_yaml_credentials(destination):
    with patch.dict(
        os.environ,
        {"DESTINATION_DATABASE_URL": "postgresql://env_writer:pw@env-host/brerc_ui"},
        clear=True,
    ):
        with patch("etl.db.CONFIG", {"destination": destination}):
            with pytest.raises(RuntimeError, match="destination block is incomplete"):
                _build_destination_database_url()


@pytest.mark.parametrize("destination", [{"user": "writer"}, {"password": "secret"}])
def test_build_destination_database_url_rejects_one_sided_yaml_credentials(
    destination,
):
    with patch.dict(
        os.environ,
        {"DESTINATION_DATABASE_URL": "postgresql://env_writer:pw@env-host/brerc_ui"},
        clear=True,
    ):
        with patch("etl.db.CONFIG", {"destination": destination}):
            with pytest.raises(RuntimeError, match="destination block is incomplete"):
                _build_destination_database_url()


def test_build_destination_database_url_quotes_reserved_characters():
    credentials = {
        **YAML_DESTINATION,
        "user": "writer@example",
        "password": "p@ss/word#100%'",
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.db.CONFIG", {"destination": credentials}):
            result = conninfo_to_dict(_build_destination_database_url())

    assert result["user"] == credentials["user"]
    assert result["password"] == credentials["password"]


def test_get_destination_connection_resolves_credentials_lazily():
    with (
        patch(
            "etl.db.get_destination_database_url",
            return_value="postgresql://writer:pw@destination/brerc_ui",
        ) as build_url,
        patch("etl.db.psycopg.connect") as connect,
    ):
        get_destination_connection()

    build_url.assert_called_once_with()
    connect.assert_called_once()
    assert connect.call_args.args == ("postgresql://writer:pw@destination/brerc_ui",)


# --- _build_source_database_url tests ---


def test_build_source_database_url_prefers_yaml_when_set():
    with patch.dict(
        os.environ,
        {"SOURCE_DATABASE_URL": "postgresql://src:pw@source-host:5432/brerc_source"},
        clear=True,
    ):
        with patch("etl.db._CONNECTION", YAML_CONNECTION):
            result = _build_source_database_url()

    assert conninfo_to_dict(result) == {
        "user": "yaml_source_user",
        "password": "yaml_source_pass",
        "host": "yaml-source-host",
        "port": "5556",
        "dbname": "yaml_source_db",
    }


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


@pytest.mark.parametrize(
    "source",
    [
        {"user": "reader", "password": "secret", "dbname": "brerc_source"},
    ],
)
def test_build_source_database_url_rejects_partial_yaml_credentials(source):
    with patch.dict(
        os.environ,
        {"SOURCE_DATABASE_URL": "postgresql://env_reader:pw@env-host/brerc_source"},
        clear=True,
    ):
        with patch("etl.db._CONNECTION", source):
            with pytest.raises(RuntimeError, match="source connection block is incomplete"):
                _build_source_database_url()


@pytest.mark.parametrize("source", [{"user": "reader"}, {"password": "secret"}])
def test_build_source_database_url_rejects_one_sided_yaml_credentials(source):
    with patch.dict(
        os.environ,
        {"SOURCE_DATABASE_URL": "postgresql://env_reader:pw@env-host/brerc_source"},
        clear=True,
    ):
        with patch("etl.db._CONNECTION", source):
            with pytest.raises(RuntimeError, match="source connection block is incomplete"):
                _build_source_database_url()


def test_build_source_database_url_quotes_reserved_characters():
    credentials = {
        **YAML_CONNECTION,
        "user": "reader@example",
        "password": "p@ss/word#100%'",
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.db._CONNECTION", credentials):
            result = conninfo_to_dict(_build_source_database_url())

    assert result["user"] == credentials["user"]
    assert result["password"] == credentials["password"]


def test_get_source_connection_resolves_credentials_lazily():
    with (
        patch(
            "etl.db._build_source_database_url",
            return_value="postgresql://reader:pw@source/brerc_source",
        ) as build_url,
        patch("etl.db.psycopg.connect") as connect,
    ):
        get_source_connection()

    build_url.assert_called_once_with()
    connect.assert_called_once_with("postgresql://reader:pw@source/brerc_source")
