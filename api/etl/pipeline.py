"""Raw records in, public payloads out. This is the safety boundary.

NO GUESSED COLUMN NAMES
-----------------------
The previous `filtering.py` hard-coded `df["species_id"]`, and the supplied BRERC
data uses different names entirely. That fails with a KeyError, which is at least
loud - but the tempting "fix" is a `.get()` or a try/except, and that turns a
fail-CLOSED crash into a fail-OPEN silent pass where nothing is gated at all.

So the mapping is explicit and required. `ColumnMap` must name every source
column; a missing one raises before any row is processed. Nothing is inferred.

NO POLICY DEFAULTS
------------------
`run_pipeline` requires an explicit `PublicationPolicy`. Every decision about
what the public sees - resolutions, place names, record ids, suppression,
licensing - comes from that object, and it is validated before the first row.

NO PANDAS
---------
The boundary works on plain dicts and uses only the standard library, so it runs
anywhere, tests instantly, and has no dependency that could change parsing
behaviour underneath it. A CSV adapter is included; pandas remains available for
exploratory work but the gate does not rely on it.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .aggregate import (
    AggregationReport,
    build_cells,
    cell_for,
    records_by_year,
    year_range,
)
from .contract import PublicCell, PublicRecord, assert_no_forbidden_fields, normalise_verified
from .gridref import is_public_resolution, precision_metres
from .identifiers import assert_unique_source_ids
from .policy import InvalidPolicy, PolicyNotApproved, PublicationPolicy
from .sensitivity import (
    SENSITIVE_SNAPSHOT_SHA256,
    SENSITIVE_SNAPSHOT_VERSION,
    generalise,
    normalise_species_id,
)
from .source_contract import LoadMode, SourceContract, SourceContractError, SourceMetadata
from .species import SpeciesDictionary


@dataclass(frozen=True)
class ColumnMap:
    """Source column names. Every field is required - nothing is guessed.

    `optional` names may be absent from the source; everything else must exist or
    `run_pipeline` raises before processing any row.

    `species_id` may be absent only for an export whose source schema genuinely
    has no species-id column and only when a `SpeciesDictionary` is supplied. If
    the mapped id is present it is authoritative and the dictionary is a
    cross-check; the id is never silently replaced by a name lookup.
    """

    record_id: str
    species_id: str
    scientific_name: str
    grid_ref: str
    year: str
    common_name: str | None = None
    place: str | None = None
    abundance: str | None = None
    record_type: str | None = None
    verified: str | None = None
    source: str | None = None
    licence: str | None = None
    sensitivity: str | None = None

    def required(self) -> tuple[str, ...]:
        return (self.record_id, self.species_id, self.scientific_name, self.grid_ref, self.year)

    def optional(self) -> tuple[str, ...]:
        return tuple(
            c
            for c in (
                self.common_name,
                self.place,
                self.abundance,
                self.record_type,
                self.verified,
                self.source,
                self.licence,
                self.sensitivity,
            )
            if c is not None
        )


@dataclass
class PipelineReport:
    """An auditable account of one run. Nothing is silently discarded."""

    rows_in: int = 0
    records_public: int = 0
    records_suppressed: int = 0
    cell_cohorts_suppressed: int = 0
    withheld: Counter = field(default_factory=Counter)
    aggregation: AggregationReport | None = None
    policy_version: str = "unknown"
    policy_approved: bool = False
    policy_approval_digest: str | None = None
    sensitive_record_action: str = "undecided"
    candidate_digest: str | None = None
    source_contract_version: str | None = None
    source_contract_digest: str | None = None
    observed_view_definition_digest: str | None = None
    observed_view_identity_digest: str | None = None
    publish_individual_records: bool = False
    publish_abundance: bool = False
    publish_place_names: bool = False
    publish_record_type: bool = False
    publish_record_verification: bool = False
    verification_available: bool = False

    @property
    def rows_withheld(self) -> int:
        return sum(self.withheld.values())

    def reconciles(self) -> bool:
        """EXACT reconciliation: every input row is published or withheld.

        Deliberately `==`, not `<=`. An inequality lets rows vanish silently -
        the very failure this report exists to detect. Suppressed records are
        counted in `withheld` under "suppressed-sparse-cell", so they appear on
        exactly one side of this equation.
        """
        return self.rows_in == self.records_public + self.rows_withheld

    def summary(self) -> dict[str, object]:
        """A structural summary. Contains counts and reasons, never record content."""
        return {
            "rowsIn": self.rows_in,
            "recordsPublic": self.records_public,
            "recordsSuppressed": self.records_suppressed,
            "cellCohortsSuppressed": self.cell_cohorts_suppressed,
            "rowsWithheld": self.rows_withheld,
            "withheldByReason": dict(sorted(self.withheld.items())),
            "reconciles": self.reconciles(),
            "policyVersion": self.policy_version,
            "policyApproved": self.policy_approved,
            "policyApprovalDigest": self.policy_approval_digest,
            "sensitiveRecordAction": self.sensitive_record_action,
            "candidateDigest": self.candidate_digest,
            "sourceContractVersion": self.source_contract_version,
            "sourceContractDigest": self.source_contract_digest,
            "observedViewDefinitionDigest": self.observed_view_definition_digest,
            "observedViewIdentityDigest": self.observed_view_identity_digest,
            "publishIndividualRecords": self.publish_individual_records,
            "publishAbundance": self.publish_abundance,
            "publishPlaceNames": self.publish_place_names,
            "publishRecordType": self.publish_record_type,
            "publishRecordVerification": self.publish_record_verification,
            "verificationAvailable": self.verification_available,
            "cells": len(self.aggregation.cells) if self.aggregation else 0,
            "resolutionsEmitted": (
                list(self.aggregation.resolutions_emitted) if self.aggregation else []
            ),
        }


_VALIDATED_SOURCE_RUN_TOKEN = object()
_CANDIDATE_PREVIEW_TOKEN = object()


def _report_digest(report: PipelineReport) -> str:
    """Canonical integrity digest of the complete audit ledger."""
    aggregation = report.aggregation
    document = {
        "summary": report.summary(),
        "aggregation": (
            None
            if aggregation is None
            else {
                "recordsIn": aggregation.records_in,
                "recordsAggregated": aggregation.records_aggregated,
                "recordsSkippedUnpublishable": aggregation.records_skipped_unpublishable,
                "cellsSuppressedLowCount": aggregation.cells_suppressed_low_count,
                "resolutionsEmitted": list(aggregation.resolutions_emitted),
                "cells": [
                    {"speciesId": cell.species_id, "year": cell.year, **cell.to_api()}
                    for cell in aggregation.cells
                ],
            }
        ),
    }
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ValidatedSourceRun:
    """Read-only carrier for a candidate that passed source preflight.

    A ``PipelineReport`` is intentionally mutable while a run is assembled, so
    its public strings cannot serve as release authority. This object is
    created only after ``run_pipeline_for_source`` validates metadata, result
    headers, row keys and source identifiers. The release API accepts this
    carrier—not a caller-supplied ``(records, report)`` pair.

    Tuple-unpacking is retained for inspection and candidate previews; it
    returns a copy of the record list, so changing that copy cannot change the
    release candidate held here.
    """

    __slots__ = (
        "_candidate_digest",
        "_observed_view_definition_digest",
        "_observed_view_identity_digest",
        "_records",
        "_report",
        "_report_digest",
        "_source_contract_digest",
        "_source_contract_version",
    )

    def __init__(
        self,
        records: list[PublicRecord],
        report: PipelineReport,
        source_contract: SourceContract,
        source_metadata: SourceMetadata,
        *,
        _token: object,
    ) -> None:
        if _token is not _VALIDATED_SOURCE_RUN_TOKEN:
            raise TypeError("ValidatedSourceRun is created only by run_pipeline_for_source()")
        self._records = tuple(records)
        self._report = copy.deepcopy(report)
        self._report_digest = _report_digest(self._report)
        self._source_contract_version = source_contract.version
        self._source_contract_digest = source_contract.digest()
        observed = source_metadata.observed_view
        self._observed_view_definition_digest = (
            observed.definition_sha256 if observed is not None else None
        )
        catalog_digest = source_metadata.observed_catalog_columns_sha256
        self._observed_view_identity_digest = (
            observed.identity_sha256(
                source_contract.columns_sha256(),
                catalog_digest,
            )
            if observed is not None and catalog_digest is not None
            else None
        )
        self._candidate_digest = report.candidate_digest

    def __iter__(self) -> Iterator[object]:
        yield list(self._records)
        yield copy.deepcopy(self._report)


class CandidatePreview:
    """Opaque, non-serialisable view of development payloads.

    A preview intentionally is *not* a ``dict`` or ``Mapping``.  This makes it
    unsuitable for JSON encoding and prevents a future database writer from
    accepting the output of :func:`build_candidate_payloads` by accident.  The
    only release-capable builder remains :func:`build_payloads`, whose input is
    the independently opaque :class:`ValidatedSourceRun`.

    Tests and the deterministic browser-fixture generator may inspect a named
    payload through ``preview["cells"]``.  Each access returns a defensive copy,
    so inspection cannot mutate the held preview.
    """

    __slots__ = ("__payloads",)

    def __init__(self, payloads: dict[str, object], *, _token: object) -> None:
        if _token is not _CANDIDATE_PREVIEW_TOKEN:
            raise TypeError("CandidatePreview is created only by build_candidate_payloads()")
        self.__payloads = copy.deepcopy(payloads)

    def __getitem__(self, key: str) -> object:
        return copy.deepcopy(self.__payloads[key])

    def keys(self) -> tuple[str, ...]:
        return tuple(self.__payloads)

    def __repr__(self) -> str:
        return f"CandidatePreview(candidate_only=True, keys={self.keys()!r})"


#: Default page size for an assembled payload.
#:
#: MUST BE POSITIVE. `RecordPageSchema.pageSize` in web/src/lib/api/schemas.ts is
#: `z.number().int().positive()`, so a page size of 0 - which an earlier version
#: produced for an empty result set by using `len(records)` - fails validation on
#: the client and renders as a network error rather than an empty state.
DEFAULT_PAGE_SIZE = 100


class MissingColumns(ValueError):
    """Raised when the source lacks a required column. Never downgraded."""


class UnmappedControlColumn(ValueError):
    """Raised when a safety-control column is present but not mapped.

    This prevents an export configuration from being reused against the live
    PostgreSQL view and silently ignoring its row-level ``sensitive`` field.
    """


class DuplicatePublicId(RuntimeError):
    """Raised when two records would be published under the same public id."""


#: Plausible recording window. Anything outside it is a data error, not a date.
MIN_YEAR, MAX_YEAR = 1500, 2200

_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")

_SENSITIVITY_COLUMN_KEYS = frozenset({"sensitive", "sensitivity"})
_RECORD_TYPE_COLUMN_KEYS = frozenset({"recordtype"})


def _normalise_column_name(value: object) -> str:
    """Normalise a source-column name for safety-alias comparison."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _validate_source_columns(
    rows: list[dict[str, object]],
    columns: ColumnMap,
    *,
    policy: PublicationPolicy,
    dictionary: SpeciesDictionary | None,
) -> None:
    """Validate the source shape before processing any row.

    Ordinary optional presentation fields may be absent. A mapped sensitivity
    control may not: its absence is a configuration error, not an ordinary
    record value. Conversely, a recognisable sensitivity column that is present
    but unmapped is refused so a legacy export mapping cannot disable the live
    view's control silently.
    """
    if columns.sensitivity is not None and policy.row_sensitive_resolution_metres is None:
        raise InvalidPolicy(
            f"ColumnMap maps row-level sensitivity as {columns.sensitivity!r}, but "
            "row_sensitive_resolution_metres is not configured. Refusing to read "
            "the control without a publication rule."
        )
    if policy.row_sensitive_resolution_metres is not None and columns.sensitivity is None:
        raise InvalidPolicy(
            "row_sensitive_resolution_metres is configured, but ColumnMap.sensitivity "
            "is not mapped. A row-level protection rule may not be left dormant."
        )
    if policy.sensitive_record_type_metres and columns.record_type is None:
        raise InvalidPolicy(
            "sensitive_record_type_metres contains rules, but ColumnMap.record_type "
            "is not mapped. A record-type protection rule may not be left dormant."
        )
    if policy.verification_publication_mode == "publish" and columns.verified is None:
        raise InvalidPolicy(
            "verification_publication_mode='publish' requires ColumnMap.verified; "
            "verification cannot be inferred from another field"
        )

    if not rows:
        return

    source_has_species_id = any(columns.species_id in row for row in rows)
    required = [
        column
        for column in columns.required()
        if not (
            dictionary is not None and column == columns.species_id and not source_has_species_id
        )
    ]
    if columns.sensitivity is not None:
        required.append(columns.sensitivity)
    if policy.sensitive_record_type_metres and columns.record_type is not None:
        required.append(columns.record_type)
    if policy.verification_publication_mode == "publish" and columns.verified is not None:
        required.append(columns.verified)

    missing = sorted(column for column in required if any(column not in row for row in rows))
    if missing:
        available = sorted({str(key) for row in rows for key in row})
        raise MissingColumns(
            f"source is missing required column(s): {', '.join(missing)}. "
            f"Available: {', '.join(available)}. "
            "Set ColumnMap explicitly - the mapping is never inferred."
        )

    present_sensitivity_columns = {
        str(key)
        for row in rows
        for key in row
        if _normalise_column_name(key) in _SENSITIVITY_COLUMN_KEYS
    }
    mapped = columns.sensitivity
    ignored = present_sensitivity_columns - ({mapped} if mapped is not None else set())
    if ignored:
        mapped_text = repr(mapped) if mapped is not None else "nothing"
        raise UnmappedControlColumn(
            "source contains row-level sensitivity control column(s) "
            f"{sorted(ignored)}, but ColumnMap maps {mapped_text}. Map the exact "
            "source column; a present safety control may never be waived or ignored."
        )

    if policy.sensitive_record_type_metres:
        present_record_type_columns = {
            str(key)
            for row in rows
            for key in row
            if _normalise_column_name(key) in _RECORD_TYPE_COLUMN_KEYS
        }
        mapped_record_type = columns.record_type
        ignored_record_types = present_record_type_columns - (
            {mapped_record_type} if mapped_record_type is not None else set()
        )
        if ignored_record_types:
            raise UnmappedControlColumn(
                "source contains record-type control column(s) "
                f"{sorted(ignored_record_types)}, but ColumnMap maps "
                f"{mapped_record_type!r}. Map the exact source column; a present "
                "safety control may never be waived or ignored."
            )


