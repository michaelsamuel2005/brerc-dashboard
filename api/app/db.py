"""Fail-closed, read-only access to the published ``serve.*`` views.

Credential resolution deliberately retains Ting Ting's ``api_readonly``
boundary: the API never falls back to the ETL destination credentials and it
has no postgres/postgres default. Query code then adds two independent guards:
every session is transaction-read-only, and routers may name only the five
public serving views owned by the atomic publication store.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import lru_cache
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app.config import DB_STATEMENT_TIMEOUT_MS

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Load host-only YAML when the ETL package is present.

    The API-only image need not package the ETL, so ``DATABASE_URL`` remains a
    supported fallback. Missing configuration is not converted into a default
    credential anywhere below.
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
    """Return only the API credential block, never the ETL destination block."""
    return get_config().get("api_readonly", {})


def _build_database_url() -> str:
    """Resolve an explicit read-only credential or fail without guessing.

    ``config/safety.yaml`` takes precedence when it supplies a complete
    ``api_readonly`` block. ``DATABASE_URL`` is the deployment fallback. The
    write-capable ``destination`` block is intentionally ignored.
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
        database = api_readonly.get("dbname")
        if not all((host, database)):
            raise RuntimeError(
                "The api_readonly block is incomplete. Set dbhostname, dbname, "
                "user and password, or leave user/password empty to use DATABASE_URL."
            )
        return make_conninfo(
            user=user,
            password=password,
            host=host,
            port=api_readonly.get("port") or 5432,
            dbname=database,
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
    """Cache the already fail-closed credential resolution."""
    return _build_database_url()


SERVING_RELATIONS = frozenset(
    {
        "serve.public_release",
        "serve.public_species",
        "serve.public_distribution_cell",
        "serve.public_species_year",
        "serve.public_record",
    }
)


class ServingRelationError(RuntimeError):
    """A query attempted to name a relation outside the public serving surface."""


def assert_serving_relation(relation: str) -> str:
    """Return an allow-listed serving view for use in a fixed SQL constant."""
    if relation not in SERVING_RELATIONS:
        raise ServingRelationError("relation is outside the public serving surface")
    return relation


def get_connection() -> psycopg.Connection:
    """Open a bounded transaction-read-only API connection.

    Kept as a compatibility entry point for the existing database safety tests;
    public routers use :func:`serving_connection`, which additionally verifies
    the live session before yielding it.
    """
    connection = psycopg.connect(
        get_database_url(),
        row_factory=dict_row,
        autocommit=False,
        options=(
            f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} -c default_transaction_read_only=on"
        ),
    )
    connection.read_only = True
    return connection


@contextmanager
def serving_connection() -> Iterator[psycopg.Connection]:
    """Yield a verified read-only connection and always roll it back."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('transaction_read_only') AS read_only, "
                "pg_catalog.pg_has_role(current_user, 'pg_write_all_data', 'USAGE') "
                "AS can_write_all"
            )
            session = cursor.fetchone()
        if (
            session is None
            or session.get("read_only") != "on"
            or session.get("can_write_all") is not False
        ):
            raise RuntimeError("publication database session is not read-only")
        yield connection
    finally:
        with suppress(Exception):
            connection.rollback()
        with suppress(Exception):
            connection.close()
