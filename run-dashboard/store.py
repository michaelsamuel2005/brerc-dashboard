"""Read-only PostgreSQL store for the internal ETL run-history dashboard.

Only the deliberately narrow ``serve.etl_job_status`` monitoring view is
queried.  The connection is verified before use so the dashboard cannot be
accidentally deployed with loader, API, Martin or superuser privileges.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
_DASHBOARD_ENVIRONMENTS = frozenset({"dev", "test", "prod"})
_FAILURE_SUMMARIES = {
    "LOADER_FAILED": "The refresh failed. Review the protected loader logs.",
    "LOADER_CONFIGURATION_INVALID": "The protected loader configuration is invalid.",
    "INCREMENTAL_SOURCE_CONTRACT_BLOCKED": "An unsupported incremental load was refused.",
    "LOADER_COORDINATOR_UNAVAILABLE": "The installed loader is incomplete or unavailable.",
    "LOADER_EXECUTION_FAILED": "The refresh stopped because an internal operation failed.",
    "LOADER_POLICY_INVALID": "The approved publication-policy evidence was rejected.",
    "LOADER_RELEASE_BLOCKED": "Publication prerequisites have not been satisfied.",
    "LOADER_TARGET_CONNECTION_FAILED": "The publication database could not be reached safely.",
    "LOADER_TARGET_PROTOCOL_INVALID": "The publication database failed its safety handshake.",
    "LOADER_ALREADY_RUNNING": "Another refresh already holds the source lock.",
    "LOADER_CANDIDATE_INVALID": "The candidate release failed validation.",
    "LOADER_SOURCE_COUNT_REJECTED": "The source snapshot exceeded its approved row limits.",
    "LOADER_CLEANUP_FAILED": "Candidate cleanup failed and needs operator attention.",
    "LOADER_CLEANUP_PENDING": "Candidate cleanup remains pending.",
    "WORKER_LOST": "The refresh worker stopped before recording a terminal outcome.",
}


class RunHistoryConfigurationError(RuntimeError):
    """The dashboard's credential-free connection configuration is invalid."""


class RunHistoryUnavailable(RuntimeError):
    """The authoritative monitoring view could not be read safely."""


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RunHistoryConfigurationError(f"{name} is required")
    return value


def validated_dashboard_environment() -> str:
    """Return one explicit deployment environment or fail closed."""
    value = _required_environment("DASHBOARD_ENV").lower()
    if value not in _DASHBOARD_ENVIRONMENTS:
        raise RunHistoryConfigurationError(
            "DASHBOARD_ENV must be exactly 'dev', 'test' or 'prod'"
        )
    return value


def _absolute_file(name: str) -> str:
    raw = _required_environment(name)
    path = Path(raw)
    if not path.is_absolute():
        raise RunHistoryConfigurationError(f"{name} must be an absolute path")
    return raw


def _connection_info() -> str:
    """Resolve either a libpq service or an explicit development DSN.

    Production requires a service name, passfile and CA path.  The tracked
    configuration therefore contains no password or complete DSN.
    """
    mode = os.environ.get("RUN_DASHBOARD_DB_MODE", "").strip().lower()
    environment = validated_dashboard_environment()
    if mode == "service":
        service = _required_environment("RUN_DASHBOARD_DB_SERVICE")
        if _SERVICE_NAME.fullmatch(service) is None:
            raise RunHistoryConfigurationError("RUN_DASHBOARD_DB_SERVICE is invalid")
        # libpq reads PGSERVICEFILE directly. Validate it here rather than
        # accepting an unreviewed relative lookup path.
        _absolute_file("PGSERVICEFILE")
        return make_conninfo(
            service=service,
            passfile=_absolute_file("RUN_DASHBOARD_DB_PASSFILE"),
            sslrootcert=_absolute_file("RUN_DASHBOARD_DB_SSLROOTCERT"),
            sslmode="verify-full",
            connect_timeout=10,
        )
    if mode == "direct":
        if environment == "prod":
            raise RunHistoryConfigurationError(
                "production run history requires RUN_DASHBOARD_DB_MODE=service"
            )
        conninfo = _required_environment("RUN_DASHBOARD_DATABASE_URL")
        try:
            parsed = conninfo_to_dict(conninfo)
        except Exception:
            raise RunHistoryConfigurationError(
                "RUN_DASHBOARD_DATABASE_URL is invalid"
            ) from None
        if not parsed.get("dbname"):
            raise RunHistoryConfigurationError(
                "RUN_DASHBOARD_DATABASE_URL must name a database"
            )
        return make_conninfo(conninfo, connect_timeout=10)
    raise RunHistoryConfigurationError(
        "RUN_DASHBOARD_DB_MODE must be 'service' or 'direct'"
    )


