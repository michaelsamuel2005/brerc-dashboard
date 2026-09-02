from __future__ import annotations

import hashlib
import hmac
import json
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from uuid import UUID

from brerc_notifier.config import SmtpDestination, WebhookDestination
from brerc_notifier.models import ClaimedNotification, DeliveryFailure
from brerc_notifier.providers import (
    SmtpProvider,
    WebhookProvider,
    notification_email,
    notification_payload,
)


def _notification(*, failed: bool = False) -> ClaimedNotification:
    return ClaimedNotification(
        notification_id=UUID("11111111-1111-4111-8111-111111111111"),
        claim_token=UUID("22222222-2222-4222-8222-222222222222"),
        delivery_cycle=1,
        cycle_attempt=1,
        total_attempt_count=1,
        job_id=UUID("33333333-3333-4333-8333-333333333333"),
        release_id=None if failed else UUID("44444444-4444-4444-8444-444444444444"),
        event_type="etl_failed" if failed else "etl_succeeded",
        destination_key="etl-operations",
        failure_code="LOADER_POLICY_INVALID" if failed else None,
        load_mode="initial",
        finished_at=datetime(2026, 8, 26, 12, 30, tzinfo=timezone.utc),
    )


class _Response:
    def __init__(self, status: int, retry_after: str | None = None) -> None:
        self.status = status
        self._retry_after = retry_after
        self.reads = 0

    def getheader(self, name: str) -> str | None:
        return self._retry_after if name == "Retry-After" else None

    def read(self, _limit: int) -> bytes:
        self.reads += 1
        return b"provider response is deliberately ignored"


class _HttpsConnection:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.requests: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.connects = 0
        self.closed = False
        self.factory_args: tuple[object, ...] = ()
        self.factory_kwargs: dict[str, object] = {}

    def factory(self, *args: object, **kwargs: object) -> _HttpsConnection:
        self.factory_args = args
        self.factory_kwargs = kwargs
        return self

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        self.requests.append((method, path, body, headers))

    def connect(self) -> None:
        self.connects += 1

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_webhook_is_count_free_signed_and_stably_idempotent() -> None:
    destination = WebhookDestination(
        provider="webhook",
        url="https://alerts.example.org/brerc",
        secret=b"s" * 32,
    )
    connection = _HttpsConnection(_Response(202))
    provider = WebhookProvider(
        destination,
        timeout_seconds=15,
        connection_factory=connection.factory,
    )

    first = provider.deliver(_notification())
    second = provider.deliver(_notification())

    assert first.delivered and second.delivered
    assert connection.response.reads == 0
    assert len(connection.requests) == 2
    method, path, body, headers = connection.requests[0]
    assert method == "POST"
    assert path == "/brerc"
    assert body == connection.requests[1][2]
    assert headers["Idempotency-Key"] == "11111111-1111-4111-8111-111111111111"
    assert headers["Idempotency-Key"] == connection.requests[1][3]["Idempotency-Key"]
    expected = hmac.new(b"s" * 32, body, hashlib.sha256).hexdigest()
    assert headers["X-BRERC-Signature"] == f"sha256={expected}"
    document = json.loads(body)
    assert set(document) == {
        "schemaVersion",
        "notificationId",
        "eventType",
        "jobId",
        "releaseId",
        "loadMode",
        "finishedAt",
        "failureCode",
    }
    serialised = body.decode("utf-8").casefold()
    for forbidden in (
        "source_rows",
        "candidate_rows",
        "rows_withheld",
        "species",
        "grid",
        "place",
        "recorder",
        "password",
    ):
        assert forbidden not in serialised


