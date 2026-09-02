"""Authenticated HTTP boundary for the internal run-history viewer."""

from __future__ import annotations

import runpy
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app
from store import RunHistoryUnavailable


def _client() -> TestClient:
    return TestClient(app.app)


def test_runs_endpoint_requires_authentication():
    response = _client().get("/api/runs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"


def test_authenticated_runs_endpoint_returns_authoritative_rows():
    expected = [{"job_id": "synthetic", "load_mode": "refresh", "status": "successful"}]
    with _client() as client:
        login = client.post(
            "/login",
            data={
                "username": "synthetic-operator",
                "password": "synthetic-dashboard-password",
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        with patch("app.fetch_runs", return_value=expected):
            response = client.get("/api/runs")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["cache-control"] == "no-store, max-age=0"


def test_database_failure_is_redacted_and_fails_closed():
    with _client() as client:
        client.post(
            "/login",
            data={
                "username": "synthetic-operator",
                "password": "synthetic-dashboard-password",
            },
        )
        with patch(
            "app.fetch_runs",
            side_effect=RunHistoryUnavailable(
                "postgresql://secret@example.invalid/source-row"
            ),
        ):
            response = client.get("/api/runs")

    assert response.status_code == 503
    assert response.json() == {"detail": "Authoritative ETL run history is unavailable"}
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert "secret" not in response.text
    assert "source-row" not in response.text


def test_index_login_and_logout_are_not_cacheable():
    with _client() as client:
        login_page = client.get("/login")
        login = client.post(
            "/login",
            data={
                "username": "synthetic-operator",
                "password": "synthetic-dashboard-password",
            },
            follow_redirects=False,
        )
        index = client.get("/")
        logout = client.get("/logout", follow_redirects=False)

    for response in (login_page, login, index, logout):
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["pragma"] == "no-cache"


def test_production_login_cookie_is_secure_and_uses_a_persistent_key(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ENV", "prod")
    monkeypatch.setenv("DASHBOARD_USERNAME", "production-operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "production-dashboard-password")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "a" * 64)

    production_module = runpy.run_path(str(app.STATIC_DIR.parent / "app.py"))
    with TestClient(production_module["app"], base_url="https://testserver") as client:
        response = client.post(
            "/login",
            data={
                "username": "production-operator",
                "password": "production-dashboard-password",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "secure" in response.headers["set-cookie"].lower()
    assert response.headers["cache-control"] == "no-store, max-age=0"


def test_production_refuses_an_ephemeral_session_key(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ENV", "prod")
    monkeypatch.setenv("DASHBOARD_USERNAME", "production-operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "production-dashboard-password")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="persistent DASHBOARD_SECRET_KEY"):
        runpy.run_path(str(app.STATIC_DIR.parent / "app.py"))
