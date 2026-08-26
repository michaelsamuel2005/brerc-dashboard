"""Private liveness, readiness and Prometheus metrics endpoint."""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_STATUSES = frozenset(
    {"pending", "delivering", "delivery_failed", "delivered", "dead_letter"}
)
_EVENT_TYPES = frozenset({"etl_succeeded", "etl_failed"})


class MetricsState:
    """Thread-safe, low-cardinality process and outbox metrics."""

    def __init__(self, *, readiness_stale_seconds: int) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._readiness_stale_seconds = readiness_stale_seconds
        self._last_db_success: float | None = None
        self._counters = {
            "polls": 0,
            "database_failures": 0,
            "claimed": 0,
            "delivered": 0,
            "retry_scheduled": 0,
            "dead_lettered": 0,
            "lease_lost": 0,
            "lease_renewal_failures": 0,
            "provider_preflight_failures": 0,
        }
        self._gauges: dict[str, float] = {
            "outbox_ready": 0,
            "outbox_delivering": 0,
            "outbox_delivered": 0,
            "outbox_dead_letter": 0,
            "outbox_total_attempts": 0,
            "outbox_redrives": 0,
            "oldest_ready_age_seconds": 0,
            "provider_preflight_ok": 0,
        }

    def note_db_success(self) -> None:
        with self._lock:
            self._last_db_success = time.monotonic()

    def note_db_failure(self) -> None:
        with self._lock:
            self._counters["database_failures"] += 1
            self._last_db_success = None

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self._counters or amount < 0:
            raise ValueError("metric counter is invalid")
        with self._lock:
            self._counters[name] += amount

    def note_provider_preflight(self, successful: bool) -> None:
        with self._lock:
            self._gauges["provider_preflight_ok"] = 1 if successful else 0
            if not successful:
                self._counters["provider_preflight_failures"] += 1

    def update_delivery_rows(self, rows: Sequence[Mapping[str, object]]) -> None:
        totals = {
            "outbox_ready": 0.0,
            "outbox_delivering": 0.0,
            "outbox_delivered": 0.0,
            "outbox_dead_letter": 0.0,
            "outbox_total_attempts": 0.0,
            "outbox_redrives": 0.0,
            "oldest_ready_age_seconds": 0.0,
        }
        now = datetime.now(timezone.utc)
        for row in rows:
            event_type = row.get("event_type")
            status = row.get("status")
            count = row.get("notification_count")
            attempts = row.get("total_attempt_count")
            redrives = row.get("redrive_count")
            if (
                event_type not in _EVENT_TYPES
                or status not in _STATUSES
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                or isinstance(attempts, bool)
                or not isinstance(attempts, int)
                or attempts < 0
                or isinstance(redrives, bool)
                or not isinstance(redrives, int)
                or redrives < 0
            ):
                raise ValueError("database metric row is invalid")
            if status in {"pending", "delivery_failed"}:
                totals["outbox_ready"] += count
                oldest = row.get("oldest_ready_at")
                if oldest is not None:
                    if not isinstance(oldest, datetime) or oldest.tzinfo is None:
                        raise ValueError("database metric timestamp is invalid")
                    totals["oldest_ready_age_seconds"] = max(
                        totals["oldest_ready_age_seconds"], max(0.0, (now - oldest).total_seconds())
                    )
            elif status == "delivering":
                totals["outbox_delivering"] += count
            elif status == "delivered":
                totals["outbox_delivered"] += count
            elif status == "dead_letter":
                totals["outbox_dead_letter"] += count
            totals["outbox_total_attempts"] += float(attempts)
            totals["outbox_redrives"] += float(redrives)
        with self._lock:
            self._gauges.update(totals)

    def ready(self) -> bool:
        with self._lock:
            last = self._last_db_success
            return last is not None and time.monotonic() - last <= self._readiness_stale_seconds

    def render(self) -> str:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            last = self._last_db_success
        ready = 1 if last is not None and time.monotonic() - last <= self._readiness_stale_seconds else 0
        lines = [
            "# HELP brerc_notifier_ready Whether a recent database poll succeeded.",
            "# TYPE brerc_notifier_ready gauge",
            f"brerc_notifier_ready {ready}",
            "# HELP brerc_notifier_uptime_seconds Worker process uptime.",
            "# TYPE brerc_notifier_uptime_seconds gauge",
            f"brerc_notifier_uptime_seconds {max(0.0, time.monotonic() - self._started):.3f}",
        ]
        for name, value in counters.items():
            metric = f"brerc_notifier_{name}_total"
            lines.extend((f"# TYPE {metric} counter", f"{metric} {value}"))
        for name, value in gauges.items():
            if not math.isfinite(value) or value < 0:
                value = 0
            metric = f"brerc_notifier_{name}"
            lines.extend((f"# TYPE {metric} gauge", f"{metric} {value:g}"))
        return "\n".join(lines) + "\n"


class _HealthHandler(BaseHTTPRequestHandler):
    state: MetricsState

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/live":
            self._json(200, {"status": "live"})
            return
        if self.path == "/ready":
            ready = self.state.ready()
            self._json(200 if ready else 503, {"status": "ready" if ready else "not_ready"})
            return
        if self.path == "/metrics":
            body = self.state.render().encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"status": "not_found"})

    def _json(self, status: int, document: Mapping[str, str]) -> None:
        body = json.dumps(document, separators=(",", ":")).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        # Request lines contain client addresses and must not enter worker logs.
        return


class _PrivateHealthServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, _request: object, _client_address: object) -> None:
        """Suppress BaseServer's client-address/traceback error output."""

        return


class HealthServer:
    def __init__(self, host: str, port: int, state: MetricsState) -> None:
        handler = type("NotifierHealthHandler", (_HealthHandler,), {"state": state})
        self._server = _PrivateHealthServer((host, port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="notifier-health",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