def _validate_runtime_sensitivity_inputs(
    policy: PublicationPolicy,
    dictionary: SpeciesDictionary | None,
) -> None:
    """Bind every runtime sensitivity source to the approved precision envelope."""
    if policy.development_only or policy.precision_mode != "approved":
        return
    if (
        policy.sensitive_snapshot_version != SENSITIVE_SNAPSHOT_VERSION
        or policy.sensitive_snapshot_sha256 != SENSITIVE_SNAPSHOT_SHA256
    ):
        raise InvalidPolicy(
            "approved precision policy does not match the runtime sensitive-species snapshot"
        )
    if dictionary is None:
        if policy.species_dictionary_sha256 is not None:
            raise InvalidPolicy(
                "approved precision policy binds a SpeciesDictionary, but no dictionary "
                "was supplied at runtime"
            )
        return
    observed = dictionary.digest()
    if policy.species_dictionary_sha256 != observed:
        raise InvalidPolicy(
            "SpeciesDictionary contributes identity/sensitivity data but its "
            "digest is absent from or differs from the approved precision policy"
        )


def _to_year(value: object) -> int | None:
    """Extract the record year from a BRERC date value.

    Real BRERC exports use several shapes, and taking the first four characters -
    as an earlier version did - fails on almost all of them:

        "23/03/2023"                 -> int("23/0")  ValueError   (0 of 998 rows parsed)
        "04/08/2023 - 17/10/2023"    -> int("04/0")  ValueError
        "2017"                       -> 2017                       (worked by luck)

    So: take the LAST four-digit group in the plausible range. For DD/MM/YYYY that
    is the year; for a vague-date range it is the END year, matching the semantics
    of the source's own `YearEnd` column. Day and month components are one or two
    digits and cannot be mistaken for a year.

    Prefer mapping `year` to `YearEnd` where the export provides it - it is a
    proper integer column, populated on every row of both client samples.
    """
    if value is None:
        return None

    # datetime / pandas Timestamp and anything else exposing .year
    year_attr = getattr(value, "year", None)
    if isinstance(year_attr, int) and MIN_YEAR <= year_attr <= MAX_YEAR:
        return year_attr

    if isinstance(value, bool):  # bool is an int subclass; never a year
        return None
    if isinstance(value, int):
        return value if MIN_YEAR <= value <= MAX_YEAR else None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        if not value.is_integer():
            return None
        as_int = int(value)
        return as_int if MIN_YEAR <= as_int <= MAX_YEAR else None

    text = str(value).strip()
    decimal_year = re.fullmatch(r"[+-]?\d+\.(\d+)", text)
    if decimal_year and any(digit != "0" for digit in decimal_year.group(1)):
        return None
    candidates = [int(m) for m in _YEAR_RE.findall(text)]
    plausible = [y for y in candidates if MIN_YEAR <= y <= MAX_YEAR]
    return plausible[-1] if plausible else None


