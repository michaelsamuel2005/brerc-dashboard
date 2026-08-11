import os
from pathlib import Path
import pytest
from unittest.mock import MagicMock, mock_open, patch

from etl.load.reload import (
    _build_admin_database_url,
    get_admin_connection,
    force_full_reload,
)


# --- _build_admin_database_url tests ---

def test_build_admin_database_url_uses_env_var():
    # Confirms the function prioritizes the DATABASE_URL_ADMIN environment variable.
    # Expects the exact connection string from the environment to be returned, else fails.
    with patch.dict(
        os.environ,
        {
            "DATABASE_URL_ADMIN": (
                "postgresql://test_admin:pass@db:5432/test_db"
            )
        },
    ):
        result = _build_admin_database_url()

    assert result == "postgresql://test_admin:pass@db:5432/test_db"


def test_build_admin_database_url_uses_fallback_config():
    # Confirms the function falls back to the admin configuration when
    # DATABASE_URL_ADMIN is not set.
    # Expects the connection string to be built correctly from the config, else fails.
    with patch.dict(os.environ, {}, clear=True):
        with patch(
            "etl.load.reload.get_config",
            return_value={
                "admin": {
                    "dbhostname": "test_host",
                    "port": 5432,
                    "dbname": "test_db",
                    "user": "test_user",
                    "password": "test_password",
                }
            },
        ):
            result = _build_admin_database_url()

    assert result == "postgresql://test_user:test_password@test_host:5432/test_db"


# --- get_admin_connection tests ---

def test_get_admin_connection_opens_valid_connection():
    # Confirms the function opens a psycopg connection using the correct DDL-capable URL.
    # Expects psycopg.connect to be called exactly once with the built admin URL, else fails.
    with (
        patch("etl.load.reload.psycopg.connect") as mock_connect,
        patch(
            "etl.load.reload._build_admin_database_url",
            return_value="postgresql://mock_url",
        ),
    ):
        get_admin_connection()

        mock_connect.assert_called_once_with("postgresql://mock_url")


# --- force_full_reload tests ---

def test_force_full_reload_uses_existing_connection():
    # Confirms the function executes schema SQL using a provided database connection without closing it.
    # Expects cursor.execute to run the file contents and commit, but NOT close the connection, else fails.
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
    mock_sql_content = "CREATE TABLE test_table (id INT);"
    dummy_path = Path("dummy_path.sql")

    with patch("builtins.open", mock_open(read_data=mock_sql_content)):
        force_full_reload(
            connection=mock_connection,
            schema_path=dummy_path,
        )

    mock_cursor.execute.assert_called_once_with(mock_sql_content)
    mock_connection.commit.assert_called_once()
    mock_connection.close.assert_not_called()


def test_force_full_reload_creates_and_closes_connection():
    # Confirms the function opens and safely closes a new connection when none is provided.
    # Expects get_admin_connection to be called, used, and explicitly closed in the finally block, else fails.
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
    mock_sql_content = "DROP TABLE IF EXISTS test_table;"
    dummy_path = Path("dummy_path.sql")

    with (
        patch("builtins.open", mock_open(read_data=mock_sql_content)),
        patch(
            "etl.load.reload.get_admin_connection",
            return_value=mock_connection,
        ),
    ):
        force_full_reload(schema_path=dummy_path)

    mock_cursor.execute.assert_called_once_with(mock_sql_content)
    mock_connection.commit.assert_called_once()
    mock_connection.close.assert_called_once()
