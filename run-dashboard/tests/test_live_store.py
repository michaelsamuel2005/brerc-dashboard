"""Opt-in real PostgreSQL acceptance for the authoritative monitor reader."""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

import app
import store


@pytest.mark.skipif(
    os.environ.get("BRERC_RUN_DASHBOARD_INTEGRATION") != "1",
    reason="requires the disposable PostgreSQL/PostGIS CI destination",
)
def test_monitor_reader_observes_the_successful_atomic_refresh():
    runs = store.fetch_runs()

    assert runs
    refreshes = [run for run in runs if run["load_mode"] == "refresh"]
    assert refreshes
    assert refreshes[0]["status"] == "successful"
    assert refreshes[0]["lifecycle_status"] == "succeeded"
    assert refreshes[0]["source_rows_seen"] == 2
    assert refreshes[0]["candidate_rows"] == 1
    assert refreshes[0]["rows_withheld"] == 1


@pytest.mark.skipif(
    os.environ.get("BRERC_RUN_DASHBOARD_INTEGRATION") != "1",
    reason="requires the disposable PostgreSQL/PostGIS CI destination",
)
def test_authenticated_http_endpoint_observes_live_refresh_and_logout_closes_it():
    with TestClient(app.app) as client:
        login = client.post(
            "/login",
            data={
                "username": os.environ["DASHBOARD_USERNAME"],
                "password": os.environ["DASHBOARD_PASSWORD"],
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        response = client.get("/api/runs")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, max-age=0"
        refreshes = [run for run in response.json() if run["load_mode"] == "refresh"]
        assert refreshes[0]["source_rows_seen"] == 2
        assert refreshes[0]["candidate_rows"] == 1
        assert refreshes[0]["rows_withheld"] == 1

        logout = client.get("/logout", follow_redirects=False)
        assert logout.status_code == 307
        denied = client.get("/api/runs")
        assert denied.status_code == 401
        assert denied.headers["cache-control"] == "no-store, max-age=0"


@pytest.mark.skipif(
    os.environ.get("BRERC_RUN_DASHBOARD_INTEGRATION") != "1",
    reason="requires the disposable PostgreSQL/PostGIS CI destination",
)
def test_monitor_reader_rejects_an_unrelated_powerful_role_grant():
    admin_url = os.environ["BRERC_RUN_DASHBOARD_ADMIN_URL"]
    monitor_role = os.environ["RUN_DASHBOARD_EXPECTED_ROLE"]
    grant = sql.SQL("GRANT pg_read_all_data TO {}").format(sql.Identifier(monitor_role))
    revoke = sql.SQL("REVOKE pg_read_all_data FROM {}").format(
        sql.Identifier(monitor_role)
    )

    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(grant)
        try:
            with pytest.raises(store.RunHistoryUnavailable, match="privileges"):
                store.fetch_runs()
        finally:
            admin.execute(revoke)