def _text(row: dict[str, object], column: str | None) -> str | None:
    if column is None:
        return None
    value = row.get(column)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def to_public_records(
    rows: Iterable[dict[str, object]],
    columns: ColumnMap,
    report: PipelineReport,
    *,
    policy: PublicationPolicy,
    dictionary: SpeciesDictionary | None = None,
) -> Iterator[PublicRecord]:
    """Generalise and reshape rows, recording a reason for everything withheld."""
    for row in rows:
        report.rows_in += 1

        year = _to_year(row.get(columns.year))
        if year is None:
            report.withheld["unusable-year"] += 1
            continue

        scientific_name = _text(row, columns.scientific_name)
        if not scientific_name:
            report.withheld["missing-scientific-name"] += 1
            continue

        original_id = _text(row, columns.record_id)
        if not original_id:
            report.withheld["missing-record-id"] += 1
            continue

        # Resolve identity without letting a scientific name overwrite an id.
        # The live view supplies both. Its mapped id is authoritative; a
        # dictionary, when present, must agree with that id before its taxonomy
        # and sensitivity metadata can be trusted. Name lookup is a fallback
        # only for the older exports whose rows genuinely lack the id column.
        source_has_species_id = columns.species_id in row
        source_species_id = (
            normalise_species_id(row.get(columns.species_id)) if source_has_species_id else None
        )

        if dictionary is not None and dictionary.is_ambiguous(scientific_name):
            report.withheld["ambiguous-species-name"] += 1
            continue

        entry = dictionary.lookup(scientific_name) if dictionary is not None else None
        if source_has_species_id:
            # A present-but-empty/invalid id is a data error. Falling back to the
            # name here would conceal it and could apply another taxon's policy.
            if source_species_id is None:
                report.withheld["missing-species-id"] += 1
                continue
            species_id = source_species_id
            if entry is not None and normalise_species_id(entry.species_no) != species_id:
                report.withheld["species-identity-mismatch"] += 1
                continue
            # A syntactically valid source id proves identity shape, not that
            # the taxon appears in the approved dictionary. Without a
            # dictionary every releasable id is unknown and follows the
            # policy's explicit unknown-species action; it is never silently
            # treated as ordinary. Development-only candidates retain their
            # synthetic convenience because they cannot cross the release gate.
            known = entry is not None or (dictionary is None and policy.development_only)
            flagged: bool | None = entry.sensitive if entry is not None else None
        else:
            # This is the only permitted fallback path: the source row does not
            # contain the mapped species-id field at all.
            species_id = normalise_species_id(entry.species_no) if entry is not None else None
            known = entry is not None
            flagged = entry.sensitive if entry is not None else None

        if species_id is None:
            # PublicRecord and every aggregate require a stable species key.
            # There is no honest value to invent for an unresolved fallback.
            report.withheld["species-not-permitted"] += 1
            continue

        raw_record_type = row.get(columns.record_type) if columns.record_type is not None else None
        if policy.record_type_safety_mode == "rules" and not policy.record_type_is_known(
            raw_record_type
        ):
            # A rules policy binds the complete approved source vocabulary.
            # Blank, unknown and newly introduced values are never assumed to
            # be ordinary merely because they have no sensitive rule yet.
            report.withheld["record-type-not-permitted"] += 1
            continue

        gen = generalise(
            row.get(columns.grid_ref),
            species_id,
            policy=policy,
            known=known,
            record_type=raw_record_type,
            flagged_sensitive=flagged,
            row_sensitive=(
                policy.is_row_sensitive(row.get(columns.sensitivity))
                if columns.sensitivity is not None
                else False
            ),
        )
        if not gen.emit or gen.grid_ref is None or gen.precision_metres is None:
            report.withheld[gen.withheld_reason or "withheld"] += 1
            continue

        # Licence gate, when BRERC has stated a vocabulary.
        if not policy.licence_permits_publication(_text(row, columns.licence)):
            report.withheld["licence-not-permitted"] += 1
            continue

        # A place name can defeat generalisation entirely: a 10 km square beside
        # "Private garden, 12 Acacia Avenue" is not generalised in any useful
        # sense. Withheld unless the policy explicitly permits place names.
        place = _text(row, columns.place) if policy.publish_place_names else None

        report.records_public += 1
        # Constructed field by field from the allow-list. No source row is passed
        # through, so a column nobody anticipated cannot ride along.
        yield PublicRecord(
            record_id=policy.public_record_id(original_id),
            species_id=species_id,
            scientific_name=scientific_name,
            common_name=_text(row, columns.common_name),
            grid_ref=gen.grid_ref,
            precision_metres=gen.precision_metres,
            place=place,
            year=year,
            abundance=(
                _text(row, columns.abundance)
                if policy.publish_individual_records and policy.publish_abundance
                else None
            ),
            record_type=(
                _text(row, columns.record_type)
                if policy.publish_individual_records and policy.publish_record_type
                else None
            ),
            verified=normalise_verified(
                (
                    _text(row, columns.verified)
                    if policy.verification_publication_mode == "publish"
                    else None
                ),
                accepted_values=policy.accepted_verification_values,
            ),
            # Never copy the raw Source column: client exports/view text may
            # contain recorder names, addresses or internal references. The
            # approved policy supplies a controlled organisational label.
            source=policy.public_source_label,
        )


