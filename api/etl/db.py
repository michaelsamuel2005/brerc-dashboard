"""
Database connection for BRERC's private source database (~5M records).

Follows the same pattern as app/db.py's UI database connection (D-005):
all connection fields (host, port, dbname, user, password) are read
from safety.yaml's `connection:` block, so environments can differ
(local / staging / prod) just by editing config. NOTE: this means
safety.yaml holds a real password when filled in for a real environment
- keep that file out of version control (or restrict its permissions)
in any environment where it holds real credentials.

If SOURCE_DATABASE_URL is set directly in the environment, it takes
priority over the assembled safety.yaml URL.

Read-only access is expected here - the pipeline reads raw records and
the species dictionary, it never writes back to the source. Enforce
this via the database credential BRERC issues (a read-only user), not
in code - see the "Access & data" sign-off in the backend plan (§12).
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from etl.load.loader import load_safety_config

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CONFIG = load_safety_config()
_CONNECTION = CONFIG.get("connection", {})


def _build_source_database_url() -> str:
    """
    Assembles the source database connection string entirely from
    safety.yaml's `connection:` block (host, port, dbname, user,
    password).

    SOURCE_DATABASE_URL, if set directly in the environment, overrides
    all of this - useful for deployments that inject a full connection
    string as one secret.
    """
    explicit_url = os.getenv("SOURCE_DATABASE_URL")
    if explicit_url:
        return explicit_url

    # Local development defaults so this still runs before safety.yaml
    # is filled in for a real environment - contain no real secret.
    # BRERC should issue a read-only user for this connection (see
    # module docstring) - set that in safety.yaml's connection.user.
    host = _CONNECTION.get("dbhostname") or "localhost"
    port = _CONNECTION.get("port") or 5432
    dbname = _CONNECTION.get("dbname") or "brerc_source"
    user = _CONNECTION.get("user") or "postgres"
    password = _CONNECTION.get("password") or "postgres"

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


SOURCE_DATABASE_URL = _build_source_database_url()


def get_source_connection() -> psycopg.Connection:
    """
    Open a connection to BRERC's private source database.
    """
    return psycopg.connect(SOURCE_DATABASE_URL, row_factory=dict_row)