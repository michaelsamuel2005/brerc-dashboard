from __future__ import annotations

import io
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from brerc_notifier.config import (
    DatabaseConfig,
    NotifierConfig,
    RuntimeConfig,
    SmtpDestination,
)
from brerc_notifier.cli import preflight_providers
from brerc_notifier.database import PostgresNotificationGateway
from brerc_notifier.errors import NotifierProtocolError, NotifierProviderPreflightError
from brerc_notifier.metrics import MetricsState
from brerc_notifier.models import ClaimedNotification, DeliveryFailure, DeliveryResult
from brerc_notifier.worker import NotificationWorker


def _notification() -> ClaimedNotification:
    return ClaimedNotification(
        notification_id=UUID("11111111-1111-4111-8111-111111111111"),
        claim_token=UUID("22222222-2222-4222-8222-222222222222"),
        delivery_cycle=1,
        cycle_attempt=1,
        total_attempt_count=1,
        job_id=UUID("33333333-3333-4333-8333-333333333333"),
        release_id=UUID("44444444-4444-4444-8444-444444444444"),
        event_type="etl_succeeded",
        destination_key="etl-operations",
        failure_code=None,
        load_mode="initial",
        finished_at=datetime(2026, 8, 26, 12, 30, tzinfo=timezone.utc),
    )


def _config(tmp_path: Path) -> NotifierConfig:
    return NotifierConfig(
        version="brerc-notifier-v1",
        database=DatabaseConfig(
            expected_database="brerc_publication",
            expected_login="brerc_notifier_service",
            expected_role="brerc_notifier",
            expected_migration_version=2,
            connect_timeout_seconds=10,
            statement_timeout_ms=5000,
            _service="notify",
            _service_file=tmp_path / "service",
            _passfile=tmp_path / "passfile",
            _sslrootcert=tmp_path / "ca",
        ),
        runtime=RuntimeConfig(
            batch_size=1,
            lease_seconds=120,
            poll_interval_seconds=1,
            delivery_timeout_seconds=15,
            provider_probe_interval_seconds=300,
            readiness_stale_seconds=60,
            health_host="127.0.0.1",
            health_port=9108,
        ),
        destinations={
            "etl-operations": SmtpDestination(
                "smtp",
                "smtp.example.org",
                465,
                "dashboard@example.org",
                ("operator@example.org",),
                "private-user",
                "private-password",
            )
        },
    )


class _Gateway:
    def __init__(self, notification: ClaimedNotification, disposition: str = "delivery_failed"):
        self.notification = notification
        self.disposition = disposition
        self.events: list[object] = []
        self.acknowledged = True
        self.renewed = True
        self.renew_called = threading.Event()

    def preflight(self) -> None:
        self.events.append("preflight")

    def claim(self, limit: int, lease_seconds: int) -> list[ClaimedNotification]:
        self.events.append(("claim", limit, lease_seconds))
        return [self.notification]

    def renew(self, notification_id: UUID, claim_token: UUID, lease_seconds: int) -> bool:
        self.events.append(("renew", notification_id, claim_token, lease_seconds))
        self.renew_called.set()
        return self.renewed

    def acknowledge(self, notification_id: UUID, claim_token: UUID) -> bool:
        self.events.append(("ack", notification_id, claim_token))
        return self.acknowledged

    def fail(
        self,
        notification_id: UUID,
        claim_token: UUID,
        code: DeliveryFailure,
        retry_after_seconds: int | None,
    ) -> str:
        self.events.append(("fail", notification_id, claim_token, code, retry_after_seconds))
        return self.disposition

    def delivery_metrics(self) -> list[dict[str, object]]:
        self.events.append("metrics")
        return []