def run_pipeline(
    rows: Iterable[dict[str, object]],
    columns: ColumnMap,
    *,
    policy: PublicationPolicy,
    dictionary: SpeciesDictionary | None = None,
) -> tuple[list[PublicRecord], PipelineReport]:
    """Run the whole boundary. Raises if required columns are absent.

    `policy` is required and validated first: a policy naming a resolution the
    client cannot draw is a configuration error and must surface as one, not as
    a per-row withholding that reads like a data problem.

    Suppression is applied CONSISTENTLY. Hiding a sparse map cell while still
    listing its records in the table, and counting them in the year series, does
    not suppress anything - the same information is simply one click away. So
    records inside a suppressed cell are withheld, and the cells and the year
    series are then rebuilt from the surviving records only. Map, table, chart
    and totals therefore describe one dataset.
    """
    policy.validate()
    _validate_runtime_sensitivity_inputs(policy, dictionary)

    rows = list(rows)
    _validate_source_columns(rows, columns, policy=policy, dictionary=dictionary)

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

    candidates = list(
        to_public_records(rows, columns, report, policy=policy, dictionary=dictionary)
    )

    min_per_cell = policy.min_records_per_cell
    if min_per_cell <= 1:
        survivors = candidates
    else:
        # Which cells fall below the threshold?
        trial = build_cells(
            candidates,
            min_records=1,
            map_cell_metres=policy.map_cell_resolution_metres,
        )
        sparse = {
            (c.species_id, c.year, c.cell_id, c.precision_metres)
            for c in trial.cells
            if c.record_count < min_per_cell
        }
        report.cell_cohorts_suppressed = len(sparse)
        survivors = []
        for rec in candidates:
            spatial_key = cell_for(
                rec,
                map_cell_metres=policy.map_cell_resolution_metres,
            )
            key = (rec.species_id, rec.year, *spatial_key) if spatial_key is not None else None
            if key is not None and key in sparse:
                report.withheld["suppressed-sparse-cell"] += 1
                report.records_public -= 1
                report.records_suppressed += 1
            else:
                survivors.append(rec)

    _assert_unique_public_ids(survivors)

    # Cells are rebuilt from survivors, so min_records is already satisfied.
    report.aggregation = build_cells(
        survivors,
        min_records=1,
        map_cell_metres=policy.map_cell_resolution_metres,
    )
    report.candidate_digest = _candidate_digest(
        survivors,
        report.aggregation,
        publish_individual_records=report.publish_individual_records,
        publish_abundance=report.publish_abundance,
        publish_place_names=report.publish_place_names,
        publish_record_type=report.publish_record_type,
        publish_record_verification=report.publish_record_verification,
        verification_available=report.verification_available,
    )
    return survivors, report


