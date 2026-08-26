"""Transactional outbox polling and delivery orchestration."""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import TextIO
from uuid import UUID

from .config import NotifierConfig
from .database import NotificationGateway
from .errors import NotificationClaimLost
from .metrics import MetricsState
from .models import DeliveryFailure, DeliveryResult
from .providers import NotificationProvider, build_provider


def safe_log(stream: TextIO, event_code: str, **numbers: int) -> None:
    """Write one fixed-code JSON event with numeric context only."""

    if not event_code.isascii() or not event_code.replace("_", "").isupper():
        raise ValueError("log event code is invalid")
    document: dict[str, str | int] = {"eventCode": event_code}
    for key, value in numbers.items():
        if (
            not key.isascii()
            or not key.replace("_", "").islower()
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ValueError("log metric is invalid")
        document[key] = value
    stream.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


@dataclass(frozen=True)
class PollOutcome:
    claimed: int = 0
    delivered: int = 0
    retry_scheduled: int = 0
    dead_lettered: int = 0
    lease_lost: int = 0


class _LeaseRenewer:
    """Keep one committed claim alive while bounded external I/O is in flight."""

    def __init__(
        self,
        gateway: NotificationGateway,
        notification_id: UUID,
        claim_token: UUID,
        lease_seconds: int,
        *,
        interval_seconds: float | None = None,
        join_timeout_seconds: float | None = None,
    ) -> None:
        self._gateway = gateway
        self._notification_id = notification_id
        self._claim_token = claim_token
        self._lease_seconds = lease_seconds
        self._interval = interval_seconds or max(1.0, lease_seconds / 4)
        self._join_timeout = join_timeout_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="notifier-lease-renewer",
            daemon=True,
        )
        self.failed = False

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                renewed = self._gateway.renew(
                    self._notification_id,
                    self._claim_token,
                    self._lease_seconds,
                )
            except Exception:
                self.failed = True
                return
            if not renewed:
                self.failed = True
                return

    def __enter__(self) -> _LeaseRenewer:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self._join_timeout)
        if self._thread.is_alive():
            self.failed = True


