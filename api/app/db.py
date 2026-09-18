"""Fail-closed, read-only access to the published ``serve.*`` views.

Credential resolution deliberately retains Ting Ting's ``api_readonly``
boundary: the API never falls back to the ETL destination credentials and it
has no postgres/postgres default. The reviewed production path uses a libpq
service plus passfile rather than a credential-bearing environment DSN.
Production connections require verified TLS; every live session must use only
the dedicated API group role and be transaction-read-only; routers may name
only the five public serving views owned by the atomic publication store.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import lru_cache
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import IsolationLevel
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app import config

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _absolute_environment_file(name: str) -> str:
    value = _required_environment(name)
    if not Path(value).is_absolute():
        raise RuntimeError(f"{name} must be an absolute path")
    return value


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Load host-only YAML when the ETL package is present.

    The API-only image need not package the ETL. Development retains its
    explicit ``DATABASE_URL`` fallback; production requires service mode and
    never reaches this YAML/URL compatibility path. Missing configuration is
    not converted into a default credential anywhere below.
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
    """Resolve explicit read-only connection info or fail without guessing.

    Explicit service mode is isolated from legacy configuration. Otherwise,
    ``config/safety.yaml`` takes precedence when it supplies a complete
    ``api_readonly`` block and ``DATABASE_URL`` is the compatibility fallback.
    The write-capable ``destination`` block is intentionally ignored.
    """
    mode = os.environ.get("BRERC_API_DB_MODE", "").strip().lower()
    if config.IS_PROD and mode != "service":
        raise RuntimeError("Production database access requires BRERC_API_DB_MODE=service")
    if mode:
        if mode != "service":
            raise RuntimeError("BRERC_API_DB_MODE must be 'service' when set")
        if os.environ.get("PGPASSWORD"):
            raise RuntimeError("PGPASSWORD is not permitted for the public API")
        if os.environ.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL must be unset when BRERC_API_DB_MODE=service")
        service = _required_environment("BRERC_API_DB_SERVICE")
        if _SERVICE_NAME.fullmatch(service) is None:
            raise RuntimeError("BRERC_API_DB_SERVICE is invalid")
        # libpq reads PGSERVICEFILE itself. Requiring an absolute reviewed path
        # prevents an accidental lookup from the service account's home or CWD.
        _absolute_environment_file("PGSERVICEFILE")
        return make_conninfo(
            service=service,
            passfile=_absolute_environment_file("BRERC_API_DB_PASSFILE"),
            sslrootcert=_absolute_environment_file("BRERC_API_DB_SSLROOTCERT"),
            sslmode="verify-full",
            connect_timeout=10,
        )

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
        return conninfo

    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url
    raise RuntimeError(
        "No database credentials configured. Set api_readonly.user/"
        "api_readonly.password in config/safety.yaml, or use DATABASE_URL as "
        "the fallback — there is no default credential."
    )


def _expected_session_identity() -> tuple[str | None, str | None]:
    """Return an all-or-nothing deployment identity assertion.

    Service mode is the reviewed production path and cannot connect before its
    exact destination database and distinct login role have been named. Legacy
    development/CI configuration remains compatible, but may opt into the same
    assertion by setting both values.
    """
    expected_database = os.environ.get("BRERC_API_EXPECTED_DATABASE", "").strip()
    expected_role = os.environ.get("BRERC_API_EXPECTED_ROLE", "").strip()
    if bool(expected_database) != bool(expected_role):
        raise RuntimeError(
            "BRERC_API_EXPECTED_DATABASE and BRERC_API_EXPECTED_ROLE must be set together"
        )
    if (
        config.IS_PROD or os.environ.get("BRERC_API_DB_MODE", "").strip().lower() == "service"
    ) and not (expected_database and expected_role):
        raise RuntimeError(
            "production/service mode requires BRERC_API_EXPECTED_DATABASE "
            "and BRERC_API_EXPECTED_ROLE"
        )
    return expected_database or None, expected_role or None


@lru_cache(maxsize=1)
def get_database_url() -> str:
    """Cache the already fail-closed PostgreSQL connection information."""
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
    expected_database, expected_role = _expected_session_identity()
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database() AS database_name, "
                "current_user AS login_role, session_user AS session_role, "
                "current_setting('transaction_read_only') AS read_only, "
                "current_setting('transaction_isolation') AS isolation_level, "
                "(SELECT rolcanlogin FROM pg_catalog.pg_roles "
                " WHERE rolname = current_user) AS can_login, "
                "(SELECT rolinherit FROM pg_catalog.pg_roles "
                " WHERE rolname = current_user) AS can_inherit, "
                "(SELECT rolsuper FROM pg_catalog.pg_roles "
                " WHERE rolname = current_user) AS is_superuser, "
                "(SELECT rolcreatedb FROM pg_catalog.pg_roles "
                " WHERE rolname = current_user) AS can_create_db, "
                "(SELECT rolcreaterole FROM pg_catalog.pg_roles "
                " WHERE rolname = current_user) AS can_create_role, "
                "(SELECT rolreplication FROM pg_catalog.pg_roles "
                " WHERE rolname = current_user) AS can_replicate, "
                "(SELECT rolbypassrls FROM pg_catalog.pg_roles "
                " WHERE rolname = current_user) AS can_bypass_rls, "
                "pg_catalog.pg_has_role(current_user, 'brerc_api', 'USAGE') AS is_api, "
                "pg_catalog.pg_has_role(current_user, 'brerc_loader', 'USAGE') AS is_loader, "
                "pg_catalog.pg_has_role(current_user, 'brerc_martin', 'USAGE') AS is_martin, "
                "pg_catalog.pg_has_role(current_user, 'brerc_monitor', 'USAGE') AS is_monitor, "
                "pg_catalog.pg_has_role(current_user, 'pg_write_all_data', 'USAGE') "
                "AS can_write_all, "
                "ARRAY(SELECT parent.rolname::text "
                "FROM pg_catalog.pg_auth_members AS membership "
                "JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member "
                "JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid "
                "WHERE member.rolname = current_user "
                "ORDER BY parent.rolname) AS direct_roles, "
                "ARRAY(SELECT role.rolname::text FROM pg_catalog.pg_roles AS role "
                "WHERE role.rolname <> current_user "
                "AND pg_catalog.pg_has_role(current_user, role.oid, 'USAGE') "
                "ORDER BY role.rolname) AS effective_roles"
            )
            session = cursor.fetchone()
        if session is None or session.get("read_only") != "on":
            raise RuntimeError("publication database session is not read-only")
        if session.get("isolation_level") != "repeatable read":
            raise RuntimeError("publication database session is not repeatable-read")
        direct_roles = tuple(session.get("direct_roles") or ())
        effective_roles = tuple(session.get("effective_roles") or ())
        if (
            session.get("login_role") != session.get("session_role")
            or (expected_database is not None and session.get("database_name") != expected_database)
            or (expected_role is not None and session.get("login_role") != expected_role)
            or session.get("can_login") is not True
            or session.get("can_inherit") is not True
            or session.get("is_superuser") is not False
            or session.get("can_create_db") is not False
            or session.get("can_create_role") is not False
            or session.get("can_replicate") is not False
            or session.get("can_bypass_rls") is not False
            or session.get("is_api") is not True
            or session.get("is_loader") is not False
            or session.get("is_martin") is not False
            or session.get("is_monitor") is not False
            or session.get("can_write_all") is not False
            or direct_roles != ("brerc_api",)
            or effective_roles != ("brerc_api",)
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