def run_pipeline_for_source(
    rows: Iterable[dict[str, object]],
    columns: ColumnMap,
    *,
    source_contract: SourceContract,
    source_metadata: SourceMetadata,
    source_result_columns: Iterable[str],
    load_mode: LoadMode,
    policy: PublicationPolicy,
    dictionary: SpeciesDictionary | None = None,
) -> ValidatedSourceRun:
    """Production-facing entry point with header-level source validation.

    ``run_pipeline`` remains useful for synthetic/export development. A live
    database path must use this wrapper so the full source header is validated
    before extraction, even when the query returns zero rows. This is what stops
    an old export mapping from silently ignoring a newly added safety control.
    """
    source_contract.require_mode(load_mode)
    policy.validate()
    policy.assert_approved()
    source_contract.validate_initial(source_metadata)
    source_contract.validate_safety_mapping(columns, policy)
    projection = (*columns.required(), *columns.optional())
    result_columns = tuple(source_result_columns)
    source_contract.validate_result_header(result_columns, projection)

    materialised = list(rows)
    expected_row_keys = set(result_columns)
    for row in materialised:
        actual_row_keys = set(row)
        if actual_row_keys != expected_row_keys:
            raise SourceContractError(
                "SOURCE_RESULT_ROW_MISMATCH: row keys do not match the validated "
                f"cursor header; missing {sorted(expected_row_keys - actual_row_keys)!r}, "
                f"extra {sorted(actual_row_keys - expected_row_keys)!r}"
            )
    canonical_ids = assert_unique_source_ids(row.get(columns.record_id) for row in materialised)
    canonical_rows: list[dict[str, object]] = []
    for row, canonical_id in zip(materialised, canonical_ids, strict=True):
        copy = dict(row)
        copy[columns.record_id] = canonical_id
        canonical_rows.append(copy)
    records, report = run_pipeline(
        canonical_rows,
        columns,
        policy=policy,
        dictionary=dictionary,
    )
    # Plain run_pipeline() is permanently candidate-only. Only this wrapper can
    # attest that the complete, versioned source metadata and safety mapping
    # passed before extraction.
    report.source_contract_version = source_contract.version
    report.source_contract_digest = source_contract.digest()
    if source_metadata.observed_view is not None:
        report.observed_view_definition_digest = source_metadata.observed_view.definition_sha256
        if source_metadata.observed_catalog_columns_sha256 is not None:
            report.observed_view_identity_digest = source_metadata.observed_view.identity_sha256(
                source_contract.columns_sha256(),
                source_metadata.observed_catalog_columns_sha256,
            )
    return ValidatedSourceRun(
        records,
        report,
        source_contract,
        source_metadata,
        _token=_VALIDATED_SOURCE_RUN_TOKEN,
    )


