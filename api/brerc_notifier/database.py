"""Narrow PostgreSQL gateway for migration 0002.

Every operation uses a short-lived autocommit connection.  A claim therefore
commits before network I/O begins, and an SMTP/webhook timeout never holds a
database transaction or row lock.  Within the four application schemas, the
login has EXECUTE on exactly six reviewed functions and no direct table or
sequence privilege.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .config import DatabaseConfig
from .errors import (
    NotificationClaimLost,
    NotifierConfigurationError,
    NotifierDatabaseError,
    NotifierDatabaseIdentityError,
    NotifierProtocolError,
)
from .models import ClaimedNotification, DeliveryFailure

MIGRATION_KEY = "0002_notification_delivery"

PREFLIGHT_SQL = "SELECT * FROM serve.notification_worker_preflight()"

CLAIM_SQL = "SELECT * FROM loader_control.claim_notifications(%s, %s)"
RENEW_SQL = "SELECT loader_control.renew_notification_lease(%s, %s, %s) AS renewed"
ACK_SQL = "SELECT loader_control.ack_notification(%s, %s) AS acknowledged"
FAIL_SQL = "SELECT loader_control.fail_notification(%s, %s, %s, %s) AS disposition"
METRICS_SQL = "SELECT * FROM serve.notification_delivery_metrics()"


class NotificationGateway(Protocol):
    def preflight(self) -> None: ...

    def claim(self, limit: int, lease_seconds: int) -> list[ClaimedNotification]: ...

    def renew(self, notification_id: UUID, claim_token: UUID, lease_seconds: int) -> bool: ...

    def acknowledge(self, notification_id: UUID, claim_token: UUID) -> bool: ...

    def fail(
        self,
        notification_id: UUID,
        claim_token: UUID,
        code: DeliveryFailure,
        retry_after_seconds: int | None,
    ) -> str: ...

    def delivery_metrics(self) -> list[Mapping[str, object]]: ...


ConnectionFactory = Callable[..., Any]


def _sanitise(error: Exception) -> Exception:
    error.__cause__ = None
    error.__context__ = None
    error.__suppress_context__ = True
    error.__traceback__ = None
    return error


def _uuid(value: object) -> UUID:
    try:
        parsed = value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        raise NotifierProtocolError() from None
    if parsed.int == 0:
        raise NotifierProtocolError()
    return parsed


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else _uuid(value)


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise NotifierProtocolError()
    return value


def _timestamp(value: object, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise NotifierProtocolError()
    return value


def _notification(row: Mapping[str, object]) -> ClaimedNotification:
    try:
        return ClaimedNotification(
            notification_id=_uuid(row["notification_id"]),
            claim_token=_uuid(row["claim_token"]),
            delivery_cycle=_positive_integer(row["delivery_cycle"]),
            cycle_attempt=_positive_integer(row["cycle_attempt"]),
            total_attempt_count=_positive_integer(row["total_attempt_count"]),
            job_id=_uuid(row["job_id"]),
            release_id=_optional_uuid(row["release_id"]),
            event_type=str(row["event_type"]),
            destination_key=str(row["destination_key"]),
            failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
            load_mode=str(row["load_mode"]),
            finished_at=_timestamp(row["finished_at"]),  # type: ignore[arg-type]
        )
    except (KeyError, TypeError, ValueError, NotifierProtocolError):
        raise NotifierProtocolError() from None


class PostgresNotificationGateway:
    """Calls only the delivery functions granted to ``brerc_notifier``."""

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        connection_factory: ConnectionFactory = psycopg.connect,
    ) -> None:
        self._config = config
        self._connection_factory = connection_factory

    def _connect(self) -> Any:
        try:
            self._config.assert_process_environment()
            return self._connection_factory(
                autocommit=True,
                row_factory=dict_row,
                **self._config.parameters(),
            )
        except NotifierConfigurationError:
            raise
        except Exception:
            raise _sanitise(NotifierDatabaseError()) from None

    def _rows(
        self,
        statement: str,
        parameters: Sequence[object] | Mapping[str, object],
        *,
        claim_sensitive: bool = False,
    ) -> list[Any]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                return list(cursor.fetchall())
        except Exception as error:
            if claim_sensitive and getattr(error, "sqlstate", None) == "55000":
                raise _sanitise(NotificationClaimLost()) from None
            raise _sanitise(NotifierDatabaseError()) from None
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _one(
        self,
        statement: str,
        parameters: Sequence[object],
        *,
        claim_sensitive: bool = False,
    ) -> Mapping[str, object]:
        rows = self._rows(statement, parameters, claim_sensitive=claim_sensitive)
        if len(rows) != 1 or not isinstance(rows[0], Mapping):
            raise NotifierProtocolError()
        return rows[0]

    def preflight(self) -> None:
        rows = self._rows(PREFLIGHT_SQL, ())
        if len(rows) != 1 or not isinstance(rows[0], Mapping):
            raise NotifierDatabaseIdentityError()
        observed = rows[0]
        if (
            observed.get("database_name") != self._config.expected_database
            or observed.get("session_user_name") != self._config.expected_login
            or observed.get("ssl") is not True
            or not isinstance(observed.get("server_version_num"), int)
            or not 160_000 <= int(observed["server_version_num"]) < 170_000
            or observed.get("ssl_version") not in {"TLSv1.2", "TLSv1.3"}
            or observed.get("migration_version") != self._config.expected_migration_version
            or observed.get("migration_key") != MIGRATION_KEY
            or observed.get("notifier_membership_only") is not True
        ):
            raise NotifierDatabaseIdentityError()

    def claim(self, limit: int, lease_seconds: int) -> list[ClaimedNotification]:
        rows = self._rows(CLAIM_SQL, (limit, lease_seconds))
        if len(rows) > limit:
            raise NotifierProtocolError()
        return [_notification(row) for row in rows]

    def renew(self, notification_id: UUID, claim_token: UUID, lease_seconds: int) -> bool:
        row = self._one(
            RENEW_SQL,
            (notification_id, claim_token, lease_seconds),
            claim_sensitive=True,
        )
        if not isinstance(row.get("renewed"), bool):
            raise NotifierProtocolError()
        return bool(row["renewed"])

    def acknowledge(self, notification_id: UUID, claim_token: UUID) -> bool:
        row = self._one(ACK_SQL, (notification_id, claim_token), claim_sensitive=True)
        if not isinstance(row.get("acknowledged"), bool):
            raise NotifierProtocolError()
        return bool(row["acknowledged"])

    def fail(
        self,
        notification_id: UUID,
        claim_token: UUID,
        code: DeliveryFailure,
        retry_after_seconds: int | None,
    ) -> str:
        row = self._one(
            FAIL_SQL,
            (notification_id, claim_token, code.value, retry_after_seconds),
            claim_sensitive=True,
        )
        disposition = row.get("disposition")
        if disposition not in {"delivery_failed", "dead_letter"}:
            raise NotifierProtocolError()
        return str(disposition)

    def delivery_metrics(self) -> list[Mapping[str, object]]:
        rows = self._rows(METRICS_SQL, ())
        if any(not isinstance(row, Mapping) for row in rows):
            raise NotifierProtocolError()
        return rows
