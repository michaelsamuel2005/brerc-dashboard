"""TLS-only notification providers with fixed, count-free payloads."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import smtplib
import socket
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Protocol
from urllib.parse import urlsplit

from .config import Destination, SmtpDestination, WebhookDestination
from .models import ClaimedNotification, DeliveryFailure, DeliveryResult

PAYLOAD_VERSION = "brerc-notification-v1"
USER_AGENT = "brerc-dashboard-notifier/1"


class NotificationProvider(Protocol):
    def preflight(self) -> DeliveryResult: ...

    def deliver(self, notification: ClaimedNotification) -> DeliveryResult: ...


def _iso8601(value: datetime) -> str:
    """Render one stable UTC instant regardless of the database session zone."""

    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def notification_payload(notification: ClaimedNotification) -> bytes:
    """Return the complete webhook payload.

    Counts are intentionally absent.  A mailbox/webhook is outside the
    controlled publication database and issue #47 permits only zero-count
    transferable acceptance evidence until separately approved.
    """

    document = {
        "schemaVersion": PAYLOAD_VERSION,
        "notificationId": str(notification.notification_id),
        "eventType": notification.event_type,
        "jobId": str(notification.job_id),
        "releaseId": None if notification.release_id is None else str(notification.release_id),
        "loadMode": notification.load_mode,
        "finishedAt": _iso8601(notification.finished_at),
        "failureCode": notification.failure_code,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _retry_after(value: str | None) -> int | None:
    """Accept only a bounded delta-seconds Retry-After value."""

    if value is None or not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value)
    return min(3600, max(30, parsed))


def _smtp_temporary(code: object) -> bool:
    return isinstance(code, int) and not isinstance(code, bool) and 400 <= code <= 499


def _smtp_refusal_failure(refusals: object) -> DeliveryFailure:
    """Classify the configured single-recipient refusal without retaining text."""

    if isinstance(refusals, dict) and len(refusals) == 1:
        response = next(iter(refusals.values()))
        if isinstance(response, tuple) and response and _smtp_temporary(response[0]):
            return DeliveryFailure.PROVIDER_UNAVAILABLE
    return DeliveryFailure.DESTINATION_INVALID


class WebhookProvider:
    def __init__(
        self,
        destination: WebhookDestination,
        *,
        timeout_seconds: int,
        connection_factory: object = http.client.HTTPSConnection,
    ) -> None:
        self._destination = destination
        self._timeout = timeout_seconds
        self._connection_factory = connection_factory

    def preflight(self) -> DeliveryResult:
        """Prove TCP/TLS and hostname verification without an HTTP request."""

        parsed = urlsplit(self._destination.url)
        connection = None
        try:
            connection = self._connection_factory(  # type: ignore[operator]
                parsed.hostname,
                parsed.port or 443,
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
            connection.connect()
            return DeliveryResult.success()
        except (socket.timeout, TimeoutError):
            return DeliveryResult.failed(DeliveryFailure.TIMEOUT)
        except ssl.SSLCertVerificationError:
            return DeliveryResult.failed(DeliveryFailure.CONFIGURATION_INVALID)
        except (ConnectionError, OSError):
            return DeliveryResult.failed(DeliveryFailure.CONNECTION_FAILED)
        except Exception:
            return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def deliver(self, notification: ClaimedNotification) -> DeliveryResult:
        body = notification_payload(notification)
        signature = hmac.new(self._destination.secret, body, hashlib.sha256).hexdigest()
        parsed = urlsplit(self._destination.url)
        connection = None
        try:
            # Config validation has already required HTTPS and a hostname and
            # forbidden credentials, query strings, fragments and redirects.
            connection = self._connection_factory(  # type: ignore[operator]
                parsed.hostname,
                parsed.port or 443,
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
            connection.request(
                "POST",
                parsed.path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "User-Agent": USER_AGENT,
                    "Idempotency-Key": str(notification.notification_id),
                    "X-BRERC-Signature": f"sha256={signature}",
                },
            )
            response = connection.getresponse()
            status = int(response.status)
            retry_after = _retry_after(response.getheader("Retry-After"))
            if 200 <= status <= 299:
                return DeliveryResult.success()
            if status == 429:
                return DeliveryResult.failed(DeliveryFailure.RATE_LIMITED, retry_after)
            if status in {408, 425} or 500 <= status <= 599:
                return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE, retry_after)
            if status in {401, 403}:
                return DeliveryResult.failed(DeliveryFailure.AUTHENTICATION_FAILED)
            if status in {404, 410}:
                return DeliveryResult.failed(DeliveryFailure.DESTINATION_INVALID)
            return DeliveryResult.failed(DeliveryFailure.PAYLOAD_REJECTED)
        except (socket.timeout, TimeoutError):
            return DeliveryResult.failed(DeliveryFailure.TIMEOUT)
        except ssl.SSLCertVerificationError:
            return DeliveryResult.failed(DeliveryFailure.CONFIGURATION_INVALID)
        except (ConnectionError, OSError):
            return DeliveryResult.failed(DeliveryFailure.CONNECTION_FAILED)
        except Exception:
            return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


def notification_email(
    notification: ClaimedNotification,
    destination: SmtpDestination,
) -> EmailMessage:
    event_label = "succeeded" if notification.event_type == "etl_succeeded" else "failed"
    message = EmailMessage()
    message["Subject"] = f"[BRERC dashboard] ETL {event_label}"
    message["From"] = destination.from_address
    message["To"] = ", ".join(destination.to_addresses)
    message["Date"] = format_datetime(
        notification.finished_at.astimezone(timezone.utc), usegmt=True
    )
    sender_domain = destination.from_address.rsplit("@", 1)[1].lower()
    message["Message-ID"] = f"<{notification.notification_id}@{sender_domain}>"
    message["X-BRERC-Notification-ID"] = str(notification.notification_id)
    lines = [
        "BRERC dashboard ETL notification",
        "",
        f"Result: {event_label}",
        f"Job ID: {notification.job_id}",
        f"Release ID: {notification.release_id or 'not activated'}",
        f"Load mode: {notification.load_mode}",
        f"Finished: {_iso8601(notification.finished_at)}",
        f"Failure code: {notification.failure_code or 'none'}",
        "",
        "This message deliberately contains no record samples, locations, species, people or counts.",
    ]
    message.set_content("\n".join(lines) + "\n")
    return message


class SmtpProvider:
    def __init__(
        self,
        destination: SmtpDestination,
        *,
        timeout_seconds: int,
        smtp_factory: object = smtplib.SMTP_SSL,
    ) -> None:
        self._destination = destination
        self._timeout = timeout_seconds
        self._smtp_factory = smtp_factory

    def preflight(self) -> DeliveryResult:
        """Connect with implicit TLS, authenticate and NOOP; never send mail."""

        client = None
        try:
            client = self._smtp_factory(  # type: ignore[operator]
                self._destination.host,
                self._destination.port,
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
            client.login(self._destination.username, self._destination.password)
            code, _response = client.noop()
            if 200 <= code <= 299:
                return DeliveryResult.success()
            if 400 <= code <= 499:
                return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
            if code in {530, 534, 535, 538}:
                return DeliveryResult.failed(DeliveryFailure.AUTHENTICATION_FAILED)
            return DeliveryResult.failed(DeliveryFailure.CONFIGURATION_INVALID)
        except smtplib.SMTPAuthenticationError as error:
            return DeliveryResult.failed(
                DeliveryFailure.PROVIDER_UNAVAILABLE
                if _smtp_temporary(error.smtp_code)
                else DeliveryFailure.AUTHENTICATION_FAILED
            )
        except smtplib.SMTPRecipientsRefused as error:
            return DeliveryResult.failed(_smtp_refusal_failure(error.recipients))
        except smtplib.SMTPSenderRefused as error:
            return DeliveryResult.failed(
                DeliveryFailure.PROVIDER_UNAVAILABLE
                if _smtp_temporary(error.smtp_code)
                else DeliveryFailure.DESTINATION_INVALID
            )
        except smtplib.SMTPResponseException as error:
            if 400 <= error.smtp_code <= 499:
                return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
            if error.smtp_code in {530, 534, 535, 538}:
                return DeliveryResult.failed(DeliveryFailure.AUTHENTICATION_FAILED)
            return DeliveryResult.failed(DeliveryFailure.CONFIGURATION_INVALID)
        except (socket.timeout, TimeoutError):
            return DeliveryResult.failed(DeliveryFailure.TIMEOUT)
        except ssl.SSLCertVerificationError:
            return DeliveryResult.failed(DeliveryFailure.CONFIGURATION_INVALID)
        except (ConnectionError, OSError):
            return DeliveryResult.failed(DeliveryFailure.CONNECTION_FAILED)
        except smtplib.SMTPException:
            return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
        except Exception:
            return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
        finally:
            self._close(client)

    def deliver(self, notification: ClaimedNotification) -> DeliveryResult:
        client = None
        try:
            client = self._smtp_factory(  # type: ignore[operator]
                self._destination.host,
                self._destination.port,
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
            client.login(self._destination.username, self._destination.password)
            refused = client.send_message(
                notification_email(notification, self._destination),
                from_addr=self._destination.from_address,
                to_addrs=list(self._destination.to_addresses),
            )
            if refused:
                return DeliveryResult.failed(_smtp_refusal_failure(refused))
            return DeliveryResult.success()
        except smtplib.SMTPAuthenticationError as error:
            return DeliveryResult.failed(
                DeliveryFailure.PROVIDER_UNAVAILABLE
                if _smtp_temporary(error.smtp_code)
                else DeliveryFailure.AUTHENTICATION_FAILED
            )
        except smtplib.SMTPRecipientsRefused as error:
            return DeliveryResult.failed(_smtp_refusal_failure(error.recipients))
        except smtplib.SMTPSenderRefused as error:
            return DeliveryResult.failed(
                DeliveryFailure.PROVIDER_UNAVAILABLE
                if _smtp_temporary(error.smtp_code)
                else DeliveryFailure.DESTINATION_INVALID
            )
        except smtplib.SMTPResponseException as error:
            if 400 <= error.smtp_code <= 499:
                return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
            if error.smtp_code in {530, 534, 535, 538}:
                return DeliveryResult.failed(DeliveryFailure.AUTHENTICATION_FAILED)
            return DeliveryResult.failed(DeliveryFailure.PAYLOAD_REJECTED)
        except (socket.timeout, TimeoutError):
            return DeliveryResult.failed(DeliveryFailure.TIMEOUT)
        except ssl.SSLCertVerificationError:
            return DeliveryResult.failed(DeliveryFailure.CONFIGURATION_INVALID)
        except (ConnectionError, OSError):
            return DeliveryResult.failed(DeliveryFailure.CONNECTION_FAILED)
        except smtplib.SMTPException:
            return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
        except Exception:
            return DeliveryResult.failed(DeliveryFailure.PROVIDER_UNAVAILABLE)
        finally:
            self._close(client)

    @staticmethod
    def _close(client: object | None) -> None:
        """Best-effort cleanup must never rewrite an already accepted outcome."""

        if client is None:
            return
        try:
            client.quit()  # type: ignore[attr-defined]
            return
        except Exception:
            pass
        try:
            client.close()  # type: ignore[attr-defined]
        except Exception:
            pass


def build_provider(destination: Destination, *, timeout_seconds: int) -> NotificationProvider:
    if isinstance(destination, SmtpDestination):
        return SmtpProvider(destination, timeout_seconds=timeout_seconds)
    if isinstance(destination, WebhookDestination):
        return WebhookProvider(destination, timeout_seconds=timeout_seconds)
    raise TypeError("unsupported destination type")
