from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from brerc_notifier.metrics import HealthServer, MetricsState, _PrivateHealthServer


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=2) as response:  # noqa: S310 - fixed loopback test URL
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def test_private_health_endpoints_track_database_readiness() -> None:
    state = MetricsState(readiness_stale_seconds=60)
    server = HealthServer("127.0.0.1", 0, state)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        status, body = _get(base + "/live")
        assert status == 200
        assert json.loads(body) == {"status": "live"}

        status, body = _get(base + "/ready")
        assert status == 503
        assert json.loads(body) == {"status": "not_ready"}

        state.note_db_success()
        status, body = _get(base + "/ready")
        assert status == 200
        assert json.loads(body) == {"status": "ready"}

        status, body = _get(base + "/metrics")
        assert status == 200
        assert b"brerc_notifier_ready 1" in body
    finally:
        server.close()


def test_readiness_expires_after_configured_database_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr("brerc_notifier.metrics.time.monotonic", lambda: clock[0])
    state = MetricsState(readiness_stale_seconds=60)
    state.note_db_success()
    assert state.ready()
    clock[0] = 161.0
    assert not state.ready()


def test_database_failure_immediately_invalidates_readiness() -> None:
    state = MetricsState(readiness_stale_seconds=60)
    state.note_db_success()
    assert state.ready()
    state.note_db_failure()
    assert not state.ready()


def test_health_server_error_hook_never_emits_client_address_or_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _PrivateHealthServer.handle_error(object(), object(), ("private-client", 1234))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_metrics_aggregate_fixed_states_without_identifiers_or_alias_labels() -> None:
    state = MetricsState(readiness_stale_seconds=60)
    now = datetime.now(timezone.utc)
    state.update_delivery_rows(
        [
            {
                "event_type": "etl_failed",
                "status": "delivery_failed",
                "notification_count": 2,
                "total_attempt_count": 4,
                "redrive_count": 1,
                "oldest_created_at": now - timedelta(minutes=10),
                "oldest_ready_at": now - timedelta(minutes=5),
                "latest_delivered_at": None,
                "latest_dead_lettered_at": None,
            },
            {
                "event_type": "etl_succeeded",
                "status": "delivered",
                "notification_count": 3,
                "total_attempt_count": 3,
                "redrive_count": 0,
                "oldest_created_at": now - timedelta(hours=1),
                "oldest_ready_at": None,
                "latest_delivered_at": now,
                "latest_dead_lettered_at": None,
            },
        ]
    )
    state.increment("delivered", 3)
    rendered = state.render()
    assert "brerc_notifier_outbox_ready 2" in rendered
    assert "brerc_notifier_outbox_delivered 3" in rendered
    assert "brerc_notifier_outbox_total_attempts 7" in rendered
    assert "brerc_notifier_outbox_redrives 1" in rendered
    assert "brerc_notifier_delivered_total 3" in rendered
    assert "etl_failed" not in rendered
    assert "etl-operations" not in rendered
    assert "notification_id" not in rendered
    assert "operator@example.org" not in rendered


def test_metrics_reject_unknown_database_vocabulary() -> None:
    state = MetricsState(readiness_stale_seconds=60)
    with pytest.raises(ValueError):
        state.update_delivery_rows(
            [
                {
                    "event_type": "arbitrary_event",
                    "status": "pending",
                    "notification_count": 1,
                    "total_attempt_count": 1,
                    "redrive_count": 0,
                }
            ]
        )


def test_runbook_alert_names_match_rendered_provider_metrics() -> None:
    state = MetricsState(readiness_stale_seconds=60)
    state.note_provider_preflight(False)
    rendered = state.render()
    runbook = (
        Path(__file__).resolve().parents[2] / "docs" / "NOTIFICATION_WORKER.md"
    ).read_text(encoding="utf-8")

    for metric in (
        "brerc_notifier_provider_preflight_ok",
        "brerc_notifier_provider_preflight_failures_total",
    ):
        assert metric in rendered
        assert metric in runbook
    assert "brerc_notifier_provider_ready" not in runbook
