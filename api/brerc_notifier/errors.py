"""Content-free errors that are safe to cross the notifier boundary."""

from __future__ import annotations


class NotifierError(RuntimeError):
    """Base class whose string value is always a fixed machine code."""

    code = "NOTIFIER_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class NotifierConfigurationError(NotifierError):
    code = "NOTIFIER_CONFIGURATION_INVALID"


class NotifierDatabaseError(NotifierError):
    code = "NOTIFIER_DATABASE_UNAVAILABLE"


class NotifierDatabaseIdentityError(NotifierError):
    code = "NOTIFIER_DATABASE_IDENTITY_INVALID"


class NotifierProtocolError(NotifierError):
    code = "NOTIFIER_DATABASE_PROTOCOL_INVALID"


class NotificationClaimLost(NotifierError):
    """The DB refused a stale/unknown lease without exposing which one."""

    code = "NOTIFICATION_CLAIM_LOST"


class NotifierProviderPreflightError(NotifierError):
    code = "NOTIFIER_PROVIDER_PREFLIGHT_FAILED"
