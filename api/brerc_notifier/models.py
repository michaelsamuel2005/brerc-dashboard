"""Fixed notification and delivery models.

No model has a free-text error or source-record field.  Provider failures are
translated immediately into the database's finite delivery-code vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class DeliveryFailure(str, Enum):
    """Failure codes accepted by migration 0002."""

    TIMEOUT = "DELIVERY_TIMEOUT"
    CONNECTION_FAILED = "DELIVERY_CONNECTION_FAILED"
    RATE_LIMITED = "DELIVERY_RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "DELIVERY_PROVIDER_UNAVAILABLE"
    AUTHENTICATION_FAILED = "DELIVERY_AUTHENTICATION_FAILED"
    DESTINATION_INVALID = "DELIVERY_DESTINATION_INVALID"
    PAYLOAD_REJECTED = "DELIVERY_PAYLOAD_REJECTED"
    CONFIGURATION_INVALID = "DELIVERY_CONFIGURATION_INVALID"


TRANSIENT_FAILURES = frozenset(
    {
        DeliveryFailure.TIMEOUT,
        DeliveryFailure.CONNECTION_FAILED,
        DeliveryFailure.RATE_LIMITED,
        DeliveryFailure.PROVIDER_UNAVAILABLE,
    }
)

LOADER_FAILURE_CODES = frozenset(
    {
        "LOADER_FAILED",
        "LOADER_CONFIGURATION_INVALID",
        "INCREMENTAL_SOURCE_CONTRACT_BLOCKED",
        "LOADER_COORDINATOR_UNAVAILABLE",
        "LOADER_EXECUTION_FAILED",
        "LOADER_POLICY_INVALID",
        "LOADER_RELEASE_BLOCKED",
        "LOADER_TARGET_CONNECTION_FAILED",
        "LOADER_TARGET_PROTOCOL_INVALID",
        "LOADER_ALREADY_RUNNING",
        "LOADER_CANDIDATE_INVALID",
        "LOADER_SOURCE_COUNT_REJECTED",
        "LOADER_CLEANUP_FAILED",
        "LOADER_CLEANUP_PENDING",
        "WORKER_LOST",
    }
)


@dataclass(frozen=True)
class ClaimedNotification:
    """One leased, already-committed outbox item.

    These are the only database values allowed to reach a provider.  In
    particular, there is no exception text, SQL, grid reference, species name,
    person, place, credential, hostname or source-row value.
    """

    notification_id: UUID
    claim_token: UUID
    delivery_cycle: int
    cycle_attempt: int
    total_attempt_count: int
    job_id: UUID
    release_id: UUID | None
    event_type: str
    destination_key: str
    failure_code: str | None
    load_mode: str
    finished_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.finished_at, datetime)
            or self.finished_at.tzinfo is None
            or self.finished_at.utcoffset() is None
        ):
            raise ValueError("notification finish time is invalid")
        if self.event_type not in {"etl_succeeded", "etl_failed"}:
            raise ValueError("notification event type is invalid")
        if self.load_mode not in {"initial", "incremental"}:
            raise ValueError("notification load mode is invalid")
        if self.destination_key != "etl-operations":
            raise ValueError("notification destination is invalid")
        if self.delivery_cycle < 1 or self.cycle_attempt < 1 or self.total_attempt_count < 1:
            raise ValueError("notification attempt values are invalid")
        if self.event_type == "etl_succeeded":
            if self.release_id is None or self.failure_code is not None:
                raise ValueError("success notification fields are invalid")
        elif self.release_id is not None or self.failure_code not in LOADER_FAILURE_CODES:
            raise ValueError("failure notification fields are invalid")


@dataclass(frozen=True)
class DeliveryResult:
    """Safe provider outcome; receipt contents are intentionally not retained."""

    delivered: bool
    failure: DeliveryFailure | None = None
    retry_after_seconds: int | None = None

    @classmethod
    def success(cls) -> DeliveryResult:
        return cls(delivered=True)

    @classmethod
    def failed(
        cls,
        failure: DeliveryFailure,
        retry_after_seconds: int | None = None,
    ) -> DeliveryResult:
        if retry_after_seconds is not None and not 30 <= retry_after_seconds <= 3600:
            raise ValueError("retry delay is outside the accepted bound")
        if failure not in TRANSIENT_FAILURES and retry_after_seconds is not None:
            raise ValueError("permanent failures cannot request a retry delay")
        return cls(False, failure, retry_after_seconds)
