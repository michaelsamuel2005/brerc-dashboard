import os
from pathlib import Path
import pytest
from unittest.mock import MagicMock, mock_open, patch

from etl.load.reload import (
    DatabaseMismatchError,
    _assert_admin_matches_destination,
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
        {"DATABASE_URL_ADMIN": ("postgresql://test_admin:pass@db:5432/test_db")},
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


def test_build_admin_database_url_raises_when_unconfigured():
    # Fails closed: this is the credential for destructive full schema
    # resets, so a genuinely unconfigured environment must raise rather
    # than silently connecting as postgres/postgres.
    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.load.reload.get_config", return_value={"admin": {}}):
            with pytest.raises(RuntimeError, match="No admin database credentials"):
                _build_admin_database_url()


# --- _assert_admin_matches_destination tests ---


def test_assert_admin_matches_destination_allows_matching_target():
    # host/port/dbname agree, so no exception should be raised even though
    # the credentials (user/password) differ — that's expected, not a mismatch.
    with patch(
        "etl.db.DESTINATION_DATABASE_URL",
        "postgresql://api_user:secret@db.example.com:5432/brerc_ui",
    ):
        _assert_admin_matches_destination(
            "postgresql://admin_user:other_secret@db.example.com:5432/brerc_ui"
        )


@pytest.mark.parametrize(
    "admin_url",
    [
        "postgresql://admin:pw@different-host:5432/brerc_ui",  # different host
        "postgresql://admin:pw@db.example.com:5433/brerc_ui",  # different port
        "postgresql://admin:pw@db.example.com:5432/some_other_db",  # different dbname
    ],
)
def test_assert_admin_matches_destination_rejects_mismatched_target(admin_url):
    with patch(
        "etl.db.DESTINATION_DATABASE_URL",
        "postgresql://api_user:secret@db.example.com:5432/brerc_ui",
    ):
        with pytest.raises(DatabaseMismatchError):
            _assert_admin_matches_destination(admin_url)


# --- get_admin_connection tests ---


def test_get_admin_connection_opens_valid_connection():
    # Confirms the function opens a psycopg connection using the correct DDL-capable URL,
    # once the admin/destination match check has passed.
    # Expects psycopg.connect to be called exactly once with the built admin URL, else fails.
    with (
        patch("etl.load.reload.psycopg.connect") as mock_connect,
        patch(
            "etl.load.reload._build_admin_database_url",
            return_value="postgresql://mock_url",
        ),
        patch("etl.load.reload._assert_admin_matches_destination"),
    ):
        get_admin_connection()

        mock_connect.assert_called_once_with("postgresql://mock_url")


def test_get_admin_connection_refuses_mismatched_target():
    # Confirms get_admin_connection never opens a connection at all if the
    # admin URL doesn't match the destination database.
    with (
        patch("etl.load.reload.psycopg.connect") as mock_connect,
        patch(
            "etl.load.reload._build_admin_database_url",
            return_value="postgresql://admin:pw@wrong-host:5432/brerc_ui",
        ),
        patch(
            "etl.db.DESTINATION_DATABASE_URL",
            "postgresql://api:pw@right-host:5432/brerc_ui",
        ),
    ):
        with pytest.raises(DatabaseMismatchError):
            get_admin_connection()

        mock_connect.assert_not_called()


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