class _Provider:
    def __init__(self, result: DeliveryResult | Exception, events: list[object]) -> None:
        self.result = result
        self.events = events

    def deliver(self, notification: ClaimedNotification) -> DeliveryResult:
        self.events.append(("deliver", notification.notification_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def preflight(self) -> DeliveryResult:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _worker(
    tmp_path: Path,
    gateway: _Gateway,
    result: DeliveryResult | Exception,
) -> tuple[NotificationWorker, MetricsState, io.StringIO]:
    metrics = MetricsState(readiness_stale_seconds=60)
    log = io.StringIO()
    provider = _Provider(result, gateway.events)
    worker = NotificationWorker(
        _config(tmp_path),
        gateway,
        metrics,
        providers={"etl-operations": provider},
        log_stream=log,
    )
    return worker, metrics, log


def test_claim_commits_before_provider_and_acknowledges_success(tmp_path: Path) -> None:
    gateway = _Gateway(_notification())
    worker, metrics, log = _worker(tmp_path, gateway, DeliveryResult.success())

    outcome = worker.poll_once()

    assert outcome.delivered == 1
    assert gateway.events[:4] == [
        "preflight",
        ("claim", 1, 120),
        ("deliver", _notification().notification_id),
        ("ack", _notification().notification_id, _notification().claim_token),
    ]
    assert gateway.events[-1] == "metrics"
    assert metrics.ready()
    assert "NOTIFICATION_DELIVERED" in log.getvalue()


def test_transient_failure_is_rescheduled_with_bounded_provider_delay(tmp_path: Path) -> None:
    gateway = _Gateway(_notification(), "delivery_failed")
    worker, _, log = _worker(
        tmp_path,
        gateway,
        DeliveryResult.failed(DeliveryFailure.RATE_LIMITED, 30),
    )

    outcome = worker.poll_once()

    assert outcome.retry_scheduled == 1
    failure = next(event for event in gateway.events if isinstance(event, tuple) and event[0] == "fail")
    assert failure[3:] == (DeliveryFailure.RATE_LIMITED, 30)
    assert "NOTIFICATION_RETRY_SCHEDULED" in log.getvalue()


def test_permanent_or_exhausted_failure_enters_dead_letter(tmp_path: Path) -> None:
    gateway = _Gateway(_notification(), "dead_letter")
    worker, _, _ = _worker(
        tmp_path,
        gateway,
        DeliveryResult.failed(DeliveryFailure.AUTHENTICATION_FAILED),
    )
    outcome = worker.poll_once()
    assert outcome.dead_lettered == 1


def test_unexpected_provider_exception_is_sanitised_to_fixed_failure(tmp_path: Path) -> None:
    gateway = _Gateway(_notification())
    worker, _, log = _worker(tmp_path, gateway, RuntimeError("private token and recipient"))
    worker.poll_once()
    failure = next(event for event in gateway.events if isinstance(event, tuple) and event[0] == "fail")
    assert failure[3] is DeliveryFailure.PROVIDER_UNAVAILABLE
    assert "private token" not in log.getvalue()
    assert "operator@example.org" not in log.getvalue()
    assert str(_notification().notification_id) not in log.getvalue()


def test_lost_ack_is_reported_without_marking_delivered(tmp_path: Path) -> None:
    gateway = _Gateway(_notification())
    gateway.acknowledged = False
    worker, _, _ = _worker(tmp_path, gateway, DeliveryResult.success())
    outcome = worker.poll_once()
    assert outcome.delivered == 0
    assert outcome.lease_lost == 1


class _BlockingProvider(_Provider):
    def __init__(self, release: threading.Event, events: list[object]) -> None:
        super().__init__(DeliveryResult.success(), events)
        self.started = threading.Event()
        self.release = release

    def deliver(self, notification: ClaimedNotification) -> DeliveryResult:
        self.events.append(("deliver", notification.notification_id))
        self.started.set()
        if not self.release.wait(2):
            raise TimeoutError
        return DeliveryResult.success()


def test_blocking_delivery_renews_exact_claim_and_stops_before_ack(tmp_path: Path) -> None:
    gateway = _Gateway(_notification())
    release = threading.Event()
    provider = _BlockingProvider(release, gateway.events)
    metrics = MetricsState(readiness_stale_seconds=60)
    log = io.StringIO()
    worker = NotificationWorker(
        _config(tmp_path),
        gateway,
        metrics,
        providers={"etl-operations": provider},
        log_stream=log,
        lease_renewal_interval_seconds=0.01,
    )
    outcomes: list[object] = []

    thread = threading.Thread(target=lambda: outcomes.append(worker.poll_once()))
    thread.start()
    assert provider.started.wait(1)
    assert gateway.renew_called.wait(1)
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert outcomes and getattr(outcomes[0], "delivered") == 1
    renewal = next(
        event
        for event in gateway.events
        if isinstance(event, tuple) and event[0] == "renew"
    )
    assert renewal == (
        "renew",
        _notification().notification_id,
        _notification().claim_token,
        120,
    )
    acknowledgement_index = next(
        index
        for index, event in enumerate(gateway.events)
        if isinstance(event, tuple) and event[0] == "ack"
    )
    assert gateway.events.index(renewal) < acknowledgement_index


def test_renewal_failure_is_fixed_code_and_counted(tmp_path: Path) -> None:
    gateway = _Gateway(_notification())
    gateway.renewed = False
    release = threading.Event()
    provider = _BlockingProvider(release, gateway.events)
    metrics = MetricsState(readiness_stale_seconds=60)
    log = io.StringIO()
    worker = NotificationWorker(
        _config(tmp_path),
        gateway,
        metrics,
        providers={"etl-operations": provider},
        log_stream=log,
        lease_renewal_interval_seconds=0.01,
    )
    errors: list[BaseException] = []

    def poll() -> None:
        try:
            worker.poll_once()
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    thread = threading.Thread(target=poll)
    thread.start()
    assert gateway.renew_called.wait(1)
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors == []
    assert "NOTIFICATION_LEASE_RENEWAL_FAILED" in log.getvalue()
    assert "brerc_notifier_lease_renewal_failures_total 1" in metrics.render()


def test_provider_probe_checks_every_destination_without_sending(tmp_path: Path) -> None:
    events: list[object] = []
    provider = _Provider(DeliveryResult.success(), events)
    preflight_providers(_config(tmp_path), providers={"etl-operations": provider})
    assert events == []

    failed = _Provider(
        DeliveryResult.failed(DeliveryFailure.AUTHENTICATION_FAILED),
        events,
    )
    with pytest.raises(NotifierProviderPreflightError) as rejected:
        preflight_providers(_config(tmp_path), providers={"etl-operations": failed})
    assert str(rejected.value) == "NOTIFIER_PROVIDER_PREFLIGHT_FAILED"
    assert "operator@example.org" not in str(rejected.value)


def test_long_lived_worker_provider_probe_updates_fixed_metric(tmp_path: Path) -> None:
    gateway = _Gateway(_notification())
    worker, metrics, log = _worker(tmp_path, gateway, DeliveryResult.success())
    assert worker.preflight_providers()
    assert "brerc_notifier_provider_preflight_ok 1" in metrics.render()

    failed = _Provider(
        DeliveryResult.failed(DeliveryFailure.AUTHENTICATION_FAILED),
        gateway.events,
    )
    worker = NotificationWorker(
        _config(tmp_path),
        gateway,
        metrics,
        providers={"etl-operations": failed},
        log_stream=log,
    )
    assert not worker.preflight_providers()
    rendered = metrics.render()
    assert "brerc_notifier_provider_preflight_ok 0" in rendered
    assert "brerc_notifier_provider_preflight_failures_total 1" in rendered
    assert "operator@example.org" not in log.getvalue()


class _Cursor:
    def __init__(self, scripted_rows: list[list[dict[str, object]]], statements: list[str]) -> None:
        self._scripted_rows = scripted_rows
        self._statements = statements
        self._current: list[dict[str, object]] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, _parameters: object) -> None:
        self._statements.append(statement)
        self._current = self._scripted_rows.pop(0)

    def fetchall(self) -> list[dict[str, object]]:
        return self._current


class _Connection:
    def __init__(self, scripted_rows: list[list[dict[str, object]]], statements: list[str]) -> None:
        self._scripted_rows = scripted_rows
        self._statements = statements

    def cursor(self) -> _Cursor:
        return _Cursor(self._scripted_rows, self._statements)

    def close(self) -> None:
        return None


def test_database_gateway_uses_only_reviewed_functions_and_validates_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path).database
    monkeypatch.setenv("PGSERVICEFILE", str(config._service_file))
    statements: list[str] = []
    rows = [
        [
            {
                "database_name": "brerc_publication",
                "session_user_name": "brerc_notifier_service",
                "ssl": True,
                "server_version_num": 160012,
                "ssl_version": "TLSv1.3",
                "migration_version": 2,
                "migration_key": "0002_notification_delivery",
                "notifier_membership_only": True,
            }
        ],
        [
            {
                "notification_id": _notification().notification_id,
                "claim_token": _notification().claim_token,
                "delivery_cycle": 1,
                "cycle_attempt": 1,
                "total_attempt_count": 1,
                "job_id": _notification().job_id,
                "release_id": _notification().release_id,
                "event_type": "etl_succeeded",
                "destination_key": "etl-operations",
                "failure_code": None,
                "load_mode": "initial",
                "finished_at": _notification().finished_at,
            }
        ],
        [{"acknowledged": True}],
        [{"disposition": "delivery_failed"}],
    ]

    def factory(**_kwargs: object) -> _Connection:
        return _Connection(rows, statements)

    gateway = PostgresNotificationGateway(config, connection_factory=factory)
    gateway.preflight()
    claimed = gateway.claim(10, 120)
    assert claimed == [_notification()]
    assert gateway.acknowledge(claimed[0].notification_id, claimed[0].claim_token)
    assert gateway.fail(
        claimed[0].notification_id,
        claimed[0].claim_token,
        DeliveryFailure.CONNECTION_FAILED,
        None,
    ) == "delivery_failed"
    assert all("UPDATE " not in statement.upper() for statement in statements)
    assert any("serve.notification_worker_preflight" in statement for statement in statements)
    assert any("loader_control.claim_notifications" in statement for statement in statements)
    assert any("loader_control.ack_notification" in statement for statement in statements)
    assert any("loader_control.fail_notification" in statement for statement in statements)


def test_database_gateway_rejects_unknown_failure_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path).database
    monkeypatch.setenv("PGSERVICEFILE", str(config._service_file))

    def factory(**_kwargs: object) -> _Connection:
        return _Connection([[{"disposition": "invented"}]], [])

    gateway = PostgresNotificationGateway(config, connection_factory=factory)
    with pytest.raises(NotifierProtocolError):
        gateway.fail(
            _notification().notification_id,
            _notification().claim_token,
            DeliveryFailure.CONNECTION_FAILED,
            None,
        )
