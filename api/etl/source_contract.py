"""Strict contract for BRERC's ``dashboard.main_data_dash`` source view.

This module describes what BRERC supplies. It does not decide what may be
published; that remains the separate :mod:`policy` boundary.

The 39 confirmed columns below were transcribed from the client-supplied view
definition dated 31 July 2026. ``date_mdb_modified`` is deliberately separate:
it was promised later in email, but is absent from that supplied definition.
Initial-load development can therefore validate the 39-column view honestly,
while incremental loading remains blocked until the extra field and its
semantics are confirmed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from .view_identity import (
    ObservedViewDefinition,
    ViewDefinitionApproval,
    source_columns_sha256,
)


class SourceContractError(ValueError):
    """The live source metadata does not match its reviewed contract."""


class IncrementalLoadBlocked(SourceContractError):
    """Incremental loading lacks one or more source guarantees."""

    def __init__(self, blockers: Iterable[str]):
        self.blockers = tuple(blockers)
        rendered = "\n".join(f"- {blocker}" for blocker in self.blockers)
        super().__init__(f"BLOCKED_SOURCE_CONTRACT:\n{rendered}")


class InvalidLoadMode(SourceContractError):
    """A load mode was omitted, aliased or misspelled."""


class LoadMode(str, Enum):
    INITIAL = "initial"
    INCREMENTAL = "incremental"


def parse_load_mode(raw: object) -> LoadMode:
    """Parse an explicit command mode; booleans and informal aliases fail."""
    if not isinstance(raw, str):
        raise InvalidLoadMode("load mode must be the string 'initial' or 'incremental'")
    try:
        return LoadMode(raw.strip().casefold())
    except ValueError:
        raise InvalidLoadMode(
            f"unsupported load mode {raw!r}; use 'initial' or 'incremental'"
        ) from None


@dataclass(frozen=True)
class ColumnSpec:
    """One expected ``information_schema.columns`` entry."""

    name: str
    data_type: str
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None

    def differences(self, actual: SourceColumn) -> tuple[str, ...]:
        differences: list[str] = []
        if _normalise_type(actual.data_type) != _normalise_type(self.data_type):
            differences.append(f"type expected {self.data_type!r}, got {actual.data_type!r}")
        if actual.character_maximum_length != self.character_maximum_length:
            differences.append(
                "character maximum length expected "
                f"{self.character_maximum_length!r}, got "
                f"{actual.character_maximum_length!r}"
            )
        if actual.numeric_precision != self.numeric_precision:
            differences.append(
                f"numeric precision expected {self.numeric_precision!r}, got "
                f"{actual.numeric_precision!r}"
            )
        if actual.numeric_scale != self.numeric_scale:
            differences.append(
                f"numeric scale expected {self.numeric_scale!r}, got {actual.numeric_scale!r}"
            )
        return tuple(differences)


@dataclass(frozen=True)
class SourceColumn:
    """Actual column metadata read before any record rows are extracted."""

    name: str
    data_type: str
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None

    @classmethod
    def from_information_schema(cls, row: dict[str, object]) -> SourceColumn:
        """Build from an explicit metadata query, never from a sample row."""

        def optional_int(value: object) -> int | None:
            return None if value is None else int(value)

        return cls(
            name=str(row["column_name"]),
            data_type=str(row["data_type"]),
            character_maximum_length=optional_int(row.get("character_maximum_length")),
            numeric_precision=optional_int(row.get("numeric_precision")),
            numeric_scale=optional_int(row.get("numeric_scale")),
        )


@dataclass(frozen=True)
class SourceMetadata:
    """The source object and its full header, including for an empty result."""

    schema: str
    name: str
    object_type: str
    columns: tuple[SourceColumn, ...]
    #: Exact live evidence returned by PostgreSQL.  The definition is hashed
    #: inside this boundary; callers cannot substitute a naked checksum.
    observed_view: ObservedViewDefinition | None = None
    #: Digest of the complete ordered catalogue column evidence captured in
    #: the same source snapshot (including UDT/nullability/collation fields).
    observed_catalog_columns_sha256: str | None = None


@dataclass(frozen=True)
class SourceSchemaReport:
    confirmed_columns: int
    incremental_supported: bool
    release_supported: bool
    warnings: tuple[str, ...]


# Every field on ``pipeline.ColumnMap`` is part of the reviewed mapping, even
# when a field is deliberately disabled with ``None``. Omitting a target would
# make ``validate_safety_mapping`` unable to notice a future mapping change.
PIPELINE_MAPPING_TARGETS: frozenset[str] = frozenset(
    {
        "record_id",
        "species_id",
        "scientific_name",
        "grid_ref",
        "year",
        "common_name",
        "place",
        "abundance",
        "record_type",
        "verified",
        "source",
        "licence",
        "sensitivity",
    }
)


@dataclass(frozen=True)
class SourceContract:
    version: str
    schema: str
    name: str
    object_type: str
    columns: tuple[ColumnSpec, ...]
    record_id_column: str
    sensitivity_column: str
    pipeline_mapping: tuple[tuple[str, str | None], ...]
    row_sensitive_resolution_metres: int
    non_sensitive_values: frozenset[str]
    allowed_modes: frozenset[LoadMode]
    incremental_blockers: tuple[str, ...]
    client_reference_document_sha256: str | None = None
    required_source_environment: str | None = None
    required_approver_organisation: str = "BRERC"
    view_approval: ViewDefinitionApproval | None = None
    release_blockers: tuple[str, ...] = ()

    def digest(self) -> str:
        """Canonical identity of the reviewed source and safety mapping."""
        document = {
            "version": self.version,
            "schema": self.schema,
            "name": self.name,
            "objectType": self.object_type,
            "columns": [
                {
                    "name": column.name,
                    "type": column.data_type,
                    "length": column.character_maximum_length,
                    "precision": column.numeric_precision,
                    "scale": column.numeric_scale,
                }
                for column in self.columns
            ],
            "recordIdColumn": self.record_id_column,
            "sensitivityColumn": self.sensitivity_column,
            "pipelineMapping": list(self.pipeline_mapping),
            "rowSensitiveResolutionMetres": self.row_sensitive_resolution_metres,
            "nonSensitiveValues": sorted(self.non_sensitive_values),
            "allowedModes": sorted(mode.value for mode in self.allowed_modes),
            "incrementalBlockers": list(self.incremental_blockers),
            "clientReferenceDocumentSha256": self.client_reference_document_sha256,
            "requiredSourceEnvironment": self.required_source_environment,
            "requiredApproverOrganisation": self.required_approver_organisation,
            "viewApproval": self.view_approval.to_document() if self.view_approval else None,
            "releaseBlockers": list(self.release_blockers),
        }
        canonical = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def __post_init__(self) -> None:
        if self.client_reference_document_sha256 is not None:
            digest = self.client_reference_document_sha256
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or digest != digest.lower()
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise SourceContractError(
                    "client_reference_document_sha256 must be a lowercase SHA-256 hex digest"
                )
        if not isinstance(self.release_blockers, tuple) or any(
            not isinstance(blocker, str) or not blocker.strip() for blocker in self.release_blockers
        ):
            raise SourceContractError("release_blockers must be a tuple of non-blank strings")
        if self.required_source_environment is not None and (
            not isinstance(self.required_source_environment, str)
            or not self.required_source_environment.strip()
        ):
            raise SourceContractError(
                "required_source_environment must be a non-blank string or None"
            )
        if (
            not isinstance(self.required_approver_organisation, str)
            or not self.required_approver_organisation.strip()
        ):
            raise SourceContractError("required_approver_organisation must be a non-blank string")
        attributes = [attribute for attribute, _ in self.pipeline_mapping]
        if len(attributes) != len(set(attributes)):
            raise SourceContractError("pipeline_mapping contains a duplicate target field")
        targets = set(attributes)
        if targets != PIPELINE_MAPPING_TARGETS:
            raise SourceContractError(
                "pipeline_mapping must name the exact ColumnMap target set; "
                f"missing {sorted(PIPELINE_MAPPING_TARGETS - targets)!r}, "
                f"extra {sorted(targets - PIPELINE_MAPPING_TARGETS)!r}"
            )
        mapped = dict(self.pipeline_mapping)
        if mapped.get("record_id") != self.record_id_column:
            raise SourceContractError("record_id_column disagrees with pipeline_mapping")
        if mapped.get("sensitivity") != self.sensitivity_column:
            raise SourceContractError("sensitivity_column disagrees with pipeline_mapping")
        source_names = {column.name for column in self.columns}
        outside = sorted(
            value for value in mapped.values() if value is not None and value not in source_names
        )
        if outside:
            raise SourceContractError(
                f"pipeline_mapping references columns outside the source contract: {outside}"
            )
        if self.view_approval is not None:
            if self.required_source_environment is None:
                raise SourceContractError(
                    "an approved view requires a pinned required_source_environment"
                )
            expected_relkind = "v" if self.object_type.casefold() == "view" else self.object_type
            approval_errors: list[str] = []
            for label, expected, actual in (
                ("schema", self.schema, self.view_approval.schema),
                ("name", self.name, self.view_approval.name),
                ("relkind", expected_relkind, self.view_approval.relkind),
                ("columnsSha256", self.columns_sha256(), self.view_approval.columns_sha256),
                (
                    "clientReferenceDocumentSha256",
                    self.client_reference_document_sha256,
                    self.view_approval.client_reference_document_sha256,
                ),
                (
                    "sourceEnvironment",
                    self.required_source_environment,
                    self.view_approval.source_environment,
                ),
                (
                    "approverOrganisation",
                    self.required_approver_organisation,
                    self.view_approval.approver_organisation,
                ),
            ):
                if expected != actual:
                    approval_errors.append(f"{label} expected {expected!r}, got {actual!r}")
            if approval_errors:
                raise SourceContractError(
                    "view approval does not describe this source contract:\n- "
                    + "\n- ".join(approval_errors)
                )

    def columns_document(self) -> tuple[dict[str, object], ...]:
        """Canonical ordered column representation shared with capture tooling."""
        return tuple(
            {
                "name": column.name,
                "type": column.data_type,
                "length": column.character_maximum_length,
                "precision": column.numeric_precision,
                "scale": column.numeric_scale,
            }
            for column in self.columns
        )

    def columns_sha256(self) -> str:
        return source_columns_sha256(self.columns_document())

    def validate_initial(self, metadata: SourceMetadata) -> SourceSchemaReport:
        """Validate the full view schema before reading any record rows."""
        errors = self._schema_errors(metadata)
        if errors:
            raise SourceContractError("SOURCE_SCHEMA_MISMATCH:\n- " + "\n- ".join(errors))

        warnings = [
            "date_mdb_modified is absent from this confirmed view version; "
            "incremental loading is blocked.",
        ]
        if not self.is_release_ready():
            warnings.append(
                "column metadata proves the reviewed shape, not the meaning of the live "
                "view SQL; public release is blocked until a BRERC-approved "
                "view-identity envelope and all release prerequisites are pinned."
            )
        return SourceSchemaReport(
            len(self.columns),
            False,
            self.is_release_ready(),
            tuple(warnings),
        )

    def is_release_ready(self) -> bool:
        """Whether this source contract has every release-level attestation."""
        return (
            self.view_approval is not None
            and self.view_approval.is_current()
            and self.required_source_environment is not None
            and not self.release_blockers
        )

    def assert_release_ready(self) -> None:
        """Block publication under a development-only source description."""
        blockers = list(self.release_blockers)
        if self.view_approval is None:
            blockers.append("BRERC-approved live view identity envelope has not been received")
        elif not self.view_approval.is_current():
            blockers.append(
                f"BRERC view-definition approval expired on {self.view_approval.review_expires_on}"
            )
        if self.required_source_environment is None:
            blockers.append("BRERC-approved source environment has not been pinned")
        if blockers:
            rendered = "\n".join(f"- {blocker}" for blocker in blockers)
            raise SourceContractError(f"BLOCKED_SOURCE_RELEASE:\n{rendered}")

    def validate_result_header(
        self,
        observed: Iterable[str],
        expected_projection: Iterable[str],
    ) -> None:
        """Validate the cursor header before consuming even an empty result."""
        actual = tuple(observed)
        expected = tuple(expected_projection)
        if not expected:
            raise SourceContractError("SOURCE_RESULT_HEADER_MISMATCH: projection is empty")
        if len(expected) != len(set(expected)):
            raise SourceContractError(
                "SOURCE_RESULT_HEADER_MISMATCH: projection contains duplicate columns"
            )
        contract_names = {column.name for column in self.columns}
        unknown = sorted(set(expected) - contract_names)
        if unknown:
            raise SourceContractError(
                f"SOURCE_RESULT_HEADER_MISMATCH: projection is outside the contract: {unknown}"
            )
        if actual != expected:
            raise SourceContractError(
                "SOURCE_RESULT_HEADER_MISMATCH: cursor header does not exactly "
                f"match the explicit projection; expected {list(expected)!r}, "
                f"got {list(actual)!r}"
            )

    def require_mode(self, mode: LoadMode) -> None:
        """Permit only modes implemented for this exact contract version."""
        if not isinstance(mode, LoadMode):
            raise InvalidLoadMode(
                f"load mode must be a LoadMode value produced by parse_load_mode(), "
                f"got {type(mode).__name__}"
            )
        if mode in self.allowed_modes:
            return
        if mode is LoadMode.INCREMENTAL:
            raise IncrementalLoadBlocked(self.incremental_blockers)
        raise InvalidLoadMode(f"load mode {mode.value!r} is not enabled")

    def validate_safety_mapping(self, columns: object, policy: object) -> None:
        """Bind the source's safety controls to the publication mechanism."""
        errors: list[str] = []
        for attribute, expected in self.pipeline_mapping:
            actual = getattr(columns, attribute, None)
            if actual != expected:
                errors.append(f"{attribute} must map exactly to {expected!r}, got {actual!r}")

        row_resolution = getattr(policy, "row_sensitive_resolution_metres", None)
        if row_resolution != self.row_sensitive_resolution_metres:
            errors.append(
                "row-sensitive resolution must be exactly "
                f"{self.row_sensitive_resolution_metres} metres, got {row_resolution!r}"
            )
        vocabulary = frozenset(getattr(policy, "non_sensitive_values", frozenset()))
        if vocabulary != self.non_sensitive_values:
            errors.append(
                "non-sensitive vocabulary must be exactly "
                f"{sorted(self.non_sensitive_values)!r}, got {sorted(vocabulary)!r}"
            )
        if errors:
            raise SourceContractError("SOURCE_SAFETY_MAPPING_MISMATCH:\n- " + "\n- ".join(errors))

    def _schema_errors(self, metadata: SourceMetadata) -> list[str]:
        errors: list[str] = []
        if metadata.schema != self.schema:
            errors.append(f"schema expected {self.schema!r}, got {metadata.schema!r}")
        if metadata.name != self.name:
            errors.append(f"object expected {self.name!r}, got {metadata.name!r}")
        if metadata.object_type.strip().casefold() != self.object_type.casefold():
            errors.append(
                f"object type expected {self.object_type!r}, got {metadata.object_type!r}"
            )
        observed = metadata.observed_view
        expected_relkind = "v" if self.object_type.casefold() == "view" else self.object_type
        if observed is not None:
            if observed.schema != metadata.schema or observed.name != metadata.name:
                errors.append("observed view identity disagrees with source metadata")
            if observed.relkind != expected_relkind:
                errors.append(
                    f"observed relkind expected {expected_relkind!r}, got {observed.relkind!r}"
                )
        if self.view_approval is not None:
            if observed is None:
                errors.append("approved source requires the exact live pg_get_viewdef evidence")
            else:
                errors.extend(
                    f"view identity: {difference}"
                    for difference in self.view_approval.differences(observed)
                )
                catalog_digest = metadata.observed_catalog_columns_sha256
                if (
                    not isinstance(catalog_digest, str)
                    or len(catalog_digest) != 64
                    or catalog_digest != catalog_digest.lower()
                    or any(character not in "0123456789abcdef" for character in catalog_digest)
                ):
                    errors.append(
                        "approved source requires the complete live catalogue-column digest"
                    )
                elif catalog_digest != self.view_approval.catalog_columns_sha256:
                    errors.append("catalogue-column digest does not match the BRERC approval")
                else:
                    observed_identity = observed.identity_sha256(
                        self.columns_sha256(),
                        catalog_digest,
                    )
                    if observed_identity != self.view_approval.identity_sha256:
                        errors.append(
                            "observed view-identity digest does not match the BRERC approval"
                        )

        counts = Counter(column.name for column in metadata.columns)
        duplicates = sorted(name for name, count in counts.items() if count > 1)
        if duplicates:
            errors.append(f"duplicate column metadata: {duplicates}")

        actual = {column.name: column for column in metadata.columns}
        expected = {column.name: column for column in self.columns}
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        if missing:
            errors.append(f"missing confirmed columns: {missing}")
        if unexpected:
            errors.append(f"unexpected columns: {unexpected}")

        expected_order = [column.name for column in self.columns]
        actual_order = [column.name for column in metadata.columns]
        if not missing and not unexpected and actual_order != expected_order:
            errors.append("column order differs from the versioned view definition")

        for name, spec in expected.items():
            if name in actual:
                differences = spec.differences(actual[name])
                if differences:
                    errors.append(f"{name}: {'; '.join(differences)}")
        return errors


