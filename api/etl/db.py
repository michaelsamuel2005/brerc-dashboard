"""
Database connection for BRERC's private source database (~5M records).

Follows the same pattern as app/db.py's UI database connection (D-005):
connection details live in ONE place, read from an environment variable,
so moving from a laptop to a real server is a credentials change only.

Read-only access is expected here - the pipeline reads raw records and
the species dictionary, it never writes back to the source. Enforce
this via the database credential BRERC issues (a read-only user), not
in code - see the "Access & data" sign-off in the backend plan (§12).
"""

# Update this later to use the config 

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SOURCE_DATABASE_URL = os.getenv(
    "SOURCE_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/brerc_source",
)


def get_source_connection() -> psycopg.Connection:
    """
    Open a connection to BRERC's private source database.
    """
    return psycopg.connect(SOURCE_DATABASE_URL, row_factory=dict_row)