def _assert_unique_public_ids(records: list[PublicRecord]) -> None:
    """Fail loudly on an id collision rather than merging two records silently.

    `PublicationPolicy.public_record_id` truncates an HMAC to 128 bits, so a
    collision is improbable but not impossible. The client keys list rows and
    selection state on `id`; two records sharing one would render as a single
    row and silently lose an occurrence. Cheap to check, so it is checked.
    """
    seen: set[str] = set()
    for rec in records:
        if rec.record_id in seen:
            raise DuplicatePublicId(
                f"two records resolve to the public id {rec.record_id!r}. This is "
                "either an HMAC truncation collision or a duplicated source "
                "record id; both need investigating before publication."
            )
        seen.add(rec.record_id)


def _candidate_digest(
    records: list[PublicRecord],
    aggregation: AggregationReport | None,
    *,
    publish_individual_records: bool,
    publish_abundance: bool,
    publish_place_names: bool,
    publish_record_type: bool,
    publish_record_verification: bool,
    verification_available: bool,
) -> str:
    """Bind the ordered candidate records and per-species cells to a report."""
    document = {
        "publishIndividualRecords": publish_individual_records,
        "publishAbundance": publish_abundance,
        "publishPlaceNames": publish_place_names,
        "publishRecordType": publish_record_type,
        "publishRecordVerification": publish_record_verification,
        "verificationAvailable": verification_available,
        "records": [{"speciesId": record.species_id, **record.to_api()} for record in records],
        "cells": [
            {"speciesId": cell.species_id, "year": cell.year, **cell.to_api()}
            for cell in (aggregation.cells if aggregation else ())
        ],
    }
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assert_candidate_matches_report(
    records: list[PublicRecord],
    report: PipelineReport,
    *,
    map_cell_metres: int,
) -> None:
    """Refuse a substituted, modified or internally inconsistent candidate."""
    if not report.reconciles() or len(records) != report.records_public:
        raise PolicyNotApproved(
            "candidate record count does not reconcile with the approved pipeline report"
        )
    recomputed = build_cells(
        records,
        min_records=1,
        map_cell_metres=map_cell_metres,
    )
    if report.aggregation != recomputed:
        raise PolicyNotApproved("candidate aggregation does not match the approved pipeline report")
    for record in records:
        resolved = precision_metres(record.grid_ref)
        if resolved != record.precision_metres or not is_public_resolution(record.precision_metres):
            raise PolicyNotApproved(
                "candidate contains a grid reference whose precision is inconsistent"
            )
    expected = _candidate_digest(
        records,
        recomputed,
        publish_individual_records=report.publish_individual_records,
        publish_abundance=report.publish_abundance,
        publish_place_names=report.publish_place_names,
        publish_record_type=report.publish_record_type,
        publish_record_verification=report.publish_record_verification,
        verification_available=report.verification_available,
    )
    if not report.candidate_digest or not hmac.compare_digest(report.candidate_digest, expected):
        raise PolicyNotApproved(
            "candidate records differ from the data bound to the approved pipeline report"
        )


#: Exact key sets the client's .strict() schemas accept. A .strict() Zod object
#: REJECTS an unrecognised key, so an extra field is a hard failure, not a
#: harmless addition - and it fails at the browser, which renders as a network
#: error rather than an obviously wrong payload.
#:
#: Source of truth: web/src/lib/api/schemas.ts
#:   CellDistributionSchema  z.object({ verificationAvailable, cells }).strict()
#:   RecordPageSchema        z.object({ items, page, pageSize, total,
#:                                       publication }).strict()
CELL_DISTRIBUTION_KEYS: frozenset[str] = frozenset({"verificationAvailable", "cells"})
RECORD_PAGE_KEYS: frozenset[str] = frozenset({"items", "page", "pageSize", "total", "publication"})


def _combine_cell_cohorts(
    cells: list[PublicCell],
    *,
    verification_available: bool,
) -> list[dict[str, object]]:
    """Combine already-safe yearly cohorts for an all-years map response."""
    totals: dict[tuple[str, int], list[int]] = {}
    for cell in cells:
        key = (cell.cell_id, cell.precision_metres)
        counts = totals.setdefault(key, [0, 0])
        counts[0] += cell.record_count
        counts[1] += cell.verified_count
    combined: list[dict[str, object]] = []
    for (cell_id, metres), counts in sorted(totals.items()):
        item: dict[str, object] = {
            "cellId": cell_id,
            "precisionMetres": metres,
            "recordCount": counts[0],
        }
        if verification_available:
            item["verifiedCount"] = counts[1]
        combined.append(item)
    return combined