def _duration_seconds(
    started_at: object, finished_at: object, heartbeat_at: object
) -> float | None:
    if not isinstance(started_at, datetime):
        return None
    end = finished_at if isinstance(finished_at, datetime) else heartbeat_at
    if not isinstance(end, datetime) or end < started_at:
        return None
    return round((end - started_at).total_seconds(), 3)


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _display_status(status: object) -> str:
    if status == "succeeded":
        return "successful"
    if status in {"failed", "cancelled"}:
        return str(status)
    return "running"


def _normalise_row(row: dict[str, Any]) -> dict[str, object]:
    failure_code = row.get("failure_code")
    return {
        "job_id": str(row["job_id"]),
        "source_id": str(row["source_id"]),
        "attempt": int(row["attempt"]),
        "load_mode": str(row["load_mode"]),
        "status": _display_status(row.get("status")),
        "lifecycle_status": str(row["status"]),
        "started_at": _iso(row.get("started_at") or row.get("created_at")),
        "finished_at": _iso(row.get("finished_at")),
        "duration_seconds": _duration_seconds(
            row.get("started_at"), row.get("finished_at"), row.get("heartbeat_at")
        ),
        "failure_code": str(failure_code) if failure_code is not None else None,
        "failure_summary": _FAILURE_SUMMARIES.get(str(failure_code))
        if failure_code is not None
        else None,
        "source_rows_seen": row.get("source_rows_seen"),
        "candidate_rows": row.get("candidate_rows"),
        "rows_withheld": row.get("rows_withheld"),
        "reused_active_release": bool(row.get("reused_active_release", False)),
    }


def _verify_session(cursor: Any) -> None:
    cursor.execute(
        "SELECT current_database() AS database_name, current_user AS login_role, "
        "session_user AS session_role, "
        "current_setting('transaction_read_only') AS read_only, "
        "(SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user) AS is_superuser, "
        "(SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = current_user) AS can_login, "
        "(SELECT rolcreatedb FROM pg_catalog.pg_roles WHERE rolname = current_user) AS can_create_db, "
        "(SELECT rolcreaterole FROM pg_catalog.pg_roles WHERE rolname = current_user) AS can_create_role, "
        "(SELECT rolreplication FROM pg_catalog.pg_roles WHERE rolname = current_user) AS can_replicate, "
        "(SELECT rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = current_user) AS can_bypass_rls, "
        "ARRAY(SELECT role.rolname::text FROM pg_catalog.pg_roles AS role "
        "WHERE role.rolname <> current_user "
        "AND pg_catalog.pg_has_role(current_user, role.oid, 'USAGE') "
        "ORDER BY role.rolname) AS effective_roles, "
        "ARRAY(SELECT parent.rolname::text "
        "FROM pg_catalog.pg_auth_members AS membership "
        "JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member "
        "JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid "
        "WHERE member.rolname = current_user ORDER BY parent.rolname) AS direct_roles"
    )
    row = cursor.fetchone()
    if not isinstance(row, dict):
        raise RunHistoryUnavailable("monitor session verification failed")
    expected_database = _required_environment("RUN_DASHBOARD_EXPECTED_DATABASE")
    expected_role = _required_environment("RUN_DASHBOARD_EXPECTED_ROLE")
    effective_roles = tuple(row.get("effective_roles") or ())
    direct_roles = tuple(row.get("direct_roles") or ())
    if (
        row.get("database_name") != expected_database
        or row.get("login_role") != expected_role
        or row.get("session_role") != expected_role
        or row.get("read_only") != "on"
        or row.get("is_superuser") is not False
        or row.get("can_login") is not True
        or row.get("can_create_db") is not False
        or row.get("can_create_role") is not False
        or row.get("can_replicate") is not False
        or row.get("can_bypass_rls") is not False
        or effective_roles != ("brerc_monitor",)
        or direct_roles != ("brerc_monitor",)
    ):
        raise RunHistoryUnavailable(
            "monitor session identity or privileges are invalid"
        )


def fetch_runs(limit: int = 500) -> list[dict[str, object]]:
    """Return recent authoritative loader jobs without exposing raw errors/data."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer from 1 to 500")
    try:
        with psycopg.connect(
            _connection_info(),
            autocommit=False,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        ) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                _verify_session(cursor)
                cursor.execute(
                    "SELECT job_id, source_id, attempt, load_mode, status, started_at, "
                    "heartbeat_at, finished_at, failure_code, source_rows_seen, "
                    "candidate_rows, rows_withheld, created_at, reused_active_release "
                    "FROM serve.etl_job_status ORDER BY created_at DESC, job_id DESC LIMIT %s",
                    (limit,),
                )
                rows = cursor.fetchall()
                normalised = [_normalise_row(dict(row)) for row in rows]
            connection.rollback()
    except RunHistoryConfigurationError:
        raise
    except RunHistoryUnavailable:
        raise
    except Exception:
        # Psycopg exceptions can contain a DSN, SQL details or server text. Keep
        # the browser-visible failure fixed and inspect protected service logs.
        raise RunHistoryUnavailable(
            "authoritative run history is unavailable"
        ) from None
    return normalised