class NotificationWorker:
    """Deliver at least once with a stable provider idempotency identity.

    There is no atomic transaction spanning PostgreSQL and SMTP/HTTPS.  If a
    provider accepts a message and the process dies before ``ack_notification``
    commits, the message can be sent again.  The UUID Idempotency-Key and stable
    SMTP Message-ID let a capable receiver collapse that duplicate; the worker
    never claims exactly-once delivery.
    """

    def __init__(
        self,
        config: NotifierConfig,
        gateway: NotificationGateway,
        metrics: MetricsState,
        *,
        providers: dict[str, NotificationProvider] | None = None,
        log_stream: TextIO = sys.stdout,
        lease_renewal_interval_seconds: float | None = None,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._metrics = metrics
        self._log = log_stream
        self._lease_renewal_interval_seconds = lease_renewal_interval_seconds
        self._lease_renewal_join_timeout_seconds = (
            config.database.connect_timeout_seconds
            + (config.database.statement_timeout_ms + 999) / 1000
            + 1
        )
        self._providers = providers or {
            key: build_provider(
                destination,
                timeout_seconds=config.runtime.delivery_timeout_seconds,
            )
            for key, destination in config.destinations.items()
        }

    def preflight_providers(self) -> bool:
        successful = set(self._providers) == set(self._config.destinations)
        for provider in self._providers.values():
            try:
                successful = provider.preflight().delivered and successful
            except Exception:
                successful = False
        self._metrics.note_provider_preflight(successful)
        safe_log(
            self._log,
            "NOTIFIER_PROVIDER_PREFLIGHT_OK"
            if successful
            else "NOTIFIER_PROVIDER_PREFLIGHT_FAILED",
        )
        return successful

    def poll_once(self) -> PollOutcome:
        runtime = self._config.runtime
        try:
            self._gateway.preflight()
            claimed = self._gateway.claim(runtime.batch_size, runtime.lease_seconds)
            self._metrics.note_db_success()
            self._metrics.increment("polls")
            self._metrics.increment("claimed", len(claimed))
        except Exception:
            self._metrics.note_db_failure()
            safe_log(self._log, "NOTIFIER_DATABASE_UNAVAILABLE")
            raise

        delivered = retry_scheduled = dead_lettered = lease_lost = 0
        for notification in claimed:
            provider = self._providers.get(notification.destination_key)
            if provider is None:
                result = DeliveryResult.failed(DeliveryFailure.CONFIGURATION_INVALID)
            else:
                with _LeaseRenewer(
                    self._gateway,
                    notification.notification_id,
                    notification.claim_token,
                    runtime.lease_seconds,
                    interval_seconds=self._lease_renewal_interval_seconds,
                    join_timeout_seconds=self._lease_renewal_join_timeout_seconds,
                ) as lease_renewer:
                    try:
                        result = provider.deliver(notification)
                    except Exception:
                        result = DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
                if lease_renewer.failed:
                    self._metrics.note_db_failure()
                    self._metrics.increment("lease_renewal_failures")
                    safe_log(self._log, "NOTIFICATION_LEASE_RENEWAL_FAILED")

            try:
                if result.delivered:
                    if self._gateway.acknowledge(
                        notification.notification_id, notification.claim_token
                    ):
                        delivered += 1
                        self._metrics.increment("delivered")
                        safe_log(self._log, "NOTIFICATION_DELIVERED")
                    else:
                        lease_lost += 1
                        self._metrics.increment("lease_lost")
                        safe_log(self._log, "NOTIFICATION_LEASE_LOST")
                    continue

                if result.failure is None:
                    result = DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
                disposition = self._gateway.fail(
                    notification.notification_id,
                    notification.claim_token,
                    result.failure,
                    result.retry_after_seconds,
                )
                if disposition == "delivery_failed":
                    retry_scheduled += 1
                    self._metrics.increment("retry_scheduled")
                    safe_log(self._log, "NOTIFICATION_RETRY_SCHEDULED")
                else:
                    dead_lettered += 1
                    self._metrics.increment("dead_lettered")
                    safe_log(self._log, "NOTIFICATION_DEAD_LETTERED")
            except NotificationClaimLost:
                lease_lost += 1
                self._metrics.increment("lease_lost")
                safe_log(self._log, "NOTIFICATION_LEASE_LOST")
            except Exception:
                self._metrics.note_db_failure()
                safe_log(self._log, "NOTIFIER_DATABASE_UNAVAILABLE")
                raise

        try:
            self._metrics.update_delivery_rows(self._gateway.delivery_metrics())
            self._metrics.note_db_success()
        except Exception:
            self._metrics.note_db_failure()
            safe_log(self._log, "NOTIFIER_METRICS_UNAVAILABLE")
            raise

        outcome = PollOutcome(
            claimed=len(claimed),
            delivered=delivered,
            retry_scheduled=retry_scheduled,
            dead_lettered=dead_lettered,
            lease_lost=lease_lost,
        )
        safe_log(
            self._log,
            "NOTIFIER_POLL_COMPLETED",
            claimed=outcome.claimed,
            delivered=outcome.delivered,
            retry_scheduled=outcome.retry_scheduled,
            dead_lettered=outcome.dead_lettered,
            lease_lost=outcome.lease_lost,
        )
        return outcome

    def run(self, stop: threading.Event) -> None:
        """Poll immediately, then wait interruptibly between polls."""

        next_provider_probe = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_provider_probe:
                self.preflight_providers()
                next_provider_probe = now + self._config.runtime.provider_probe_interval_seconds
            try:
                self.poll_once()
            except Exception:
                # The database lease makes a claimed message recoverable after
                # every process failure.  Keep serving /live while /ready goes
                # false; Docker may restart us and the external monitor alerts.
                pass
            stop.wait(self._config.runtime.poll_interval_seconds)
        safe_log(self._log, "NOTIFIER_STOPPED")
