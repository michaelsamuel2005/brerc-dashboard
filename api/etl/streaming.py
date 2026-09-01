"""Bounded-memory transformation for the private PostgreSQL loader.

This module deliberately stops before global suppression and aggregation.
Those operations depend on the complete candidate and therefore belong in the
inactive PostgreSQL staging area, not in independently processed Python
batches.  Calling the ordinary complete-run pipeline once per batch would make
publication depend on the arbitrary batch boundary.

The only object that leaves this layer is :class:`SafeDisposition`: an HMAC
source token, an HMAC fingerprint, and either an allow-listed, already
generalised ``PublicRecord`` or a fixed withholding reason.  Raw ``unique_no``,
precise source fields and source control flags never leave the transformation
call.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .aggregate import cell_for
from .contract import PublicRecord
from .gridref import square_bounds
from .identifiers import canonical_unique_no
from .pipeline import (
    ColumnMap,
    PipelineReport,
    _validate_runtime_sensitivity_inputs,
    to_public_records,
)
from .policy import PublicationPolicy
from .source_contract import LoadMode, SourceContract, SourceContractError, SourceMetadata
from .species import SpeciesDictionary

MIN_RECONCILIATION_SECRET_BYTES = 32
_SOURCE_TOKEN_DOMAIN = b"brerc-loader-source-token-v1\x00"
_FINGERPRINT_DOMAIN = b"brerc-loader-safe-input-v1\x00"
_SESSION_TOKEN = object()


class StreamingTransformError(ValueError):
    """A streaming row or lifecycle invariant failed without echoing data."""


@dataclass(frozen=True)
class SafeDisposition:
    """One private source key's safe, job-scoped candidate disposition."""

    source_token: str
    source_fingerprint: str
    record: PublicRecord | None
    withheld_reason: str | None
    cell_id: str | None
    cell_precision_metres: int | None
    min_easting: int | None
    min_northing: int | None
    max_easting: int | None
    max_northing: int | None

    def __post_init__(self) -> None:
        for label, value in (
            ("source_token", self.source_token),
            ("source_fingerprint", self.source_fingerprint),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise StreamingTransformError(f"{label} must be a lowercase SHA-256 digest")
        eligible = self.record is not None
        if eligible == (self.withheld_reason is not None):
            raise StreamingTransformError(
                "a disposition must contain exactly one of a safe record or withholding reason"
            )
        spatial = (
            self.cell_id,
            self.cell_precision_metres,
            self.min_easting,
            self.min_northing,
            self.max_easting,
            self.max_northing,
        )
        if eligible and any(value is None for value in spatial):
            raise StreamingTransformError("an eligible disposition requires complete safe geometry")
        if not eligible and any(value is not None for value in spatial):
            raise StreamingTransformError("a withheld disposition cannot carry spatial data")


def _safe_json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _digest(secret: bytes, domain: bytes, payload: bytes) -> str:
    return hmac.new(secret, domain + payload, hashlib.sha256).hexdigest()


class StreamingTransformSession:
    """Stateful, bounded-memory transformer for one validated source snapshot."""

    __slots__ = (
        "_columns",
        "_dictionary",
        "_finished",
        "_header",
        "_policy",
        "_report",
        "_secret",
        "_sensitivity_counts",
    )

    def __init__(
        self,
        *,
        columns: ColumnMap,
        policy: PublicationPolicy,
        dictionary: SpeciesDictionary | None,
        header: tuple[str, ...],
        reconciliation_secret: bytes,
        _token: object,
    ) -> None:
        if _token is not _SESSION_TOKEN:
            raise TypeError("use begin_streaming_transform()")
        self._columns = columns
        self._policy = policy
        self._dictionary = dictionary
        self._header = header
        self._secret = reconciliation_secret
        self._finished = False
        self._sensitivity_counts: Counter[str] = Counter()
        report = PipelineReport()
        report.policy_version = policy.version
        report.policy_approved = policy.is_approved()
        report.policy_approval_digest = policy.approval_digest
        report.sensitive_record_action = policy.sensitive_record_action
        report.publish_individual_records = policy.publish_individual_records
        report.publish_abundance = policy.publish_abundance
        report.publish_place_names = policy.publish_place_names
        report.publish_record_type = policy.publish_record_type
        report.publish_record_verification = policy.publish_record_verification
        report.verification_available = (
            policy.verification_publication_mode == "publish" and columns.verified is not None
        )
        self._report = report

    def transform_batch(
        self,
        rows: Iterable[Mapping[str, object]],
    ) -> tuple[SafeDisposition, ...]:
        if self._finished:
            raise StreamingTransformError("streaming transform is already finished")
        dispositions: list[SafeDisposition] = []
        expected_keys = set(self._header)
        for source_row in rows:
            row = dict(source_row)
            if set(row) != expected_keys:
                raise SourceContractError(
                    "SOURCE_RESULT_ROW_MISMATCH: row keys differ from the validated header"
                )
            canonical_id = canonical_unique_no(row.get(self._columns.record_id))
            row[self._columns.record_id] = canonical_id
            if self._columns.sensitivity is not None:
                raw_sensitivity = row.get(self._columns.sensitivity)
                normalised_sensitivity = (
                    "" if raw_sensitivity is None else str(raw_sensitivity).strip().casefold()
                )
                if not normalised_sensitivity:
                    bucket = "null-or-blank"
                elif normalised_sensitivity in self._policy.non_sensitive_values:
                    bucket = "no"
                elif normalised_sensitivity == "yes":
                    bucket = "yes"
                else:
                    bucket = "other"
                self._sensitivity_counts[bucket] += 1
            token = _digest(self._secret, _SOURCE_TOKEN_DOMAIN, canonical_id.encode("ascii"))
            fingerprint_document = [
                [column, _safe_json_value(row[column])] for column in self._header
            ]
            fingerprint = _digest(
                self._secret,
                _FINGERPRINT_DOMAIN,
                json.dumps(
                    fingerprint_document,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8"),
            )

            before_withheld = Counter(self._report.withheld)
            before_public = self._report.records_public
            records = tuple(
                to_public_records(
                    (row,),
                    self._columns,
                    self._report,
                    policy=self._policy,
                    dictionary=self._dictionary,
                )
            )
            if len(records) > 1:
                raise StreamingTransformError("one source row produced multiple public records")
            if records:
                if self._report.records_public != before_public + 1:
                    raise StreamingTransformError("eligible-row accounting drifted")
                record = records[0]
                cell = cell_for(
                    record,
                    map_cell_metres=self._policy.map_cell_resolution_metres,
                )
                if cell is None:
                    raise StreamingTransformError("eligible record has no publishable map cell")
                bounds = square_bounds(cell[0])
                if bounds is None or cell[1] < record.precision_metres:
                    raise StreamingTransformError("safe map-cell geometry is inconsistent")
                dispositions.append(
                    SafeDisposition(
                        source_token=token,
                        source_fingerprint=fingerprint,
                        record=record,
                        withheld_reason=None,
                        cell_id=cell[0],
                        cell_precision_metres=cell[1],
                        min_easting=bounds[0],
                        min_northing=bounds[1],
                        max_easting=bounds[2],
                        max_northing=bounds[3],
                    )
                )
                continue

            deltas = self._report.withheld - before_withheld
            reasons = [reason for reason, count in deltas.items() for _ in range(count)]
            if len(reasons) != 1 or self._report.records_public != before_public:
                raise StreamingTransformError("withheld-row accounting drifted")
            dispositions.append(
                SafeDisposition(
                    source_token=token,
                    source_fingerprint=fingerprint,
                    record=None,
                    withheld_reason=reasons[0],
                    cell_id=None,
                    cell_precision_metres=None,
                    min_easting=None,
                    min_northing=None,
                    max_easting=None,
                    max_northing=None,
                )
            )
        return tuple(dispositions)

    def finish(self) -> PipelineReport:
        if self._finished:
            raise StreamingTransformError("streaming transform is already finished")
        self._finished = True
        return copy.deepcopy(self._report)

    @property
    def sensitivity_buckets(self) -> tuple[tuple[str, int], ...]:
        """Fixed-category counts only; raw source values never leave the session."""
        return tuple(sorted(self._sensitivity_counts.items()))


def begin_streaming_transform(
    *,
    columns: ColumnMap,
    source_contract: SourceContract,
    source_metadata: SourceMetadata,
    source_result_columns: Sequence[str],
    policy: PublicationPolicy,
    reconciliation_secret: bytes,
    dictionary: SpeciesDictionary | None = None,
) -> StreamingTransformSession:
    """Validate every non-row input before constructing a streaming session."""
    if (
        not isinstance(reconciliation_secret, bytes)
        or len(reconciliation_secret) < MIN_RECONCILIATION_SECRET_BYTES
    ):
        raise StreamingTransformError(
            f"reconciliation secret must contain at least {MIN_RECONCILIATION_SECRET_BYTES} bytes"
        )
    source_contract.require_mode(LoadMode.INITIAL)
    validate_streaming_policy_inputs(policy=policy, dictionary=dictionary)
    source_contract.validate_initial(source_metadata)
    source_contract.validate_safety_mapping(columns, policy)
    projection = (*columns.required(), *columns.optional())
    header = tuple(source_result_columns)
    source_contract.validate_result_header(header, projection)
    return StreamingTransformSession(
        columns=columns,
        policy=policy,
        dictionary=dictionary,
        header=header,
        reconciliation_secret=bytes(reconciliation_secret),
        _token=_SESSION_TOKEN,
    )


def validate_streaming_policy_inputs(
    *,
    policy: PublicationPolicy,
    dictionary: SpeciesDictionary | None,
) -> None:
    """Validate approval and the bound dictionary before any database socket.

    The connector calls this during preflight ordering, then the transform calls
    it again at construction. Repeating a deterministic, side-effect-free check
    keeps the streaming boundary safe even if it is used independently.
    """
    policy.validate()
    policy.assert_approved()
    _validate_runtime_sensitivity_inputs(policy, dictionary)