def _assemble_payloads(
    records: list[PublicRecord],
    report: PipelineReport,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    page: int = 1,
    species_id: str | None = None,
    year: int | None = None,
) -> dict[str, object]:
    """Assemble API-shaped data after the caller has selected its trust level.

    `payloads["cells"]` and `payloads["records"]` are byte-exact to
    `CellDistributionSchema` and `RecordPageSchema` in web/src/lib/api/schemas.ts
    and are asserted against those key sets before returning.

    `payloads["meta"]` carries derived figures that are NOT part of the client
    contract - kept under a separate key precisely so nothing can drift into a
    strict schema by accident.

    NOT SummarySchema. The ETL cannot currently produce a valid `SummarySchema`
    object, and this is deliberately not faked:
      * `totalSpecies` is computable, but
      * `topGroups` needs a taxonomic grouping the occurrence export does not
        carry (the dictionary has FAMILY and TAXANB; which one BRERC means by
        "group", if either, is not settled);
      * `coverageCaveat` is text BRERC must write, not text we may invent.

    `yearRange` is now nullable and the ETL already uses ``None`` for an empty
    result. Verification is a separate availability issue: the confirmed live
    view has no verdict column, so this module omits aggregate verified counts
    rather than turning "unavailable" into a misleading numeric zero.

    This is a single-page assembly for verification and fixture generation, not
    the paging implementation - that belongs to the read-only API. It exists so
    the ETL output can be validated against the client's own schemas before any
    database work starts.
    """
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be a positive integer")
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive integer")
    if year is not None and (
        isinstance(year, bool) or not isinstance(year, int) or not MIN_YEAR <= year <= MAX_YEAR
    ):
        raise ValueError(f"year must be an integer from {MIN_YEAR} to {MAX_YEAR}")

    aggregation = report.aggregation
    all_cells = list(aggregation.cells) if aggregation else []
    available_species = {record.species_id for record in records}
    if species_id is None:
        if len(available_species) > 1:
            raise ValueError(
                "payload endpoints are species-scoped; species_id is required "
                "when a candidate contains multiple species"
            )
        selected_species = next(iter(available_species), None)
    else:
        selected_species = str(species_id).strip().upper()
        if not selected_species:
            raise ValueError("species_id must not be blank")

    scoped_records = (
        records
        if selected_species is None
        else [record for record in records if record.species_id == selected_species]
    )
    if year is not None:
        scoped_records = [record for record in scoped_records if record.year == year]
    cells = (
        []
        if selected_species is None
        else [cell for cell in all_cells if cell.species_id == selected_species]
    )
    if year is not None:
        cells = [cell for cell in cells if cell.year == year]
    public_rows = scoped_records if report.publish_individual_records else []
    start = (page - 1) * page_size
    window = public_rows[start : start + page_size]
    span = year_range(scoped_records)

    cell_items = _combine_cell_cohorts(
        cells,
        verification_available=report.verification_available,
    )
    cell_payload = {
        "verificationAvailable": report.verification_available,
        "cells": cell_items,
    }
    record_items = [r.to_api() for r in window]
    if not (report.verification_available and report.publish_record_verification):
        for item in record_items:
            item.pop("verified", None)
    record_payload = {
        "items": record_items,
        "page": page,
        # Positive by construction: the schema rejects 0, which is what
        # `len(records)` produced for an empty result set.
        "pageSize": page_size,
        "total": len(public_rows),
        "publication": {
            "mode": (
                "individual-records" if report.publish_individual_records else "aggregates-only"
            ),
            "fields": {
                "abundance": (report.publish_individual_records and report.publish_abundance),
                "place": (report.publish_individual_records and report.publish_place_names),
                "recordType": (report.publish_individual_records and report.publish_record_type),
                "verification": (
                    report.publish_individual_records
                    and report.verification_available
                    and report.publish_record_verification
                ),
            },
        },
    }

    _assert_exact_keys(cell_payload, CELL_DISTRIBUTION_KEYS, "CellDistributionSchema")
    _assert_exact_keys(record_payload, RECORD_PAGE_KEYS, "RecordPageSchema")

    year_items = records_by_year(scoped_records)
    if not report.verification_available:
        year_items = [
            {key: value for key, value in item.items() if key != "verifiedCount"}
            for item in year_items
        ]

    return {
        "cells": cell_payload,
        "records": record_payload,
        "meta": {
            "recordsByYear": year_items,
            "verificationAvailable": report.verification_available,
            "yearRange": {"min": span[0], "max": span[1]} if span else None,
            "totalRecords": sum(int(cell["recordCount"]) for cell in cell_items),
            "totalSpecies": len({r.species_id for r in scoped_records}),
        },
    }


def build_candidate_payloads(
    records: list[PublicRecord],
    report: PipelineReport,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    page: int = 1,
    species_id: str | None = None,
    year: int | None = None,
) -> CandidatePreview:
    """Build a synthetic/development preview that must never be released.

    The explicit ``candidate`` name prevents a test or export transform from
    being mistaken for an authorised public release. Production writers and
    activation code must call :func:`build_payloads` instead.
    """
    payloads = _assemble_payloads(
        records,
        report,
        page_size=page_size,
        page=page,
        species_id=species_id,
        year=year,
    )
    assert_payloads_clean(payloads)
    return CandidatePreview(payloads, _token=_CANDIDATE_PREVIEW_TOKEN)


