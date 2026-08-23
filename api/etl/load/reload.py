"""
Admin and ops database operations for B6 schema rebuilds.

Why this is separate from api/app/db.py:
That module serves the public API using a read-only user (brerc_api_ro).
rebuilding or dropping schemas requires admin privileges (DDL rights) and
has no business being near API request handlers where a bug could wipe data.
This module uses a separate admin connection via DATABASE_URL_ADMIN or safety.yaml.
"""

import os
from functools import lru_cache
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import etl.db as db
from etl.load.loader import load_safety_config


class DatabaseMismatchError(RuntimeError):
    """
    Raised when the admin connection (used for destructive schema resets)
    would target a different database than the one normal ETL writes go to.

    The two are deliberately configured independently, via separate
    credentials, so that a bug in the everyday write path can't reach
    DDL privileges (see the module docstring). But "independently
    configured" also means they can silently drift apart — e.g. DATABASE_URL
    gets pointed at a new host during deployment and DATABASE_URL_ADMIN
    doesn't. Refusing here means that drift fails loudly instead of quietly
    wiping whatever the admin URL happens to resolve to.
    """


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Lazily loads and caches safety configuration once per process."""
    return load_safety_config()


def _get_admin() -> dict:
    """Extracts the admin configuration block."""
    return get_config().get("admin", {})


B6_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "db" / "b6_schema.sql"


def _build_admin_database_url() -> str:
    """
    Builds the admin connection string, preferring config/safety.yaml's
    'admin' block — the normal way to configure this, with explicit
    host/database/user/password fields. DATABASE_URL_ADMIN is the fallback
    for deployments that do not mount the YAML file.

    Fails closed: if neither supplies real credentials, raises instead of
    silently connecting as postgres/postgres — this is the credential used
    for destructive full schema resets, so it matters more here than
    anywhere else in the ETL.
    """
    admin = _get_admin()

    user = admin.get("user")
    password = admin.get("password")

    if bool(user) != bool(password):
        raise RuntimeError(
            "The admin block is incomplete. Set both user and password, or "
            "leave both empty to use DATABASE_URL_ADMIN."
        )

    if user and password:
        host = admin.get("dbhostname")
        dbname = admin.get("dbname")

        if not all((user, password, host, dbname)):
            raise RuntimeError(
                "The admin block is incomplete. Set dbhostname, dbname, user "
                "and password, or leave user/password empty to use "
                "DATABASE_URL_ADMIN."
            )

        return make_conninfo(
            user=user,
            password=password,
            host=host,
            port=admin.get("port") or 5432,
            dbname=dbname,
        )

    explicit_url = os.getenv("DATABASE_URL_ADMIN")

    if explicit_url:
        return explicit_url

    raise RuntimeError(
        "No admin database credentials configured. Set admin.user/"
        "admin.password in config/safety.yaml, or use DATABASE_URL_ADMIN as "
        "the fallback — there is no default credential."
    )


def _database_target(connection_string: str) -> tuple:
    """
    Extracts a fail-closed routing identity from a direct connection string.

    Deliberately excludes user/password: the admin and destination
    connections are SUPPOSED to use different credentials (that's the
    whole point of the privilege separation) — only host/port/dbname
    need to agree.
    """
    parsed = None
    try:
        parsed = conninfo_to_dict(connection_string)
    except (psycopg.Error, TypeError, ValueError):
        pass

    if parsed is None:
        raise DatabaseMismatchError(
            "Refusing to run a full schema reset: a database connection "
            "string is invalid."
        )

    if parsed.get("service"):
        raise DatabaseMismatchError(
            "Refusing to run a full schema reset: service-based connection "
            "settings cannot be compared safely. Use an explicit single-host "
            "connection string for both admin and destination roles."
        )

    host = parsed.get("host") or ""
    hostaddr = parsed.get("hostaddr") or ""
    port = parsed.get("port")
    dbname = parsed.get("dbname")

    if not dbname or not port or (not host and not hostaddr):
        raise DatabaseMismatchError(
            "Refusing to run a full schema reset: both connections must name "
            "an explicit database, port and single host."
        )

    if any("," in value for value in (host, hostaddr, port)):
        raise DatabaseMismatchError(
            "Refusing to run a full schema reset: multi-host connection "
            "settings cannot be compared safely."
        )

    try:
        numeric_port = int(port)
    except (TypeError, ValueError):
        raise DatabaseMismatchError(
            "Refusing to run a full schema reset: the database port is invalid."
        ) from None

    return (host, hostaddr, numeric_port, dbname)


def _assert_admin_matches_destination(admin_url: str) -> None:
    """Raises DatabaseMismatchError if admin_url targets a different
    database than the one normal ETL writes go to."""
    admin_target = _database_target(admin_url)
    destination_target = _database_target(db.get_destination_database_url())

    if admin_target != destination_target:
        raise DatabaseMismatchError(
            "Refusing to run a full schema reset: the admin connection targets "
            "a different database endpoint than normal ETL writes. Set "
            "DATABASE_URL_ADMIN (or config/safety.yaml's 'admin' block) to "
            "match the destination host, hostaddr, port and database."
        )


def get_admin_connection() -> psycopg.Connection:
    """Opens a database connection with DDL privileges for schema changes.

    Refuses to connect if the admin URL targets a different database than
    the one normal ETL writes go to — see _assert_admin_matches_destination.
    """
    admin_url = _build_admin_database_url()
    _assert_admin_matches_destination(admin_url)
    return psycopg.connect(admin_url, options="-c search_path=public")


def force_full_reload(
    connection=None,
    schema_path: Path = B6_SCHEMA_PATH,
):
    """
    Drops and recreates the entire B6 database schema by running the b6_schema.sql file.
    Used for full resets when tables are missing, empty, or incremental checks fail.
    """
    # Track whether we opened our own connection so we know to close it later
    owns_connection = connection is None

    if owns_connection:
        connection = get_admin_connection()

    try:
        # Read the SQL schema setup file
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        # Execute the entire script to reset tables, views, and constraints
        with connection.cursor() as cur:
            cur.execute(schema_sql)

        connection.commit()

    finally:
        # Clean up the connection if we opened it locally
        if owns_connection:
            connection.close()
