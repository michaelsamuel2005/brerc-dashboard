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
    Assembles the source database connection URL from safety.yaml's 
    'connection' configuration block or environment variables.
    """

    explicit_url = os.getenv("SOURCE_DATABASE_URL")

    if explicit_url:
        return explicit_url

    host = _CONNECTION.get("dbhostname") or "localhost"
    port = _CONNECTION.get("port") or 5432
    dbname = _CONNECTION.get("dbname") or "brerc_source"
    user = _CONNECTION.get("user") or "postgres"
    password = _CONNECTION.get("password") or "postgres"

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


SOURCE_DATABASE_URL = _build_source_database_url()


def get_source_connection() -> psycopg.Connection:
    """
    Opens a connection to BRERC's private source database.

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
    return psycopg.connect(SOURCE_DATABASE_URL)


# ============================================================
# DESTINATION / UI DATABASE
# ============================================================


def _build_destination_database_url() -> str:
    """
    Assemble the UI database connection string, checking environment variables 
    (DESTINATION_DATABASE_URL or generic DATABASE_URL) before falling back to safety.yaml.
    """
    explicit_url = os.getenv("DESTINATION_DATABASE_URL") or os.getenv("DATABASE_URL")

    if explicit_url:
        return explicit_url

    destination = CONFIG.get("destination", {})

    host = destination.get("dbhostname") or "localhost"
    port = destination.get("port") or 5432
    dbname = destination.get("dbname") or "brerc_ui"
    user = destination.get("user") or "postgres"
    password = destination.get("password") or "postgres"

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


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