def build_payloads(
    validated_run: ValidatedSourceRun | object,
    legacy_report: PipelineReport | None = None,
    *,
    policy: PublicationPolicy,
    source_contract: SourceContract,
    page_size: int = DEFAULT_PAGE_SIZE,
    page: int = 1,
    species_id: str | None = None,
    year: int | None = None,
) -> dict[str, object]:
    """Build releasable payloads only under the exact current approval.

    Validation is repeated at the release boundary: a policy may expire after
    transformation, and an approved policy object may be copied and changed.
    The validated-source carrier binds the source preflight, records and report;
    a plain mutable ``(records, report)`` pair is never release authority.
    """
    if not isinstance(validated_run, ValidatedSourceRun) or legacy_report is not None:
        raise PolicyNotApproved(
            "releasable payloads require the opaque ValidatedSourceRun returned by "
            "run_pipeline_for_source(); plain pipeline records and mutable report "
            "fields can never attest source validation"
        )
    records = list(validated_run._records)
    report = validated_run._report
    if not hmac.compare_digest(validated_run._report_digest, _report_digest(report)):
        raise PolicyNotApproved("validated source audit ledger changed after source validation")
    policy.validate()
    policy.assert_approved()
    if validated_run._source_contract_version != source_contract.version:
        raise PolicyNotApproved(
            "pipeline report has no matching versioned source-contract attestation; "
            "plain run_pipeline candidates can never be released"
        )
    if not hmac.compare_digest(
        validated_run._source_contract_digest,
        source_contract.digest(),
    ):
        raise PolicyNotApproved(
            "pipeline report source-contract digest does not match the reviewed contract"
        )
    source_contract.assert_release_ready()
    approval = source_contract.view_approval
    if approval is None:
        raise PolicyNotApproved("source contract has no BRERC-approved live view identity")
    if (
        validated_run._observed_view_definition_digest is None
        or not hmac.compare_digest(
            validated_run._observed_view_definition_digest,
            approval.definition_sha256,
        )
        or validated_run._observed_view_identity_digest is None
        or not hmac.compare_digest(
            validated_run._observed_view_identity_digest,
            approval.identity_sha256,
        )
    ):
        raise PolicyNotApproved(
            "validated source view evidence differs from the BRERC-approved identity"
        )
    if (
        report.source_contract_version != validated_run._source_contract_version
        or report.source_contract_digest != validated_run._source_contract_digest
        or report.observed_view_definition_digest != validated_run._observed_view_definition_digest
        or report.observed_view_identity_digest != validated_run._observed_view_identity_digest
    ):
        raise PolicyNotApproved("pipeline report source-attestation fields were changed")
    if not report.candidate_digest or not hmac.compare_digest(
        report.candidate_digest,
        validated_run._candidate_digest or "",
    ):
        raise PolicyNotApproved("pipeline report candidate digest changed after source validation")
    if not report.policy_approved:
        raise PolicyNotApproved(
            "pipeline report is an unapproved development candidate and cannot "
            "be converted into releasable payloads"
        )
    if report.policy_version != policy.version:
        raise PolicyNotApproved(
            "release policy version differs from the policy that transformed the records"
        )
    if report.sensitive_record_action != policy.sensitive_record_action:
        raise PolicyNotApproved(
            "sensitive-record action differs from the policy that transformed the records"
        )
    if report.publish_individual_records is not policy.publish_individual_records:
        raise PolicyNotApproved(
            "individual-record publication mode differs from the approved policy"
        )
    if report.publish_abundance is not policy.publish_abundance:
        raise PolicyNotApproved("abundance publication capability differs from the approved policy")
    if report.publish_place_names is not policy.publish_place_names:
        raise PolicyNotApproved(
            "place-name publication capability differs from the approved policy"
        )
    if report.publish_record_type is not policy.publish_record_type:
        raise PolicyNotApproved(
            "record-type publication capability differs from the approved policy"
        )
    if report.publish_record_verification is not policy.publish_record_verification:
        raise PolicyNotApproved(
            "record-verification publication capability differs from the approved policy"
        )
    expected_verification = policy.verification_publication_mode == "publish"
    if report.verification_available is not expected_verification:
        raise PolicyNotApproved(
            "verification publication capability differs from the approved policy"
        )
    if not report.policy_approval_digest or not hmac.compare_digest(
        report.policy_approval_digest,
        policy.approval_digest or "",
    ):
        raise PolicyNotApproved(
            "release approval digest differs from the policy that transformed the records"
        )
    _assert_candidate_matches_report(
        records,
        report,
        map_cell_metres=policy.map_cell_resolution_metres,
    )
    payloads = _assemble_payloads(
        records,
        report,
        page_size=page_size,
        page=page,
        species_id=species_id,
        year=year,
    )
    assert_payloads_clean(payloads)
    return payloads


def _assert_exact_keys(
    payload: dict[str, object], expected: frozenset[str], schema_name: str
) -> None:
    actual = set(payload)
    if actual != expected:
        raise AssertionError(
            f"{schema_name} is .strict() and accepts exactly {sorted(expected)}; "
            f"this payload has {sorted(actual)}. Extra: "
            f"{sorted(actual - expected)}; missing: {sorted(expected - actual)}."
        )


def assert_payloads_clean(payloads: dict[str, object]) -> None:
    """Raise if any forbidden field reached the payloads. Belt and braces."""
    found = assert_no_forbidden_fields(payloads)
    if found:
        raise AssertionError(
            "forbidden field(s) reached the public payloads - the allow-list in "
            f"contract.py has been bypassed: {found}"
        )


def read_csv(path: str | Path) -> list[dict[str, object]]:
    """Read a CSV into plain dicts. Standard library only."""
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]
