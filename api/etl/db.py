"""
Database connection management and schema verification module.
Handles connection string construction, environment variable resolution,
and connection factory functions for both private source databases
and public UI destination databases using psycopg.
"""

import os
from functools import lru_cache
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from etl.load.loader import load_safety_config


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CONFIG = load_safety_config()


# ============================================================
# SOURCE DATABASE
# ============================================================

_CONNECTION = CONFIG.get("connection", {})


def _build_source_database_url() -> str:
    """
    Assembles the source database connection URL, preferring config/safety.yaml's
    'connection' block — the normal way to configure this, with explicit
    host/database/user/password fields. SOURCE_DATABASE_URL is the fallback
    for deployments that do not mount the YAML file.

    Fails closed: if neither supplies real credentials, raises instead of
    silently connecting as postgres/postgres.
    """
    user = _CONNECTION.get("user")
    password = _CONNECTION.get("password")

    if bool(user) != bool(password):
        raise RuntimeError(
            "The source connection block is incomplete. Set both user and "
            "password, or leave both empty to use SOURCE_DATABASE_URL."
        )

    if user and password:
        host = _CONNECTION.get("dbhostname")
        dbname = _CONNECTION.get("dbname")

        if not all((user, password, host, dbname)):
            raise RuntimeError(
                "The source connection block is incomplete. Set dbhostname, "
                "dbname, user and password, or leave user/password empty to use "
                "SOURCE_DATABASE_URL."
            )

        return make_conninfo(
            user=user,
            password=password,
            host=host,
            port=_CONNECTION.get("port") or 5432,
            dbname=dbname,
        )

    explicit_url = os.getenv("SOURCE_DATABASE_URL")

    if explicit_url:
        return explicit_url

    raise RuntimeError(
        "No source database credentials configured. Set connection.user/"
        "connection.password in config/safety.yaml, or use "
        "SOURCE_DATABASE_URL as the fallback — there is no default credential."
    )


def get_source_connection() -> psycopg.Connection:
    """
    Opens a connection to BRERC's private source database.

    Builds the connection URL lazily (only when this is actually called),
    not at import time — get_source_connection() is only ever called in
    source.mode == "database" setups (see etl/job.py). A CSV-mode setup
    never needs source database credentials at all, so importing this
    module must not fail closed on their absence.

    NOTE: deliberately NO row_factory here, unlike the destination connection.
    This connection is only ever handed to pandas.read_sql (see etl/job.py), and
    pandas cannot read psycopg's dict_row rows — instead of failing, it silently
    returns a DataFrame in which every value is the COLUMN NAME:

        species_no  scientific  nbn_number
        species_no  scientific  nbn_number     <- not the data

    which then shows up as "Species resolution coverage: 0.00%" and every record
    being blurred fail-closed. If you add a row_factory back, database mode stops
    working without raising anything.
    """
    return psycopg.connect(_build_source_database_url())


# ============================================================
# DESTINATION / UI DATABASE
# ============================================================


def _build_destination_database_url() -> str:
    """
    Assembles the UI destination database connection string, preferring
    config/safety.yaml's 'destination' block — the normal way to configure
    this, with explicit host/database/user/password fields.
    DESTINATION_DATABASE_URL is the fallback for deployments that do not mount
    the YAML file.

    Deliberately does NOT fall back to the generic DATABASE_URL — that variable
    is what app/db.py uses for the public API's read-only connection. If the
    ETL silently reused it, either the ETL's writes would fail against a
    read-only role, or someone "fixing" that by widening DATABASE_URL's
    permissions would unknowingly give the public API write access too.
    Keeping the names distinct means that mistake can't happen by accident.

    Also fails closed on credentials: if neither safety.yaml nor
    DESTINATION_DATABASE_URL supplies real credentials, raises instead of
    silently connecting as postgres/postgres.
    """
    destination = CONFIG.get("destination", {})

    user = destination.get("user")
    password = destination.get("password")

    if bool(user) != bool(password):
        raise RuntimeError(
            "The destination block is incomplete. Set both user and password, "
            "or leave both empty to use DESTINATION_DATABASE_URL."
        )

    if user and password:
        host = destination.get("dbhostname")
        dbname = destination.get("dbname")

        if not all((user, password, host, dbname)):
            raise RuntimeError(
                "The destination block is incomplete. Set dbhostname, dbname, "
                "user and password, or leave user/password empty to use "
                "DESTINATION_DATABASE_URL."
            )

        return make_conninfo(
            user=user,
            password=password,
            host=host,
            port=destination.get("port") or 5432,
            dbname=dbname,
        )

    explicit_url = os.getenv("DESTINATION_DATABASE_URL")

    if explicit_url:
        return explicit_url

    raise RuntimeError(
        "No destination database credentials configured. Set "
        "destination.user/destination.password in config/safety.yaml, or "
        "use DESTINATION_DATABASE_URL as the fallback — there is no default "
        "credential."
    )


@lru_cache(maxsize=1)
def get_destination_database_url() -> str:
    """Returns the destination connection string without resolving it at import time."""
    return _build_destination_database_url()


def get_destination_connection() -> psycopg.Connection:
    """Opens and returns a dictionary-yielding connection to the UI destination database."""
    return psycopg.connect(
        get_destination_database_url(),
        row_factory=dict_row,
    )


# ============================================================
# DESTINATION TABLE CHECKS
# ============================================================


def check_table_exists(
    connection: psycopg.Connection,
    table_name: str,
) -> bool:
    """Checks whether a destination table exists in the database schema."""

    with connection.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS exists;",
            (table_name,),
        )

        return bool(cur.fetchone()["exists"])


def check_table_has_rows(
    connection: psycopg.Connection,
    table_name: str,
) -> bool:
    """Checks whether a destination table contains at least one row of data."""

    query = sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1) AS has_rows;").format(
        sql.Identifier(table_name)
    )

    with connection.cursor() as cur:
        cur.execute(query)

        return bool(cur.fetchone()["has_rows"])