def _normalise_type(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def varchar(name: str, length: int) -> ColumnSpec:
    return ColumnSpec(name, "character varying", character_maximum_length=length)


def date(name: str) -> ColumnSpec:
    return ColumnSpec(name, "date")


def text(name: str) -> ColumnSpec:
    return ColumnSpec(name, "text")


def numeric(name: str, precision: int, scale: int) -> ColumnSpec:
    return ColumnSpec(name, "numeric", numeric_precision=precision, numeric_scale=scale)


BRERC_MAIN_DATA_DASH_COLUMNS: tuple[ColumnSpec, ...] = (
    varchar("scientific_name", 120),
    varchar("common_name", 120),
    varchar("grid_ref", 25),
    varchar("place", 254),
    varchar("date_of_record", 50),
    varchar("abundance", 35),
    varchar("sex_stage", 45),
    varchar("record_type", 55),
    date("start_date"),
    varchar("species_no", 20),
    date("precise_date"),
    varchar("vague_date", 35),
    varchar("vitality", 15),
    varchar("digital_or_paper", 10),
    date("date_entered"),
    varchar("bnes", 4),
    varchar("bcc", 3),
    varchar("sglos", 4),
    varchar("nsom", 4),
    varchar("year_end", 5),
    varchar("year_start", 5),
    date("end_date"),
    varchar("comments", 254),
    varchar("source", 50),
    varchar("bliss", 100),
    varchar("taxa_brerc", 60),
    numeric("unique_no", 13, 2),
    varchar("licence", 1),
    varchar("sensitive", 4),
    varchar("taxo_id", 20),
    numeric("easting", 13, 2),
    numeric("northing", 13, 2),
    text("taxa_nb"),
    text("brerc_status"),
    text("national_status"),
    text("legal_protection"),
    text("bap"),
    text("rspb"),
    text("brerc_notable"),
)

PENDING_DATE_MDB_MODIFIED = date("date_mdb_modified")

BRERC_MAIN_DATA_DASH = SourceContract(
    version="brerc-main-data-dash-2026-07-31",
    schema="dashboard",
    name="main_data_dash",
    object_type="view",
    columns=BRERC_MAIN_DATA_DASH_COLUMNS,
    record_id_column="unique_no",
    sensitivity_column="sensitive",
    pipeline_mapping=(
        ("record_id", "unique_no"),
        ("species_id", "species_no"),
        ("scientific_name", "scientific_name"),
        ("grid_ref", "grid_ref"),
        ("year", "year_end"),
        ("common_name", "common_name"),
        ("place", None),
        ("abundance", "abundance"),
        ("record_type", "record_type"),
        ("verified", None),
        ("source", None),
        ("licence", "licence"),
        ("sensitivity", "sensitive"),
    ),
    row_sensitive_resolution_metres=1000,
    non_sensitive_values=frozenset({"no"}),
    allowed_modes=frozenset({LoadMode.INITIAL}),
    client_reference_document_sha256=(
        "567f614773df83609c3dd1a63f6b5d44fd98406d67ef60f2e5eb66f1fcebb72d"
    ),
    incremental_blockers=(
        "updated view DDL containing date_mdb_modified has not been received",
        "date_mdb_modified is absent from the confirmed 39-column schema",
        "date_mdb_modified nullability and update semantics are unconfirmed",
        "unique_no has no confirmed non-null, unique and never-reused guarantee",
        "date-only watermarks require an inclusive overlap and idempotent upserts",
        "deletions, withdrawals and source-key changes have no confirmed signal",
        "lookup-table changes may alter the joined view without changing date_mdb_modified",
        "the incremental coordinator does not yet build a complete replacement candidate from "
        "an approved change window and deletion signal",
        "the inclusive watermark and affected-aggregate protocol has not been approved or "
        "validated against a revised live BRERC view",
    ),
    release_blockers=(
        "the destination publication writer and atomic loader are not present in the "
        "publication-core port",
        "BRERC-approved species dictionary and its exact digest have not been received",
        "BRERC-approved live view version and identity envelope have not been received",
        "BRERC-approved source database/service identity and extraction role have not been "
        "independently pinned; connector configuration labels are deployment assertions only",
        "BRERC-approved automatic initial source-count and large-drop bounds have not been received",
        "the destination loader has not been accepted at BRERC's approximately five-million-row "
        "scale, including activation duration, disk capacity and failed-candidate retention",
    ),
)
