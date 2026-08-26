"""Versioned identity and approval for a PostgreSQL source view.

The original source contract carried a naked 64-character checksum.  That was
enough to compare two strings, but not enough to say what was hashed, who
approved it, or whether the observed PostgreSQL object had the reviewed owner
and security options.

This module deliberately keeps three concepts separate:

* a client-supplied document is provenance, not live database evidence;
* ``pg_get_viewdef(oid, false)`` is the live SQL identity;
* a named BRERC approval binds that identity to a client-issued version.

No SQL formatting or Unicode normalisation is performed.  One changed byte,
including whitespace, produces a different digest and therefore fails closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

#: Bumped to v2 on 15 August 2026 when quote_all_identifiers moved from ON to
#: OFF in the fixed session (see brerc_source.postgres.FIXED_SESSION_SQL). That
#: GUC changes how PostgreSQL renders both pg_get_viewdef() and
#: information_schema.columns.data_type, so a definition digest taken under the
#: old profile is not comparable with one taken under the new profile.  The
#: version suffix makes any earlier approval fail closed and be re-captured
#: rather than silently compared across two different rendering rules.
VIEW_DEFINITION_DIGEST_PROFILE = "postgres-pg-get-viewdef-oid-false-exact-utf8-fixed-gucs-sha256-v2"
VIEW_IDENTITY_PROFILE = "brerc-postgres-view-identity-sha256-v1"
VIEW_CAPTURE_EVIDENCE_PROFILE = "brerc-view-capture-canonical-json-sha256-v1"
VIEW_CAPTURE_ARTIFACT_FORMAT = "brerc-view-capture/v1"
VIEW_APPROVAL_ARTIFACT_FORMAT = "brerc-view-approval/v1"

EXPECTED_CAPTURE_SESSION = {
    "search_path": "pg_catalog",
    "client_encoding": "UTF8",
    # Must stay OFF.  format_type() honours this GUC, and
    # information_schema.columns.data_type is produced by format_type(), so ON
    # reports `date` as `"date"` and `text` as `"text"`.
    "quote_all_identifiers": "off",
    "standard_conforming_strings": "on",
    "DateStyle": "ISO, YMD",
    "IntervalStyle": "postgres",
    "TimeZone": "UTC",
    "extra_float_digits": "3",
    "bytea_output": "hex",
    "lc_numeric": "C",
}


class ViewIdentityError(ValueError):
    """A captured or approved view identity is incomplete or inconsistent."""


def _require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ViewIdentityError(f"{field_name} must be a non-blank string")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ViewIdentityError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def postgres_major_version(server_version_num: object) -> int:
    """Return the major version encoded by PostgreSQL ``server_version_num``."""
    if isinstance(server_version_num, bool) or not isinstance(server_version_num, int):
        raise ViewIdentityError("postgres_server_version_num must be an integer")
    if server_version_num < 90000:
        raise ViewIdentityError("unsupported PostgreSQL server_version_num")
    return server_version_num // 10000


def _parse_utc_timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ViewIdentityError(f"{field_name} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ViewIdentityError(f"{field_name} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ViewIdentityError(f"{field_name} must be in UTC")
    return parsed


def view_definition_sha256(definition: object) -> str:
    """Hash the exact UTF-8 bytes returned by ``pg_get_viewdef(oid, false)``.

    Do not trim, add a semicolon/newline, reindent, case-fold or normalise.  The
    PostgreSQL result itself is the byte-level contract.
    """
    if not isinstance(definition, str) or not definition:
        raise ViewIdentityError("view definition must be a non-empty string")
    if "\x00" in definition:
        raise ViewIdentityError("view definition must not contain a NUL character")
    try:
        encoded = definition.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ViewIdentityError("view definition is not valid UTF-8 text") from exc
    return hashlib.sha256(encoded).hexdigest()


def source_columns_sha256(columns: object) -> str:
    """Hash the ordered, public source-column contract representation."""
    if not isinstance(columns, list | tuple):
        raise ViewIdentityError("columns must be an ordered list or tuple")
    canonical = json.dumps(
        columns,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def capture_evidence_sha256(document: object) -> str:
    """Hash every field in one validated raw capture as canonical JSON.

    This is provenance for the approval event, not the live technical identity:
    a later runtime observation will necessarily have a new timestamp and may
    have a different relation OID while still describing the approved view.
    """
    if not isinstance(document, dict):
        raise ViewIdentityError("capture evidence must be a JSON object")
    try:
        canonical = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ViewIdentityError("capture evidence is not canonical JSON data") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _identity_document(
    *,
    schema: str,
    name: str,
    relkind: str,
    postgres_server_version_num: int,
    owner: str,
    reloptions: tuple[str, ...],
    definition_sha256: str,
    contract_columns_sha256: str,
    catalog_columns_sha256: str,
) -> dict[str, object]:
    return {
        "profile": VIEW_IDENTITY_PROFILE,
        "schema": schema,
        "name": name,
        "relkind": relkind,
        "postgresServerVersionNum": postgres_server_version_num,
        "postgresMajor": postgres_major_version(postgres_server_version_num),
        "owner": owner,
        "reloptions": list(reloptions),
        "definitionProfile": VIEW_DEFINITION_DIGEST_PROFILE,
        "definitionSha256": definition_sha256,
        "contractColumnsSha256": contract_columns_sha256,
        "catalogColumnsSha256": catalog_columns_sha256,
    }


def _identity_sha256(document: dict[str, object]) -> str:
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ObservedViewDefinition:
    """Evidence captured directly from PostgreSQL in the extraction snapshot.

    ``definition`` is excluded from ``repr`` so normal logging cannot disclose
    BRERC's internal SQL.  Only its digests are carried into release evidence.
    """

    schema: str
    name: str
    relkind: str
    definition: str = field(repr=False)
    postgres_server_version_num: int
    owner: str
    reloptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonblank(self.schema, "schema")
        _require_nonblank(self.name, "name")
        if self.relkind != "v":
            raise ViewIdentityError("source object must be an ordinary PostgreSQL view (relkind v)")
        view_definition_sha256(self.definition)
        postgres_major_version(self.postgres_server_version_num)
        _require_nonblank(self.owner, "owner")
        if not isinstance(self.reloptions, tuple):
            raise ViewIdentityError("reloptions must be a sorted tuple")
        if any(not isinstance(option, str) or not option for option in self.reloptions):
            raise ViewIdentityError("reloptions must contain only non-blank strings")
        if tuple(sorted(set(self.reloptions))) != self.reloptions:
            raise ViewIdentityError("reloptions must be unique and sorted")

    @property
    def definition_sha256(self) -> str:
        return view_definition_sha256(self.definition)

    @property
    def postgres_major(self) -> int:
        return postgres_major_version(self.postgres_server_version_num)

    def identity_document(
        self,
        contract_columns_sha256: str,
        catalog_columns_sha256: str,
    ) -> dict[str, object]:
        _require_sha256(contract_columns_sha256, "contract_columns_sha256")
        _require_sha256(catalog_columns_sha256, "catalog_columns_sha256")
        return _identity_document(
            schema=self.schema,
            name=self.name,
            relkind=self.relkind,
            postgres_server_version_num=self.postgres_server_version_num,
            owner=self.owner,
            reloptions=self.reloptions,
            definition_sha256=self.definition_sha256,
            contract_columns_sha256=contract_columns_sha256,
            catalog_columns_sha256=catalog_columns_sha256,
        )

    def identity_sha256(
        self,
        contract_columns_sha256: str,
        catalog_columns_sha256: str,
    ) -> str:
        return _identity_sha256(
            self.identity_document(contract_columns_sha256, catalog_columns_sha256)
        )


@dataclass(frozen=True)
class CapturedContractColumn:
    """Immutable reduced column evidence used by the reviewed source contract."""

    name: str
    data_type: str
    character_maximum_length: int | None
    numeric_precision: int | None
    numeric_scale: int | None

    def to_document(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.data_type,
            "length": self.character_maximum_length,
            "precision": self.numeric_precision,
            "scale": self.numeric_scale,
        }


@dataclass(frozen=True)
class ViewCaptureEvidence:
    """Validated result of the read-only PostgreSQL catalogue capture query."""

    captured_at_utc: str
    observation: ObservedViewDefinition
    contract_columns: tuple[CapturedContractColumn, ...]
    catalog_columns_sha256_value: str
    capture_sha256: str

    def __post_init__(self) -> None:
        _parse_utc_timestamp(self.captured_at_utc, "captured_at_utc")
        if not isinstance(self.contract_columns, tuple) or not self.contract_columns:
            raise ViewIdentityError("contract_columns must be a non-empty tuple")
        source_columns_sha256(self.columns_document)
        _require_sha256(
            self.catalog_columns_sha256_value,
            "catalog_columns_sha256_value",
        )
        _require_sha256(self.capture_sha256, "capture_sha256")

    @property
    def columns_document(self) -> tuple[dict[str, object], ...]:
        """Fresh serialisable documents; callers cannot mutate stored evidence."""
        return tuple(column.to_document() for column in self.contract_columns)

    @property
    def columns_sha256(self) -> str:
        return source_columns_sha256(self.columns_document)

    @property
    def catalog_columns_sha256(self) -> str:
        return self.catalog_columns_sha256_value

    @property
    def identity_sha256(self) -> str:
        return self.observation.identity_sha256(
            self.columns_sha256,
            self.catalog_columns_sha256,
        )

    def pending_approval_document(self) -> dict[str, object]:
        """Return a sanitised template.  It deliberately cannot grant approval."""
        return {
            "artifactFormat": VIEW_APPROVAL_ARTIFACT_FORMAT,
            "status": "pending-brerc-approval",
            "sourceVersion": None,
            "sourceEnvironment": None,
            "clientReferenceDocumentSha256": None,
            "source": {
                "schema": self.observation.schema,
                "name": self.observation.name,
                "relkind": self.observation.relkind,
                "postgresServerVersionNum": (self.observation.postgres_server_version_num),
                "postgresMajor": self.observation.postgres_major,
                "owner": self.observation.owner,
                "reloptions": list(self.observation.reloptions),
                "contractColumnsSha256": self.columns_sha256,
                "catalogColumnsSha256": self.catalog_columns_sha256,
            },
            "digest": {
                "profile": VIEW_DEFINITION_DIGEST_PROFILE,
                "definitionSha256": self.observation.definition_sha256,
                "identityProfile": VIEW_IDENTITY_PROFILE,
                "identitySha256": self.identity_sha256,
                "captureProfile": VIEW_CAPTURE_EVIDENCE_PROFILE,
                "captureEvidenceSha256": self.capture_sha256,
            },
            "capture": {"capturedAtUtc": self.captured_at_utc},
            "approval": {
                "approvedBy": None,
                "approverRole": None,
                "approverOrganisation": None,
                "approvedOn": None,
                "reviewExpiresOn": None,
                "evidenceReference": None,
            },
        }

    @classmethod
    def from_document(cls, document: object) -> ViewCaptureEvidence:
        if not isinstance(document, dict):
            raise ViewIdentityError("capture artifact must be a JSON object")
        _require_exact_keys(
            document,
            {
                "artifact_format",
                "captured_at_utc",
                "postgres",
                "session",
                "object",
                "view_definition",
                "view_definition_utf8_hex",
                "columns",
            },
            "capture artifact",
        )
        if document["artifact_format"] != VIEW_CAPTURE_ARTIFACT_FORMAT:
            raise ViewIdentityError("unsupported capture artifact format")
        postgres = _require_dict(document["postgres"], "postgres")
        session = _require_dict(document["session"], "session")
        source_object = _require_dict(document["object"], "object")
        _require_exact_keys(
            postgres,
            {
                "database",
                "server_version",
                "server_version_num",
                "server_major",
                "server_encoding",
                "captured_by_database_role",
            },
            "postgres",
        )
        _require_exact_keys(session, set(EXPECTED_CAPTURE_SESSION), "session")
        if session != EXPECTED_CAPTURE_SESSION:
            differences = [
                f"{key} expected {expected!r}, got {session.get(key)!r}"
                for key, expected in EXPECTED_CAPTURE_SESSION.items()
                if session.get(key) != expected
            ]
            raise ViewIdentityError(
                "capture session does not match the digest profile: " + "; ".join(differences)
            )
        _require_exact_keys(
            source_object,
            {
                "schema",
                "name",
                "qualified_name",
                "relation_oid",
                "relkind",
                "relpersistence",
                "owner",
                "reloptions",
            },
            "object",
        )
        _require_nonblank(postgres["database"], "postgres.database")
        _require_nonblank(postgres["server_version"], "postgres.server_version")
        _require_nonblank(
            postgres["captured_by_database_role"],
            "postgres.captured_by_database_role",
        )
        if postgres["server_encoding"] != "UTF8":
            raise ViewIdentityError("capture must use PostgreSQL server encoding UTF8")
        server_version_num = postgres["server_version_num"]
        expected_major = postgres_major_version(server_version_num)
        if postgres["server_major"] != expected_major:
            raise ViewIdentityError("server_major disagrees with server_version_num")
        # Reported field-by-field on purpose. "capture is not for
        # dashboard.main_data_dash" names the expectation but not the mismatch,
        # which leaves an operator holding a rejected capture with no way to tell
        # whether the schema, the relation or the qualified name is wrong. These
        # three values are catalogue identifiers, never record content, so naming
        # them cannot disclose client data.
        identity_mismatches = [
            f"{field}={source_object[field]!r} (expected {expected!r})"
            for field, expected in (
                ("schema", "dashboard"),
                ("name", "main_data_dash"),
                ("qualified_name", "dashboard.main_data_dash"),
            )
            if source_object[field] != expected
        ]
        if identity_mismatches:
            raise ViewIdentityError(
                "capture is not for dashboard.main_data_dash: " + "; ".join(identity_mismatches)
            )
        if source_object["relpersistence"] != "p":
            raise ViewIdentityError("source view must be a permanent PostgreSQL relation")
        relation_oid = source_object["relation_oid"]
        if isinstance(relation_oid, bool) or not isinstance(relation_oid, int) or relation_oid <= 0:
            raise ViewIdentityError("relation_oid must be a positive integer")
        reloptions_raw = source_object["reloptions"]
        if not isinstance(reloptions_raw, list):
            raise ViewIdentityError("object.reloptions must be a JSON array")

        definition = document["view_definition"]
        definition_hex = document["view_definition_utf8_hex"]
        if not isinstance(definition_hex, str) or definition_hex != definition_hex.lower():
            raise ViewIdentityError("view_definition_utf8_hex must be lowercase hexadecimal")
        try:
            definition_bytes = bytes.fromhex(definition_hex)
            decoded_definition = definition_bytes.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ViewIdentityError("view_definition_utf8_hex is not valid UTF-8 bytes") from exc
        if decoded_definition != definition or definition_bytes.hex() != definition_hex:
            raise ViewIdentityError(
                "view_definition text and view_definition_utf8_hex do not match exactly"
            )

        raw_columns = document["columns"]
        if not isinstance(raw_columns, list) or not raw_columns:
            raise ViewIdentityError("columns must be a non-empty JSON array")
        columns: list[CapturedContractColumn] = []
        expected_column_keys = {
            "ordinal_position",
            "column_name",
            "data_type",
            "udt_schema",
            "udt_name",
            "character_maximum_length",
            "numeric_precision",
            "numeric_scale",
            "is_nullable",
            "collation_schema",
            "collation_name",
        }
        for index, raw_column in enumerate(raw_columns, start=1):
            column = _require_dict(raw_column, f"columns[{index - 1}]")
            _require_exact_keys(column, expected_column_keys, f"columns[{index - 1}]")
            if (
                isinstance(column["ordinal_position"], bool)
                or not isinstance(column["ordinal_position"], int)
                or column["ordinal_position"] != index
            ):
                raise ViewIdentityError("column ordinals must be contiguous and start at one")
            _require_nonblank(column["column_name"], "column_name")
            _require_nonblank(column["data_type"], "data_type")
            _require_nonblank(column["udt_schema"], "udt_schema")
            _require_nonblank(column["udt_name"], "udt_name")
            if column["is_nullable"] not in {"YES", "NO"}:
                raise ViewIdentityError("is_nullable must be exactly YES or NO")
            collation_schema = column["collation_schema"]
            collation_name = column["collation_name"]
            if (collation_schema is None) != (collation_name is None):
                raise ViewIdentityError(
                    "collation_schema and collation_name must both be null or both be set"
                )
            if collation_schema is not None:
                _require_nonblank(collation_schema, "collation_schema")
                _require_nonblank(collation_name, "collation_name")
            for key in (
                "character_maximum_length",
                "numeric_precision",
                "numeric_scale",
            ):
                value = column[key]
                if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                    raise ViewIdentityError(f"{key} must be an integer or null")
                if value is not None and value < 0:
                    raise ViewIdentityError(f"{key} must not be negative")
            columns.append(
                CapturedContractColumn(
                    name=column["column_name"],
                    data_type=column["data_type"],
                    character_maximum_length=column["character_maximum_length"],
                    numeric_precision=column["numeric_precision"],
                    numeric_scale=column["numeric_scale"],
                )
            )

        observation = ObservedViewDefinition(
            schema=source_object["schema"],
            name=source_object["name"],
            relkind=source_object["relkind"],
            definition=decoded_definition,
            postgres_server_version_num=server_version_num,
            owner=source_object["owner"],
            reloptions=tuple(reloptions_raw),
        )
        return cls(
            captured_at_utc=document["captured_at_utc"],
            observation=observation,
            contract_columns=tuple(columns),
            catalog_columns_sha256_value=source_columns_sha256(raw_columns),
            capture_sha256=capture_evidence_sha256(document),
        )


_PLACEHOLDER_VALUES = frozenset({"tbd", "pending", "unknown", "none", "n/a", "placeholder"})


@dataclass(frozen=True)
class ViewDefinitionApproval:
    """Named BRERC approval of one observed PostgreSQL view identity."""

    source_version: str
    source_environment: str
    client_reference_document_sha256: str | None
    schema: str
    name: str
    relkind: str
    postgres_server_version_num: int
    owner: str
    reloptions: tuple[str, ...]
    columns_sha256: str
    catalog_columns_sha256: str
    definition_sha256: str
    capture_evidence_sha256: str
    approved_by: str
    approver_role: str
    approver_organisation: str
    captured_at_utc: str
    approved_on: str
    evidence_reference: str
    review_expires_on: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "source_version",
            "source_environment",
            "schema",
            "name",
            "owner",
            "approved_by",
            "approver_role",
            "approver_organisation",
            "approved_on",
            "evidence_reference",
        ):
            value = _require_nonblank(getattr(self, field_name), field_name)
            if value.strip().casefold() in _PLACEHOLDER_VALUES:
                raise ViewIdentityError(f"{field_name} must not be a placeholder")
        if self.relkind != "v":
            raise ViewIdentityError("approved object must be an ordinary PostgreSQL view")
        postgres_major_version(self.postgres_server_version_num)
        if not isinstance(self.reloptions, tuple):
            raise ViewIdentityError("reloptions must be a sorted tuple")
        if tuple(sorted(set(self.reloptions))) != self.reloptions:
            raise ViewIdentityError("reloptions must be unique and sorted")
        _require_sha256(self.columns_sha256, "columns_sha256")
        _require_sha256(self.catalog_columns_sha256, "catalog_columns_sha256")
        _require_sha256(self.definition_sha256, "definition_sha256")
        _require_sha256(self.capture_evidence_sha256, "capture_evidence_sha256")
        if self.client_reference_document_sha256 is not None:
            _require_sha256(
                self.client_reference_document_sha256,
                "client_reference_document_sha256",
            )
        approved = self._parse_date(self.approved_on, "approved_on")
        if approved > date.today():
            raise ViewIdentityError("approved_on must not be in the future")
        if self.review_expires_on is not None:
            expires = self._parse_date(self.review_expires_on, "review_expires_on")
            if expires < approved:
                raise ViewIdentityError("review_expires_on must not precede approved_on")
        captured = _parse_utc_timestamp(self.captured_at_utc, "captured_at_utc")
        if captured > datetime.now(timezone.utc):
            raise ViewIdentityError("captured_at_utc must not be in the future")
        if captured.date() > approved:
            raise ViewIdentityError("captured_at_utc must not be later than approved_on")

    @property
    def postgres_major(self) -> int:
        return postgres_major_version(self.postgres_server_version_num)

    @staticmethod
    def _parse_date(value: str, field_name: str) -> date:
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ViewIdentityError(f"{field_name} must be an ISO date (YYYY-MM-DD)") from exc

    def is_current(self, *, on: date | None = None) -> bool:
        if self.review_expires_on is None:
            return True
        return (on or date.today()) <= self._parse_date(
            self.review_expires_on,
            "review_expires_on",
        )

    def assert_current(self) -> None:
        if not self.is_current():
            raise ViewIdentityError(f"view-definition approval expired on {self.review_expires_on}")

    def identity_document(self) -> dict[str, object]:
        return _identity_document(
            schema=self.schema,
            name=self.name,
            relkind=self.relkind,
            postgres_server_version_num=self.postgres_server_version_num,
            owner=self.owner,
            reloptions=self.reloptions,
            definition_sha256=self.definition_sha256,
            contract_columns_sha256=self.columns_sha256,
            catalog_columns_sha256=self.catalog_columns_sha256,
        )

    @property
    def identity_sha256(self) -> str:
        return _identity_sha256(self.identity_document())

    def differences(self, observed: ObservedViewDefinition) -> tuple[str, ...]:
        differences: list[str] = []
        comparisons = (
            ("schema", self.schema, observed.schema),
            ("name", self.name, observed.name),
            ("relkind", self.relkind, observed.relkind),
            (
                "PostgreSQL server_version_num",
                self.postgres_server_version_num,
                observed.postgres_server_version_num,
            ),
            ("owner", self.owner, observed.owner),
            ("reloptions", self.reloptions, observed.reloptions),
            ("definition SHA-256", self.definition_sha256, observed.definition_sha256),
        )
        for label, expected, actual in comparisons:
            if expected != actual:
                differences.append(f"{label} expected {expected!r}, got {actual!r}")
        return tuple(differences)

    def to_document(self) -> dict[str, object]:
        return {
            "artifactFormat": VIEW_APPROVAL_ARTIFACT_FORMAT,
            "status": "approved",
            "sourceVersion": self.source_version,
            "sourceEnvironment": self.source_environment,
            "clientReferenceDocumentSha256": self.client_reference_document_sha256,
            "source": {
                "schema": self.schema,
                "name": self.name,
                "relkind": self.relkind,
                "postgresServerVersionNum": self.postgres_server_version_num,
                "postgresMajor": self.postgres_major,
                "owner": self.owner,
                "reloptions": list(self.reloptions),
                "contractColumnsSha256": self.columns_sha256,
                "catalogColumnsSha256": self.catalog_columns_sha256,
            },
            "digest": {
                "profile": VIEW_DEFINITION_DIGEST_PROFILE,
                "definitionSha256": self.definition_sha256,
                "identityProfile": VIEW_IDENTITY_PROFILE,
                "identitySha256": self.identity_sha256,
                "captureProfile": VIEW_CAPTURE_EVIDENCE_PROFILE,
                "captureEvidenceSha256": self.capture_evidence_sha256,
            },
            "capture": {
                "capturedAtUtc": self.captured_at_utc,
            },
            "approval": {
                "approvedBy": self.approved_by,
                "approverRole": self.approver_role,
                "approverOrganisation": self.approver_organisation,
                "approvedOn": self.approved_on,
                "reviewExpiresOn": self.review_expires_on,
                "evidenceReference": self.evidence_reference,
            },
        }

    @classmethod
    def from_document(cls, document: object) -> ViewDefinitionApproval:
        if not isinstance(document, dict):
            raise ViewIdentityError("approval artifact must be a JSON object")
        _require_exact_keys(
            document,
            {
                "artifactFormat",
                "status",
                "sourceVersion",
                "sourceEnvironment",
                "clientReferenceDocumentSha256",
                "source",
                "digest",
                "capture",
                "approval",
            },
            "approval artifact",
        )
        if document["artifactFormat"] != VIEW_APPROVAL_ARTIFACT_FORMAT:
            raise ViewIdentityError("unsupported approval artifact format")
        if document["status"] != "approved":
            raise ViewIdentityError("view identity is not BRERC-approved")
        source = _require_dict(document["source"], "source")
        digest = _require_dict(document["digest"], "digest")
        capture = _require_dict(document["capture"], "capture")
        approval = _require_dict(document["approval"], "approval")
        _require_exact_keys(
            source,
            {
                "schema",
                "name",
                "relkind",
                "postgresServerVersionNum",
                "postgresMajor",
                "owner",
                "reloptions",
                "contractColumnsSha256",
                "catalogColumnsSha256",
            },
            "source",
        )
        _require_exact_keys(
            digest,
            {
                "profile",
                "definitionSha256",
                "identityProfile",
                "identitySha256",
                "captureProfile",
                "captureEvidenceSha256",
            },
            "digest",
        )
        _require_exact_keys(capture, {"capturedAtUtc"}, "capture")
        _require_exact_keys(
            approval,
            {
                "approvedBy",
                "approverRole",
                "approverOrganisation",
                "approvedOn",
                "reviewExpiresOn",
                "evidenceReference",
            },
            "approval",
        )
        if digest["profile"] != VIEW_DEFINITION_DIGEST_PROFILE:
            raise ViewIdentityError("unsupported view-definition digest profile")
        if digest["identityProfile"] != VIEW_IDENTITY_PROFILE:
            raise ViewIdentityError("unsupported view-identity profile")
        if digest["captureProfile"] != VIEW_CAPTURE_EVIDENCE_PROFILE:
            raise ViewIdentityError("unsupported capture-evidence digest profile")
        reloptions_raw = source["reloptions"]
        if not isinstance(reloptions_raw, list):
            raise ViewIdentityError("source.reloptions must be a JSON array")
        result = cls(
            source_version=document["sourceVersion"],
            source_environment=document["sourceEnvironment"],
            client_reference_document_sha256=document["clientReferenceDocumentSha256"],
            schema=source["schema"],
            name=source["name"],
            relkind=source["relkind"],
            postgres_server_version_num=source["postgresServerVersionNum"],
            owner=source["owner"],
            reloptions=tuple(reloptions_raw),
            columns_sha256=source["contractColumnsSha256"],
            catalog_columns_sha256=source["catalogColumnsSha256"],
            definition_sha256=digest["definitionSha256"],
            capture_evidence_sha256=digest["captureEvidenceSha256"],
            approved_by=approval["approvedBy"],
            approver_role=approval["approverRole"],
            approver_organisation=approval["approverOrganisation"],
            captured_at_utc=capture["capturedAtUtc"],
            approved_on=approval["approvedOn"],
            review_expires_on=approval["reviewExpiresOn"],
            evidence_reference=approval["evidenceReference"],
        )
        supplied_identity = _require_sha256(digest["identitySha256"], "identitySha256")
        if source["postgresMajor"] != result.postgres_major:
            raise ViewIdentityError("postgresMajor disagrees with postgresServerVersionNum")
        if supplied_identity != result.identity_sha256:
            raise ViewIdentityError("identitySha256 does not match the approved identity fields")
        return result


def _require_dict(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ViewIdentityError(f"{field_name} must be a JSON object")
    return value


def _require_exact_keys(document: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(document)
    if actual != expected:
        raise ViewIdentityError(
            f"{label} keys differ; missing {sorted(expected - actual)!r}, "
            f"unexpected {sorted(actual - expected)!r}"
        )
