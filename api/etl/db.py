"""
Database connection management and schema verification module. 
Handles connection string construction, environment variable resolution, 
and connection factory functions for both private source databases 
and public UI destination databases using psycopg.
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
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
    'connection' block — the normal way to configure this, plain user/password
    fields with nothing to assemble by hand. SOURCE_DATABASE_URL is only an
    override for when one's specifically needed (e.g. a Docker deployment
    injecting secrets as environment variables).

    Fails closed: if neither supplies real credentials, raises instead of
    silently connecting as postgres/postgres.
    """
    user = _CONNECTION.get("user")
    password = _CONNECTION.get("password")

    if user and password:
        host = _CONNECTION.get("dbhostname") or "localhost"
        port = _CONNECTION.get("port") or 5432
        dbname = _CONNECTION.get("dbname") or "brerc_source"
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    explicit_url = os.getenv("SOURCE_DATABASE_URL")

    if explicit_url:
        return explicit_url

    raise RuntimeError(
        "No source database credentials configured. Set connection.user/"
        "connection.password in config/safety.yaml, or SOURCE_DATABASE_URL "
        "as an override — there is no default credential."
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
    this, plain user/password fields with nothing to assemble by hand.
    DESTINATION_DATABASE_URL is only an override for when one's specifically
    needed (e.g. a Docker deployment injecting secrets as environment
    variables).

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

    if user and password:
        host = destination.get("dbhostname") or "localhost"
        port = destination.get("port") or 5432
        dbname = destination.get("dbname") or "brerc_ui"
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    explicit_url = os.getenv("DESTINATION_DATABASE_URL")

    if explicit_url:
        return explicit_url

    raise RuntimeError(
        "No destination database credentials configured. Set "
        "destination.user/destination.password in config/safety.yaml, or "
        "DESTINATION_DATABASE_URL as an override — there is no default "
        "credential."
    )


DESTINATION_DATABASE_URL = _build_destination_database_url()


def get_destination_connection() -> psycopg.Connection:
    """Opens and returns a dictionary-yielding connection to the UI destination database."""
    return psycopg.connect(
        DESTINATION_DATABASE_URL,
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
