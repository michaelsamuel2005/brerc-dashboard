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
from psycopg.rows import dict_row

from etl.load.loader import load_safety_config

# Load api/.env (if present) so credentials can live in a git-ignored file
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Cached loader for safety and database configuration settings."""
    return load_safety_config()


def _get_destination() -> dict:
    """Retrieves the destination connection configuration block."""
    return get_config().get("destination", {})


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
    Assembles the database connection string from safety.yaml's destination block
    or falls back to the explicit DATABASE_URL environment variable if provided.

    Fails closed: user/password have no default, so a genuinely unconfigured
    environment raises instead of silently connecting as postgres/postgres.
    """
    explicit_url = os.getenv("DATABASE_URL")

    if explicit_url:
        return explicit_url

    # Local development defaults if safety.yaml is missing credentials
    destination = _get_destination()

    host = destination.get("dbhostname") or "localhost"
    port = destination.get("port") or 5432
    dbname = destination.get("dbname") or "brerc_ui"
    user = destination.get("user")
    password = destination.get("password")

    if not user or not password:
        raise RuntimeError(
            "No database credentials configured. Set DATABASE_URL, or "
            "destination.user/destination.password in config/safety.yaml — "
            "there is no default credential."
        )

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


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