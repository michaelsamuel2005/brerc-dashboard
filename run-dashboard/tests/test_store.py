"""Safety and response-contract tests for the authoritative PostgreSQL store."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

import store

JOB_ID = UUID("00000000-0000-4000-8000-000000000056")


def _job_row(**overrides):
    started = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)
    row = {
        "job_id": JOB_ID,
        "source_id": "brerc-main-data-dash",
        "attempt": 4,
        "load_mode": "refresh",
        "status": "succeeded",
        "started_at": started,
        "heartbeat_at": started + timedelta(seconds=25),
        "finished_at": started + timedelta(seconds=30),
        "failure_code": None,
        "source_rows_seen": 1_916,
        "candidate_rows": 1_125,
        "rows_withheld": 791,
        "created_at": started - timedelta(seconds=1),
        "reused_active_release": False,
    }
    row.update(overrides)
    return row


def _verified_session(**overrides):
    expected_database = os.environ["RUN_DASHBOARD_EXPECTED_DATABASE"]
    expected_role = os.environ["RUN_DASHBOARD_EXPECTED_ROLE"]
    row = {
        "database_name": expected_database,
        "login_role": expected_role,
        "session_role": expected_role,
        "read_only": "on",
        "is_superuser": False,
        "can_login": True,
        "can_create_db": False,
        "can_create_role": False,
        "can_replicate": False,
        "can_bypass_rls": False,
        "effective_roles": ["brerc_monitor"],
        "direct_roles": ["brerc_monitor"],
    }
    row.update(overrides)
    return row


def _mock_connection(session=None, rows=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = session or _verified_session()
    cursor.fetchall.return_value = rows if rows is not None else [_job_row()]
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor_context
    return connection, cursor


def test_direct_connection_is_never_available_in_production(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ENV", "prod")
    monkeypatch.setenv("RUN_DASHBOARD_DB_MODE", "direct")

    with pytest.raises(store.RunHistoryConfigurationError, match="requires.*service"):
        store._connection_info()


@pytest.mark.parametrize("environment", (None, "", "production", "PROD-TYPO"))
def test_connection_rejects_missing_or_unknown_environment(monkeypatch, environment):
    if environment is None:
        monkeypatch.delenv("DASHBOARD_ENV", raising=False)
    else:
        monkeypatch.setenv("DASHBOARD_ENV", environment)

    with pytest.raises(store.RunHistoryConfigurationError, match="DASHBOARD_ENV"):
        store._connection_info()


def test_service_connection_requires_absolute_protected_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_ENV", "prod")
    monkeypatch.setenv("RUN_DASHBOARD_DB_MODE", "service")
    monkeypatch.setenv("RUN_DASHBOARD_DB_SERVICE", "brerc-monitor")
    monkeypatch.setenv("PGSERVICEFILE", str(tmp_path / "pg_service.conf"))
    monkeypatch.setenv("RUN_DASHBOARD_DB_PASSFILE", str(tmp_path / "monitor.pgpass"))
    monkeypatch.setenv("RUN_DASHBOARD_DB_SSLROOTCERT", str(tmp_path / "ca.crt"))

    parameters = store.conninfo_to_dict(store._connection_info())

    assert parameters["service"] == "brerc-monitor"
    assert parameters["sslmode"] == "verify-full"
    assert parameters["sslrootcert"] == str(tmp_path / "ca.crt")
    assert parameters["passfile"] == str(tmp_path / "monitor.pgpass")
    assert parameters["connect_timeout"] == "10"


def test_service_connection_rejects_relative_service_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_ENV", "prod")
    monkeypatch.setenv("RUN_DASHBOARD_DB_MODE", "service")
    monkeypatch.setenv("RUN_DASHBOARD_DB_SERVICE", "brerc-monitor")
    monkeypatch.setenv("PGSERVICEFILE", "relative.conf")
    monkeypatch.setenv("RUN_DASHBOARD_DB_PASSFILE", str(tmp_path / "monitor.pgpass"))
    monkeypatch.setenv("RUN_DASHBOARD_DB_SSLROOTCERT", str(tmp_path / "ca.crt"))

    with pytest.raises(store.RunHistoryConfigurationError, match="absolute path"):
        store._connection_info()


def test_fetch_runs_reads_only_the_monitor_view_and_returns_fixed_fields():
    connection, cursor = _mock_connection()

    with patch("store.psycopg.connect", return_value=connection) as connect:
        result = store.fetch_runs()

    assert result == [
        {
            "job_id": str(JOB_ID),
            "source_id": "brerc-main-data-dash",
            "attempt": 4,
            "load_mode": "refresh",
            "status": "successful",
            "lifecycle_status": "succeeded",
            "started_at": "2026-09-03T01:00:00+00:00",
            "finished_at": "2026-09-03T01:00:30+00:00",
            "duration_seconds": 30.0,
            "failure_code": None,
            "failure_summary": None,
            "source_rows_seen": 1_916,
            "candidate_rows": 1_125,
            "rows_withheld": 791,
            "reused_active_release": False,
        }
    ]
    connect.assert_called_once()
    assert connection.read_only is True
    connection.rollback.assert_called_once_with()
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("FROM serve.etl_job_status" in statement for statement in statements)
    assert all("loader_control.etl_job" not in statement for statement in statements)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_name", "wrong"),
        ("login_role", "wrong"),
        ("session_role", "wrong"),
        ("read_only", "off"),
        ("is_superuser", True),
        ("can_login", False),
        ("can_create_db", True),
        ("can_create_role", True),
        ("can_replicate", True),
        ("can_bypass_rls", True),
        ("effective_roles", []),
        ("effective_roles", ["brerc_monitor", "pg_read_all_data"]),
        ("direct_roles", []),
        ("direct_roles", ["brerc_monitor", "unrelated_role"]),
    ],
)
def test_fetch_runs_rejects_wrong_identity_or_privilege(field, value):
    connection, _ = _mock_connection(session=_verified_session(**{field: value}))

    with (
        patch("store.psycopg.connect", return_value=connection),
        pytest.raises(store.RunHistoryUnavailable, match="identity or privileges"),
    ):
        store.fetch_runs()


def test_failure_mapping_exposes_only_fixed_code_and_repository_text():
    row = _job_row(
        status="failed",
        failure_code="LOADER_POLICY_INVALID",
        reused_active_release=False,
    )

    result = store._normalise_row(row)

    assert result["status"] == "failed"
    assert result["failure_code"] == "LOADER_POLICY_INVALID"
    assert (
        result["failure_summary"]
        == "The approved publication-policy evidence was rejected."
    )
    assert set(result) == {
        "job_id",
        "source_id",
        "attempt",
        "load_mode",
        "status",
        "lifecycle_status",
        "started_at",
        "finished_at",
        "duration_seconds",
        "failure_code",
        "failure_summary",
        "source_rows_seen",
        "candidate_rows",
        "rows_withheld",
        "reused_active_release",
    }


def test_fetch_runs_bounds_the_query_limit():
    for value in (True, 0, 501, 1.5):
        with pytest.raises(ValueError, match="1 to 500"):
            store.fetch_runs(value)


def test_malformed_view_row_is_redacted_as_unavailable():
    connection, _ = _mock_connection(rows=[{"job_id": JOB_ID}])

    with (
        patch("store.psycopg.connect", return_value=connection),
        pytest.raises(store.RunHistoryUnavailable, match="authoritative run history"),
    ):
        store.fetch_runs()
