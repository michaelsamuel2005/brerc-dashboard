"""Fail-closed, read-only access to the published ``serve.*`` views.

Credential resolution deliberately retains Ting Ting's ``api_readonly``
boundary: the API never falls back to the ETL destination credentials and it
has no postgres/postgres default. Production connections require verified TLS;
every live session must use only the dedicated API group role and be
transaction-read-only; routers may name only the five public serving views
owned by the atomic publication store.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import lru_cache
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import IsolationLevel
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app import config

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


def _validate_production_tls(conninfo: str) -> str:
    """Require certificate and hostname verification for production PostgreSQL."""
    if not config.IS_PROD:
        return conninfo

    parameters = conninfo_to_dict(conninfo)
    if parameters.get("sslmode") != "verify-full" or not parameters.get("sslrootcert"):
        raise RuntimeError(
            "Production database TLS requires sslmode=verify-full and an explicit sslrootcert."
        )
    return conninfo


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
        conninfo = make_conninfo(
            user=user,
            password=password,
            host=host,
            port=api_readonly.get("port") or 5432,
            dbname=database,
            sslmode=api_readonly.get("sslmode"),
            sslrootcert=api_readonly.get("sslrootcert"),
        )
        return _validate_production_tls(conninfo)

    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return _validate_production_tls(explicit_url)
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
    """Open a bounded, repeatable-read, transaction-read-only API connection.

    Kept as a compatibility entry point for the existing database safety tests;
    public routers use :func:`serving_connection`, which additionally verifies
    the live session before yielding it. Repeatable read is important because a
    route first reads the active release's capabilities and then reads one or
    more serving views. If an atomic release switch commits between those SQL
    statements, every statement in this request must still describe the same
    release snapshot.
    """
    connection = psycopg.connect(
        get_database_url(),
        row_factory=dict_row,
        autocommit=False,
        options=(
            f"-c statement_timeout={config.DB_STATEMENT_TIMEOUT_MS} "
            "-c default_transaction_read_only=on"
        ),
    )
    connection.isolation_level = IsolationLevel.REPEATABLE_READ
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
                "current_setting('transaction_isolation') AS isolation_level, "
                "pg_catalog.pg_has_role(current_user, 'brerc_api', 'USAGE') AS is_api, "
                "pg_catalog.pg_has_role(current_user, 'brerc_loader', 'USAGE') AS is_loader, "
                "pg_catalog.pg_has_role(current_user, 'brerc_martin', 'USAGE') AS is_martin, "
                "pg_catalog.pg_has_role(current_user, 'brerc_monitor', 'USAGE') AS is_monitor, "
                "pg_catalog.pg_has_role(current_user, 'pg_write_all_data', 'USAGE') "
                "AS can_write_all"
            )
            session = cursor.fetchone()
        if session is None or session.get("read_only") != "on":
            raise RuntimeError("publication database session is not read-only")
        if session.get("isolation_level") != "repeatable read":
            raise RuntimeError("publication database session is not repeatable-read")
        if (
            session.get("is_api") is not True
            or session.get("is_loader") is not False
            or session.get("is_martin") is not False
            or session.get("is_monitor") is not False
            or session.get("can_write_all") is not False
        ):
            raise RuntimeError(
                "publication database session is not using the dedicated read-only API role"
            )
        yield connection
    finally:
        with suppress(Exception):
            connection.rollback()
        with suppress(Exception):
            connection.close()
