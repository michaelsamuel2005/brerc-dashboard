"""
Read-only database connection management and security validation module for the API layer.
Enforces strict read-only access, parameterised queries, statement timeouts,
and validation against approved public B6 views (public_*).
"""

import os
from functools import lru_cache
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

# Load api/.env (if present) so credentials can live in a git-ignored file
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Loads host-only YAML config when the ETL package is available.

    The production API image intentionally contains only ``app/``. Its
    DATABASE_URL fallback must therefore remain usable without packaging the
    write-capable ETL alongside the public service.
    """
    try:
        from etl.load.loader import load_safety_config
    except ModuleNotFoundError as error:
        if error.name != "etl":
            raise
        return {}

    try:
        return load_safety_config()
    except FileNotFoundError:
        return {}


def _get_api_readonly() -> dict:
    """
    Retrieves the API's own read-only connection block (api_readonly), kept
    separate from safety.yaml's 'destination' block. 'destination' holds the
    ETL's write-capable credentials — sharing it here would mean that on any
    host where safety.yaml wins (the intended behaviour), this "read-only"
    API silently starts connecting with write credentials instead. The
    read-only-ness of this connection is enforced entirely by the database
    role's own grants (see db/docker/99_set_ro_password.sh), so which
    credentials land here matters.
    """
    return get_config().get("api_readonly", {})


# Statement timeout guard: caps query execution at 10 seconds to prevent runaway queries
STATEMENT_TIMEOUT_MS = 10_000  # 10s

# Strict whitelist: API requests are restricted exclusively to approved public views.
B6_PUBLIC_RELATIONS = {
    "public_species",
    "public_records",
    "public_cells",
    "public_provenance",
}


def _build_database_url() -> str:
    """
    Assembles the database connection string, preferring config/safety.yaml's
    api_readonly block — the normal way to configure this, with explicit
    host/database/user/password fields. DATABASE_URL is the fallback for
    deployments (such as Docker/CI) that do not mount the YAML file.

    Deliberately reads api_readonly, not destination: destination holds the
    ETL's write-capable credentials, and this connection must never end up
    using them (see _get_api_readonly).

    Fails closed: if neither supplies real credentials, raises instead of
    silently connecting as postgres/postgres.
    """
    api_readonly = _get_api_readonly()

    user = api_readonly.get("user")
    password = api_readonly.get("password")

    if bool(user) != bool(password):
        raise RuntimeError(
            "The api_readonly block is incomplete. Set both user and password, "
            "or leave both empty to use DATABASE_URL."
        )

    if user and password:
        host = api_readonly.get("dbhostname")
        dbname = api_readonly.get("dbname")

        if not all((user, password, host, dbname)):
            raise RuntimeError(
                "The api_readonly block is incomplete. Set dbhostname, dbname, "
                "user and password, or leave user/password empty to use DATABASE_URL."
            )

        return make_conninfo(
            user=user,
            password=password,
            host=host,
            port=api_readonly.get("port") or 5432,
            dbname=dbname,
        )

    explicit_url = os.getenv("DATABASE_URL")

    if explicit_url:
        return explicit_url

    raise RuntimeError(
        "No database credentials configured. Set api_readonly.user/"
        "api_readonly.password in config/safety.yaml, or use DATABASE_URL as "
        "the fallback — there is no default credential."
    )


@lru_cache(maxsize=1)
def get_database_url() -> str:
    """Cached wrapper to retrieve the assembled database connection URL."""
    return _build_database_url()


def get_connection() -> psycopg.Connection:
    """
    Opens a read-only connection to the UI database with dictionary row factories
    and a strict statement timeout configuration.
    """
    return psycopg.connect(
        get_database_url(),
        row_factory=dict_row,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )


def _validate_public_relation(table_name: str) -> None:
    """
    Security check: ensures the requested relation is explicitly whitelisted
    among approved public B6 views, preventing direct access to base tables.
    """
    if table_name not in B6_PUBLIC_RELATIONS:
        raise ValueError(f"Unsupported public relation: {table_name}")


def check_table_exists(connection, table_name: str) -> bool:
    """Checks whether an approved public view exists in the database schema."""
    _validate_public_relation(table_name)

    with connection.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS exists;",
            (table_name,),
        )

        return bool(cur.fetchone()["exists"])


def check_table_has_rows(connection, table_name: str) -> bool:
    """Checks whether an approved public view contains at least one row of data."""
    _validate_public_relation(table_name)

    query = sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1) AS has_rows;").format(
        sql.Identifier(table_name)
    )

    with connection.cursor() as cur:
        cur.execute(query)

        return bool(cur.fetchone()["has_rows"])
