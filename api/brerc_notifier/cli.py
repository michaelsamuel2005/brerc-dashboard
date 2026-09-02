"""Operator CLI: validate, probe, once and run."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from .config import load_config
from .database import PostgresNotificationGateway
from .errors import (
    NotifierConfigurationError,
    NotifierError,
    NotifierProviderPreflightError,
)
from .metrics import HealthServer, MetricsState
from .providers import NotificationProvider, build_provider
from .worker import NotificationWorker


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, '{"code":"NOTIFIER_CLI_USAGE_INVALID"}\n')


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="brerc-notifier")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "probe", "check", "once", "run"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True, type=Path)
    return parser


def _print(stream: object, code: str, **counts: int) -> None:
    document: dict[str, str | int] = {"code": code}
    document.update(counts)
    print(json.dumps(document, sort_keys=True, separators=(",", ":")), file=stream)


def preflight_providers(
    config: object,
    *,
    providers: dict[str, NotificationProvider] | None = None,
) -> None:
    """Probe every provider without sending and expose only one fixed failure."""

    try:
        destinations = config.destinations  # type: ignore[attr-defined]
        timeout = config.runtime.delivery_timeout_seconds  # type: ignore[attr-defined]
        registry = (
            providers
            if providers is not None
            else {
                key: build_provider(destination, timeout_seconds=timeout)
                for key, destination in destinations.items()
            }
        )
        failed = False
        for provider in registry.values():
            try:
                if not provider.preflight().delivered:
                    failed = True
            except Exception:
                failed = True
        if failed or set(registry) != set(destinations):
            raise NotifierProviderPreflightError()
    except NotifierProviderPreflightError:
        raise
    except Exception:
        raise NotifierProviderPreflightError() from None


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        config = load_config(args.config)
        if args.command == "validate":
            _print(sys.stdout, "NOTIFIER_CONFIGURATION_VALID")
            return 0

        gateway = PostgresNotificationGateway(config.database)
        if args.command in {"probe", "check"}:
            gateway.preflight()
            gateway.delivery_metrics()
            preflight_providers(config)
            _print(sys.stdout, "NOTIFIER_PROBE_OK")
            return 0

        metrics = MetricsState(readiness_stale_seconds=config.runtime.readiness_stale_seconds)
        worker = NotificationWorker(config, gateway, metrics)
        if args.command == "once":
            outcome = worker.poll_once()
            _print(
                sys.stdout,
                "NOTIFIER_ONCE_COMPLETED",
                claimed=outcome.claimed,
                delivered=outcome.delivered,
                retry_scheduled=outcome.retry_scheduled,
                dead_lettered=outcome.dead_lettered,
                lease_lost=outcome.lease_lost,
            )
            return 0

        stop = threading.Event()

        def request_stop(_signum: int, _frame: object) -> None:
            stop.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        server = HealthServer(
            config.runtime.health_host,
            config.runtime.health_port,
            metrics,
        )
        server.start()
        try:
            worker.run(stop)
        finally:
            server.close()
        return 0
    except NotifierConfigurationError:
        _print(sys.stderr, "NOTIFIER_CONFIGURATION_INVALID")
        return 2
    except NotifierError as error:
        _print(sys.stderr, error.code)
        return 3
    except Exception:
        _print(sys.stderr, "NOTIFIER_FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