def test_webhook_preflight_proves_tls_without_making_an_http_request() -> None:
    destination = WebhookDestination(
        provider="webhook",
        url="https://alerts.example.org/brerc",
        secret=b"s" * 32,
    )
    connection = _HttpsConnection(_Response(500))
    result = WebhookProvider(
        destination,
        timeout_seconds=15,
        connection_factory=connection.factory,
    ).preflight()
    assert result.delivered
    assert connection.connects == 1
    assert connection.requests == []
    context = connection.factory_kwargs["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_webhook_classifies_rate_limit_and_clamps_retry_after() -> None:
    destination = WebhookDestination("webhook", "https://alerts.example.org/brerc", b"s" * 32)
    connection = _HttpsConnection(_Response(429, "1"))
    result = WebhookProvider(
        destination, timeout_seconds=15, connection_factory=connection.factory
    ).deliver(_notification())
    assert result.failure is DeliveryFailure.RATE_LIMITED
    assert result.retry_after_seconds == 30


def test_webhook_rejects_authentication_without_retry() -> None:
    destination = WebhookDestination("webhook", "https://alerts.example.org/brerc", b"s" * 32)
    connection = _HttpsConnection(_Response(401))
    result = WebhookProvider(
        destination, timeout_seconds=15, connection_factory=connection.factory
    ).deliver(_notification())
    assert result.failure is DeliveryFailure.AUTHENTICATION_FAILED
    assert result.retry_after_seconds is None


class _SmtpClient:
    def __init__(
        self,
        *,
        authentication_code: int | None = None,
        cleanup_failure: bool = False,
        recipient_code: int | None = None,
        sender_code: int | None = None,
    ) -> None:
        self.authentication_code = authentication_code
        self.cleanup_failure = cleanup_failure
        self.recipient_code = recipient_code
        self.sender_code = sender_code
        self.messages: list[EmailMessage] = []
        self.login_values: tuple[str, str] | None = None
        self.noops = 0
        self.factory_args: tuple[object, ...] = ()
        self.factory_kwargs: dict[str, object] = {}

    def factory(self, *args: object, **kwargs: object) -> _SmtpClient:
        self.factory_args = args
        self.factory_kwargs = kwargs
        return self

    def __enter__(self) -> _SmtpClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        if self.authentication_code is not None:
            raise smtplib.SMTPAuthenticationError(
                self.authentication_code, b"private provider detail"
            )
        self.login_values = (username, password)

    def send_message(self, message: EmailMessage, **_kwargs: object) -> dict[str, object]:
        if self.sender_code is not None:
            raise smtplib.SMTPSenderRefused(
                self.sender_code,
                b"private provider detail",
                "dashboard@example.org",
            )
        if self.recipient_code is not None:
            raise smtplib.SMTPRecipientsRefused(
                {"operator@example.org": (self.recipient_code, b"private provider detail")}
            )
        self.messages.append(message)
        return {}

    def noop(self) -> tuple[int, bytes]:
        self.noops += 1
        return 250, b"ok"

    def quit(self) -> None:
        if self.cleanup_failure:
            raise OSError("private cleanup detail")

    def close(self) -> None:
        if self.cleanup_failure:
            raise OSError("private cleanup detail")


def _smtp_destination() -> SmtpDestination:
    return SmtpDestination(
        provider="smtp",
        host="smtp.example.org",
        port=465,
        from_address="dashboard@example.org",
        to_addresses=("operator@example.org",),
        username="private-user",
        password="private-password",
    )


def test_smtp_uses_stable_message_id_and_count_free_body() -> None:
    client = _SmtpClient()
    provider = SmtpProvider(
        _smtp_destination(), timeout_seconds=15, smtp_factory=client.factory
    )

    assert provider.deliver(_notification()).delivered
    assert provider.deliver(_notification()).delivered
    assert client.login_values == ("private-user", "private-password")
    first, second = client.messages
    assert first["Message-ID"] == second["Message-ID"]
    assert first["Message-ID"] == "<11111111-1111-4111-8111-111111111111@example.org>"
    body = first.get_content().casefold()
    assert "no record samples" in body
    for forbidden in (
        "257 supplied rows",
        "vipera berus",
        "st 567 789",
        "jane fieldworker",
        "ashton court",
    ):
        assert forbidden not in body


def test_smtp_preflight_authenticates_and_noops_without_sending() -> None:
    client = _SmtpClient()
    result = SmtpProvider(
        _smtp_destination(), timeout_seconds=15, smtp_factory=client.factory
    ).preflight()
    assert result.delivered
    assert client.login_values == ("private-user", "private-password")
    assert client.noops == 1
    assert client.messages == []
    context = client.factory_kwargs["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_smtp_authentication_error_is_permanent_and_content_free() -> None:
    client = _SmtpClient(authentication_code=535)
    result = SmtpProvider(
        _smtp_destination(), timeout_seconds=15, smtp_factory=client.factory
    ).deliver(_notification(failed=True))
    assert result.failure is DeliveryFailure.AUTHENTICATION_FAILED
    assert result.retry_after_seconds is None
    assert "private provider detail" not in repr(result)


def test_smtp_temporary_authentication_error_is_retried() -> None:
    provider = SmtpProvider(
        _smtp_destination(),
        timeout_seconds=15,
        smtp_factory=_SmtpClient(authentication_code=454).factory,
    )
    assert provider.deliver(_notification(failed=True)).failure is (
        DeliveryFailure.PROVIDER_UNAVAILABLE
    )
    assert provider.preflight().failure is DeliveryFailure.PROVIDER_UNAVAILABLE


def test_smtp_temporary_recipient_and_sender_errors_are_retried() -> None:
    recipient_result = SmtpProvider(
        _smtp_destination(),
        timeout_seconds=15,
        smtp_factory=_SmtpClient(recipient_code=450).factory,
    ).deliver(_notification())
    sender_result = SmtpProvider(
        _smtp_destination(),
        timeout_seconds=15,
        smtp_factory=_SmtpClient(sender_code=451).factory,
    ).deliver(_notification())
    assert recipient_result.failure is DeliveryFailure.PROVIDER_UNAVAILABLE
    assert sender_result.failure is DeliveryFailure.PROVIDER_UNAVAILABLE


def test_smtp_permanent_recipient_error_is_not_retried() -> None:
    result = SmtpProvider(
        _smtp_destination(),
        timeout_seconds=15,
        smtp_factory=_SmtpClient(recipient_code=550).factory,
    ).deliver(_notification())
    assert result.failure is DeliveryFailure.DESTINATION_INVALID


def test_smtp_cleanup_failure_cannot_rewrite_accepted_delivery() -> None:
    client = _SmtpClient(cleanup_failure=True)
    result = SmtpProvider(
        _smtp_destination(), timeout_seconds=15, smtp_factory=client.factory
    ).deliver(_notification())
    assert result.delivered
    assert len(client.messages) == 1


def test_certificate_verification_failures_are_fixed_and_fail_closed() -> None:
    def certificate_failure(*_args: object, **_kwargs: object) -> object:
        raise ssl.SSLCertVerificationError(1, "private certificate detail")

    webhook = WebhookProvider(
        WebhookDestination(
            provider="webhook",
            url="https://alerts.example.org/brerc",
            secret=b"s" * 32,
        ),
        timeout_seconds=15,
        connection_factory=certificate_failure,
    )
    smtp = SmtpProvider(
        _smtp_destination(),
        timeout_seconds=15,
        smtp_factory=certificate_failure,
    )

    for result in (
        webhook.preflight(),
        webhook.deliver(_notification()),
        smtp.preflight(),
        smtp.deliver(_notification()),
    ):
        assert result.failure is DeliveryFailure.CONFIGURATION_INVALID
        assert "private certificate detail" not in repr(result)


def test_payload_is_deterministic() -> None:
    assert notification_payload(_notification()) == notification_payload(_notification())
    assert notification_email(_notification(), _smtp_destination())["Message-ID"] == (
        "<11111111-1111-4111-8111-111111111111@example.org>"
    )


def test_payload_and_email_normalise_non_utc_database_timestamp() -> None:
    notification = _notification()
    shifted = ClaimedNotification(
        **{
            **notification.__dict__,
            "finished_at": datetime(
                2026,
                8,
                26,
                13,
                30,
                tzinfo=timezone(timedelta(hours=1)),
            ),
        }
    )

    document = json.loads(notification_payload(shifted))
    message = notification_email(shifted, _smtp_destination())
    assert document["finishedAt"] == "2026-08-26T12:30:00Z"
    assert "Finished: 2026-08-26T12:30:00Z" in message.get_content()
    assert parsedate_to_datetime(str(message["Date"])) == datetime(
        2026, 8, 26, 12, 30, tzinfo=timezone.utc
    )
