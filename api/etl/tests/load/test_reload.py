import os
from pathlib import Path
import pytest
from psycopg.conninfo import conninfo_to_dict
from unittest.mock import MagicMock, mock_open, patch

from etl.load.reload import (
    DatabaseMismatchError,
    _assert_admin_matches_destination,
    _build_admin_database_url,
    get_admin_connection,
    force_full_reload,
)


# --- _build_admin_database_url tests ---
# Every test here explicitly patches etl.load.reload.get_config rather than
# relying on whatever real config/safety.yaml happens to be on the machine
# running the suite — otherwise these silently pick up (and can leak into
# test output) real credentials from a developer's own machine.

YAML_ADMIN = {
    "dbhostname": "test_host",
    "port": 5432,
    "dbname": "test_db",
    "user": "test_user",
    "password": "test_password",
}


def test_build_admin_database_url_prefers_yaml_when_set():
    # safety.yaml is the normal host configuration, so it wins when both are present.
    with patch.dict(
        os.environ,
        {"DATABASE_URL_ADMIN": "postgresql://test_admin:pass@db:5432/test_db"},
        clear=True,
    ):
        with patch("etl.load.reload.get_config", return_value={"admin": YAML_ADMIN}):
            result = _build_admin_database_url()

    assert conninfo_to_dict(result) == {
        "user": "test_user",
        "password": "test_password",
        "host": "test_host",
        "port": "5432",
        "dbname": "test_db",
    }


def test_build_admin_database_url_falls_back_to_env_var_when_yaml_unset():
    # Confirms the function falls back to the DATABASE_URL_ADMIN environment
    # variable when safety.yaml's admin block has no credentials.
    with patch.dict(
        os.environ,
        {"DATABASE_URL_ADMIN": "postgresql://test_admin:pass@db:5432/test_db"},
        clear=True,
    ):
        with patch("etl.load.reload.get_config", return_value={"admin": {}}):
            result = _build_admin_database_url()

    assert result == "postgresql://test_admin:pass@db:5432/test_db"


def test_build_admin_database_url_raises_when_unconfigured():
    # Fails closed: this is the credential for destructive full schema
    # resets, so a genuinely unconfigured environment must raise rather
    # than silently connecting as postgres/postgres.
    with patch.dict(os.environ, {}, clear=True):
        with patch("etl.load.reload.get_config", return_value={"admin": {}}):
            with pytest.raises(RuntimeError, match="No admin database credentials"):
                _build_admin_database_url()


@pytest.mark.parametrize(
    "admin",
    [
        {"user": "admin", "password": "secret", "dbname": "brerc_ui"},
    ],
)
def test_build_admin_database_url_rejects_partial_yaml_credentials(admin):
    with patch.dict(
        os.environ,
        {"DATABASE_URL_ADMIN": "postgresql://env_admin:pw@env-host/brerc_ui"},
        clear=True,
    ):
        with patch("etl.load.reload.get_config", return_value={"admin": admin}):
            with pytest.raises(RuntimeError, match="admin block is incomplete"):
                _build_admin_database_url()


@pytest.mark.parametrize("admin", [{"user": "admin"}, {"password": "secret"}])
def test_build_admin_database_url_rejects_one_sided_yaml_credentials(admin):
    with patch.dict(
        os.environ,
        {"DATABASE_URL_ADMIN": "postgresql://env_admin:pw@env-host/brerc_ui"},
        clear=True,
    ):
        with patch("etl.load.reload.get_config", return_value={"admin": admin}):
            with pytest.raises(RuntimeError, match="admin block is incomplete"):
                _build_admin_database_url()


def test_build_admin_database_url_quotes_reserved_characters():
    credentials = {
        **YAML_ADMIN,
        "user": "admin@example",
        "password": "p@ss/word#100%'",
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch(
            "etl.load.reload.get_config",
            return_value={"admin": credentials},
        ):
            result = conninfo_to_dict(_build_admin_database_url())

    assert result["user"] == credentials["user"]
    assert result["password"] == credentials["password"]


# --- _assert_admin_matches_destination tests ---


def test_assert_admin_matches_destination_allows_matching_target():
    # host/port/dbname agree, so no exception should be raised even though
    # the credentials (user/password) differ — that's expected, not a mismatch.
    with patch(
        "etl.db.get_destination_database_url",
        return_value="postgresql://api_user:secret@db.example.com:5432/brerc_ui",
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
        "etl.db.get_destination_database_url",
        return_value="postgresql://api_user:secret@db.example.com:5432/brerc_ui",
    ):
        with pytest.raises(DatabaseMismatchError):
            _assert_admin_matches_destination(admin_url)


@pytest.mark.parametrize(
    ("admin_url", "destination_url"),
    [
        (
            "host=db.example.com hostaddr=192.0.2.10 port=5432 dbname=brerc_ui user=admin",
            "host=db.example.com hostaddr=192.0.2.20 port=5432 dbname=brerc_ui user=writer",
        ),
        (
            "hostaddr=192.0.2.10 port=5432 dbname=brerc_ui user=admin",
            "hostaddr=192.0.2.20 port=5432 dbname=brerc_ui user=writer",
        ),
    ],
)
def test_assert_admin_matches_destination_rejects_hostaddr_bypass(
    admin_url, destination_url
):
    with patch(
        "etl.db.get_destination_database_url",
        return_value=destination_url,
    ):
        with pytest.raises(DatabaseMismatchError):
            _assert_admin_matches_destination(admin_url)


@pytest.mark.parametrize(
    "connection_url",
    [
        "service=admin_db user=admin",
        "host=db-a,db-b port=5432,5432 dbname=brerc_ui user=admin",
        "host=db.example.com user=admin",
        "host=db.example.com dbname=brerc_ui user=admin",
        "not-a-valid-connection-string",
    ],
)
def test_assert_admin_matches_destination_rejects_ambiguous_targets(connection_url):
    with patch(
        "etl.db.get_destination_database_url",
        return_value="postgresql://writer:pw@db.example.com:5432/brerc_ui",
    ):
        with pytest.raises(DatabaseMismatchError):
            _assert_admin_matches_destination(connection_url)


def test_assert_admin_matches_destination_rejects_ambient_port_bypass():
    with (
        patch.dict(os.environ, {"PGPORT": "6543"}, clear=False),
        patch(
            "etl.db.get_destination_database_url",
            return_value="host=db.example.com dbname=brerc_ui user=writer",
        ),
    ):
        with pytest.raises(DatabaseMismatchError):
            _assert_admin_matches_destination(
                "host=db.example.com port=5432 dbname=brerc_ui user=admin"
            )


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

        mock_connect.assert_called_once_with(
            "postgresql://mock_url", options="-c search_path=public"
        )


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
            "etl.db.get_destination_database_url",
            return_value="postgresql://api:pw@right-host:5432/brerc_ui",
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
