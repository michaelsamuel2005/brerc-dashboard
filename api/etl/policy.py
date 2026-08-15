"""BRERC's publication policy, as an explicit versioned artefact.

WHY A POLICY OBJECT RATHER THAN CONSTANTS
-----------------------------------------
Earlier versions hard-coded the decisions that determine what the public sees:
a 100 m floor, a blanket 10 km for sensitive taxa, place names published,
original record ids published, no suppression. None of those are engineering
choices - they are BRERC's to make, and several are irreversible once published.

So they live here, in a dated object with a named approver. `assert_approved()`
is what a production release must call: it raises until a real approval is
recorded.

THERE IS NO DEFAULT POLICY, ANYWHERE
------------------------------------
`generalise` and `run_pipeline` both require one. A default would mean a caller
who forgot it still got a run - and a silent 100% withhold reads in the report
like a data problem rather than a missing decision.

`UNAPPROVED_POLICY` is the null policy: it names no resolutions BRERC has agreed,
no salt, no place names. It does not merely publish little - `validate()` REFUSES
it, so it cannot run at all. That is deliberate. Choosing what the public sees
must be an act, not an omission. Use `DEVELOPMENT_POLICY` for synthetic-data work
and build a real policy from BRERC's answers for anything else.

THE RESOLUTION SET IS NOT DEFINED HERE
--------------------------------------
It comes from `gridref.PUBLIC_RESOLUTIONS_METRES`, which records what the client
can parse and draw. Restating the tuple here would create a second source of
truth that could silently disagree with the first. A policy may only ever choose
from that set; `validate()` enforces it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from types import MappingProxyType

from .gridref import (
    PUBLIC_MAX_PRECISION_METRES,
    PUBLIC_MIN_PRECISION_METRES,
    PUBLIC_RESOLUTIONS_METRES,
)

#: What to do with a species that cannot be resolved, or that the policy does not
#: cover. "withhold" drops the record; "coarsest" publishes it at the coarsest
#: emittable resolution. Never "ordinary".
UnknownSpeciesAction = str  # "withhold" | "coarsest"

#: Resolutions a policy may choose, finest first. Aliased, not restated - the
#: same tuple object as gridref's, so the two cannot drift apart.
EMITTABLE_RESOLUTIONS_METRES: tuple[int, ...] = PUBLIC_RESOLUTIONS_METRES

FINEST_EMITTABLE_METRES = PUBLIC_MIN_PRECISION_METRES
COARSEST_EMITTABLE_METRES = PUBLIC_MAX_PRECISION_METRES

# A HMAC key is a secret, not a cosmetic salt. Thirty-two UTF-8 bytes matches
# SHA-256's security level and prevents a short, guessable value from being
# mistaken for production protection. Entropy and secret storage still have to
# be supplied operationally; length alone cannot prove either.
MIN_PUBLIC_ID_SECRET_BYTES = 32

# Controlled public provenance labels. Raw source text can contain recorder
# names, addresses or internal references, so it is never copied through.
PUBLIC_SOURCE_LABELS: frozenset[str] = frozenset({"BRERC"})
REQUIRED_APPROVER_ORGANISATION = "BRERC"

# Approval modes distinguish a deliberate decision from an omitted value. For
# example, ``allowed_licence_values=None`` alone cannot tell us whether BRERC
# approved publication without a licence gate or nobody supplied the codebook.
PRECISION_MODES: frozenset[str] = frozenset({"undecided", "approved"})
SUPPRESSION_MODES: frozenset[str] = frozenset({"undecided", "none", "minimum-count"})
LICENSING_MODES: frozenset[str] = frozenset(
    {"undecided", "not-applicable", "all-publication-allow-list"}
)
RECORD_TYPE_SAFETY_MODES: frozenset[str] = frozenset({"undecided", "not-used", "rules"})
ROW_LEVEL_RECORDS_MODES: frozenset[str] = frozenset({"undecided", "aggregates-only", "publish"})
VERIFICATION_PUBLICATION_MODES: frozenset[str] = frozenset({"undecided", "unavailable", "publish"})

# Only one suppression model is implemented. Binding its semantics into the
# approval digest prevents a later code change from silently reinterpreting the
# approved numeric threshold.
SUPPRESSION_SCOPE = "all-otherwise-publishable-records"
SUPPRESSION_COUNT_BASIS = "records"
SUPPRESSION_COHORT = ("species", "year", "cell", "precision")
SUPPRESSION_SURFACES = (
    "map",
    "accessible-cell-table",
    "individual-records-if-enabled",
    "year-series",
    "totals",
)

# The individual-row disclosure envelope is a governance artefact, not merely
# a serializer detail. A field added to the public row must change this schema
# version/allow-list and therefore invalidate the existing BRERC approval.
INDIVIDUAL_RECORD_SCHEMA_VERSION = "brerc-public-record-v1"
INDIVIDUAL_RECORD_BASE_FIELDS = (
    "id",
    "scientificName",
    "commonName",
    "gridRef",
    "precisionMetres",
    "year",
    "source",
)
INDIVIDUAL_RECORD_CONTROLLED_FIELDS = MappingProxyType(
    {
        "place": "publishPlaceNames",
        "abundance": "publishAbundance",
        "recordType": "publishRecordType",
        "verified": "publishRecordVerification",
    }
)


class PolicyNotApproved(RuntimeError):
    """Raised when a production action requires an approved policy."""


class InvalidPolicy(ValueError):
    """Raised when a policy asks for something the client cannot render."""


@dataclass(frozen=True)
class PublicationPolicy:
    """Every decision that changes what the public can see."""

    version: str

    #: Named individual at BRERC who approved this policy. None = NOT APPROVED.
    approved_by: str | None = None
    #: BRERC role in which the named individual has publication authority.
    approver_role: str | None = None
    #: Organisation owning the decision; a production approval must be BRERC's.
    approver_organisation: str | None = None
    #: Retained BRERC-controlled evidence (ticket, signed note or document id).
    evidence_reference: str | None = None
    #: ISO date of approval. None = NOT APPROVED.
    approved_on: str | None = None
    #: ISO date the policy is next due for review.
    review_due: str | None = None
    #: Canonical digest binding the approval metadata to every publication
    #: decision. A copied policy whose rules are changed therefore loses its
    #: approval automatically. This detects accidental/stale reuse; it is not a
    #: substitute for an externally signed governance record.
    approval_digest: str | None = field(default=None, repr=False)

    #: Marks a policy that exists for tests and synthetic-data development. Such
    #: a policy can NEVER report itself approved, whatever else is set on it.
    #: Without this flag a development policy could carry a placeholder approver
    #: string, satisfy `assert_approved()`, and reach a real release.
    development_only: bool = False

    #: ``undecided`` may be used while building a candidate, but it can never be
    #: approved or released. Each alternative records an affirmative decision.
    precision_mode: str = "undecided"
    suppression_mode: str = "undecided"
    licensing_mode: str = "undecided"
    record_type_safety_mode: str = "undecided"
    row_level_records_mode: str = "undecided"
    verification_publication_mode: str = "undecided"

    #: Version and digest of the retained sensitive-species snapshot used at
    #: runtime. These are supplied from sensitivity.py by the deployment policy
    #: builder; policy.py cannot import that module without a circular import.
    sensitive_snapshot_version: str | None = None
    sensitive_snapshot_sha256: str | None = None

    #: Optional digest of a SpeciesDictionary whose identity/sensitivity flags
    #: are allowed to contribute to the gate. Runtime rejects any dictionary
    #: whose digest is absent from, or differs from, the approval envelope.
    species_dictionary_sha256: str | None = None

    #: Resolution for ordinary (non-sensitive) records.
    #: !! Whether BRERC permits 100 m publication of real locations is UNCONFIRMED.
    ordinary_resolution_metres: int = COARSEST_EMITTABLE_METRES

    #: Base map aggregation resolution. Coarser records retain their own square.
    map_cell_resolution_metres: int = 1000

    #: Per-species resolution overrides, keyed by normalised (upper-case) species
    #: id. NBN assigns these per taxon; a blanket figure is a stand-in, not a
    #: policy.
    sensitive_resolution_metres: Mapping[str, int] = field(default_factory=dict)

    #: Fallback for a species known to be sensitive but with no explicit entry.
    default_sensitive_metres: int = COARSEST_EMITTABLE_METRES

    #: Independent floor for an occurrence row explicitly marked sensitive by
    #: the source view. This is deliberately separate from the per-taxon
    #: fallback: BRERC currently describes the view flag as a 1 km rule, while
    #: an individual protected taxon or record type may still require 10 km.
    #: None means no row-level rule has been configured and is only valid when
    #: the source contract contains no row-level sensitivity column.
    row_sensitive_resolution_metres: int | None = None

    #: A species that does not resolve, or is absent from the taxonomy.
    unknown_species_action: UnknownSpeciesAction = "withhold"

    #: Free-text place names. A place can defeat generalisation entirely - a
    #: 10 km square beside "Private garden, 12 Acacia Avenue" is not generalised.
    publish_place_names: bool = False

    #: Controlled attribution used in public record rows. This is a policy
    #: decision, but deliberately limited to reviewed organisational labels;
    #: raw source-view/export text is never eligible.
    public_source_label: str = "BRERC"

    #: Publishing individual occurrence rows is a separate disclosure decision
    #: from publishing aggregated cells. It is off unless BRERC explicitly
    #: approves it; the cell-summary table remains the accessible map equivalent.
    publish_individual_records: bool = False

    #: Optional row-level fields with additional inference risk. These can only
    #: be enabled when individual records themselves are approved.
    publish_abundance: bool = False
    publish_record_type: bool = False
    publish_record_verification: bool = False

    #: Original BRERC record numbers are reversible back to the source row.
    publish_original_record_ids: bool = False

    #: Salt for deriving non-reversible public record ids. Must be set, and kept
    #: out of the repository, before any real release.
    public_id_salt: str | None = field(default=None, repr=False)

    #: Minimum records before a map cell may be published. 1 = no suppression.
    min_records_per_cell: int = 1

    #: Verification verdicts that count as accepted, lower-cased and stripped.
    #: None = use contract.normalise_verified's classification. A set gives BRERC
    #: exact control over a vocabulary the parser would otherwise have to guess.
    accepted_verification_values: frozenset[str] | None = None

    #: Licence values permitting public use, lower-cased and stripped. They are
    #: meaningful only with ``licensing_mode='all-publication-allow-list'``;
    #: that mode gates every public surface before aggregation.
    allowed_licence_values: frozenset[str] | None = None

    #: Values in a mapped row-level sensitivity column that BRERC has explicitly
    #: defined as "not sensitive". Everything else - including null, blank and
    #: an unfamiliar value - is treated as sensitive. The empty default is
    #: deliberately fail-closed; a source-specific policy must opt values in.
    non_sensitive_values: frozenset[str] = frozenset()

    #: Record types requiring coarse treatment regardless of taxon - bat roosts,
    #: badger setts, raptor nests. The reviewed workbook has 47 record types
    #: aligned to ``sensitive=yes`` plus two anomalies requiring BRERC resolution.
    #: Keys are lower-cased.
    sensitive_record_type_metres: Mapping[str, int] = field(default_factory=dict)

    #: Complete approved source vocabulary when record-type rules are active.
    #: Blank and new/unrecognised values are withheld rather than assumed safe.
    record_type_vocabulary: frozenset[str] = frozenset()

    #: What to do with a record whose own resolution is real but unpublishable -
    #: in practice a 2 km tetrad, which the client parser cannot draw.
    #:
    #: False (default): withhold it. We have not been told we may republish it at
    #: a different resolution than the one BRERC recorded.
    #: True: coarsen it up to the next resolution the client CAN draw (2 km ->
    #: 10 km). Strictly coarser than the source, so it cannot disclose more; but
    #: it does present the record at a resolution BRERC did not choose.
    #:
    #: !! REQUIRES BRERC CONFIRMATION - see the PR2 policy questions. !!
    coarsen_unpublishable_resolutions: bool = False

    def __post_init__(self) -> None:
        """Copy, normalise and freeze every policy-controlled vocabulary.

        ``frozen=True`` only prevents assigning a new attribute; it does not
        freeze a caller-owned dict. Without these defensive copies an approved
        policy could change after approval, and mixed-case keys could silently
        miss the lookup they were meant to protect.
        """
        if not isinstance(self.version, str) or not self.version.strip():
            raise InvalidPolicy("policy version must be a non-blank string")
        if self.version != self.version.strip():
            raise InvalidPolicy("policy version must not have surrounding whitespace")
        if self.public_id_salt is not None and not isinstance(self.public_id_salt, str):
            raise InvalidPolicy("public_id_salt must be a string supplied by a secret store")

        if not isinstance(self.sensitive_resolution_metres, Mapping):
            raise InvalidPolicy("sensitive_resolution_metres must be a mapping")
        if not isinstance(self.sensitive_record_type_metres, Mapping):
            raise InvalidPolicy("sensitive_record_type_metres must be a mapping")

        species_rules: dict[str, int] = {}
        for raw_key, metres in self.sensitive_resolution_metres.items():
            # Source species ids are identifiers, not numbers. Requiring text
            # prevents YAML/Excel coercion from turning 1234 into 1234.0 (or
            # dropping a leading zero), which would silently miss the source's
            # canonical "1234" key and disable a protection rule.
            if not isinstance(raw_key, str):
                raise InvalidPolicy(
                    "sensitive species rule keys must be quoted strings; numeric "
                    "keys can change identifier spelling and fail open"
                )
            key = raw_key.strip().upper()
            if not key:
                raise InvalidPolicy("sensitive species rule keys must not be blank")
            if key in species_rules:
                raise InvalidPolicy(
                    f"duplicate sensitive species rule after normalisation: {key!r}"
                )
            species_rules[key] = metres

        record_type_rules: dict[str, int] = {}
        for raw_key, metres in self.sensitive_record_type_metres.items():
            if not isinstance(raw_key, str):
                raise InvalidPolicy("sensitive record-type rule keys must be strings")
            key = raw_key.strip().casefold()
            if not key:
                raise InvalidPolicy("sensitive record-type rule keys must not be blank")
            if key in record_type_rules:
                raise InvalidPolicy(
                    f"duplicate sensitive record-type rule after normalisation: {key!r}"
                )
            record_type_rules[key] = metres

        def vocabulary(values: frozenset[str], label: str) -> frozenset[str]:
            if not isinstance(values, set | frozenset):
                raise InvalidPolicy(
                    f"{label} must be a set/frozenset of strings, not a scalar or list"
                )
            if any(not isinstance(value, str) for value in values):
                raise InvalidPolicy(f"{label} must contain strings only")
            normalised_values = [value.strip().casefold() for value in values]
            if "" in normalised_values:
                raise InvalidPolicy(f"{label} must not contain null or blank values")
            normalised = frozenset(normalised_values)
            if len(normalised) != len(values):
                raise InvalidPolicy(f"{label} contains duplicates after normalisation")
            return normalised

        object.__setattr__(
            self,
            "sensitive_resolution_metres",
            MappingProxyType(species_rules),
        )
        object.__setattr__(
            self,
            "sensitive_record_type_metres",
            MappingProxyType(record_type_rules),
        )
        object.__setattr__(
            self,
            "non_sensitive_values",
            vocabulary(self.non_sensitive_values, "non_sensitive_values"),
        )
        object.__setattr__(
            self,
            "record_type_vocabulary",
            vocabulary(self.record_type_vocabulary, "record_type_vocabulary"),
        )
        if self.accepted_verification_values is not None:
            object.__setattr__(
                self,
                "accepted_verification_values",
                vocabulary(
                    self.accepted_verification_values,
                    "accepted_verification_values",
                ),
            )
        if self.allowed_licence_values is not None:
            object.__setattr__(
                self,
                "allowed_licence_values",
                vocabulary(self.allowed_licence_values, "allowed_licence_values"),
            )

    # -- approval -------------------------------------------------------------

    def _decision_document(self) -> dict[str, object]:
        """Canonical, secret-safe representation of every release decision."""
        key_fingerprint = None
        if self.public_id_salt is not None:
            key_fingerprint = hashlib.sha256(self.public_id_salt.encode("utf-8")).hexdigest()
        return {
            "version": self.version,
            "developmentOnly": self.development_only,
            "precisionMode": self.precision_mode,
            "suppressionMode": self.suppression_mode,
            "licensingMode": self.licensing_mode,
            "recordTypeSafetyMode": self.record_type_safety_mode,
            "rowLevelRecordsMode": self.row_level_records_mode,
            "verificationPublicationMode": self.verification_publication_mode,
            "sensitiveSnapshotVersion": self.sensitive_snapshot_version,
            "sensitiveSnapshotSha256": self.sensitive_snapshot_sha256,
            "speciesDictionarySha256": self.species_dictionary_sha256,
            "ordinaryResolutionMetres": self.ordinary_resolution_metres,
            "mapCellResolutionMetres": self.map_cell_resolution_metres,
            "sensitiveResolutionMetres": dict(sorted(self.sensitive_resolution_metres.items())),
            "defaultSensitiveMetres": self.default_sensitive_metres,
            "rowSensitiveResolutionMetres": self.row_sensitive_resolution_metres,
            "unknownSpeciesAction": self.unknown_species_action,
            "publishPlaceNames": self.publish_place_names,
            "publicSourceLabel": self.public_source_label,
            "publishIndividualRecords": self.publish_individual_records,
            "individualRecordSchemaVersion": INDIVIDUAL_RECORD_SCHEMA_VERSION,
            "individualRecordBaseFields": list(INDIVIDUAL_RECORD_BASE_FIELDS),
            "individualRecordControlledFields": dict(INDIVIDUAL_RECORD_CONTROLLED_FIELDS),
            "publishAbundance": self.publish_abundance,
            "publishRecordType": self.publish_record_type,
            "publishRecordVerification": self.publish_record_verification,
            "publishOriginalRecordIds": self.publish_original_record_ids,
            "publicIdScheme": "original" if self.publish_original_record_ids else "hmac-sha256-128",
            "publicIdKeyFingerprint": key_fingerprint,
            "minRecordsPerCell": self.min_records_per_cell,
            "suppressionScope": SUPPRESSION_SCOPE,
            "suppressionCountBasis": SUPPRESSION_COUNT_BASIS,
            "suppressionCohort": list(SUPPRESSION_COHORT),
            "suppressionSurfaces": list(SUPPRESSION_SURFACES),
            "acceptedVerificationValues": (
                None
                if self.accepted_verification_values is None
                else sorted(self.accepted_verification_values)
            ),
            "allowedLicenceValues": (
                None if self.allowed_licence_values is None else sorted(self.allowed_licence_values)
            ),
            "nonSensitiveValues": sorted(self.non_sensitive_values),
            "sensitiveRecordTypeMetres": dict(sorted(self.sensitive_record_type_metres.items())),
            "recordTypeVocabulary": sorted(self.record_type_vocabulary),
            "coarsenUnpublishableResolutions": self.coarsen_unpublishable_resolutions,
        }

    def _expected_approval_digest(self) -> str:
        envelope = {
            "approvedBy": self.approved_by,
            "approverRole": self.approver_role,
            "approverOrganisation": self.approver_organisation,
            "evidenceReference": self.evidence_reference,
            "approvedOn": self.approved_on,
            "reviewDue": self.review_due,
            "decisions": self._decision_document(),
        }
        canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _iso_date(value: object, label: str) -> date:
        """Parse one canonical ISO calendar date without accepting ambiguity."""
        if not isinstance(value, str) or not value.strip():
            raise InvalidPolicy(f"{label} must be a non-blank ISO date (YYYY-MM-DD)")
        text = value.strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise InvalidPolicy(f"{label} must be a valid ISO date (YYYY-MM-DD)") from exc
        if parsed.isoformat() != text:
            raise InvalidPolicy(f"{label} must use canonical YYYY-MM-DD form")
        return parsed

    def _approval_problem(self, *, as_of: date | None = None) -> str | None:
        """Why this policy is not currently approved, or ``None``."""
        if self.development_only:
            return "it is marked development_only"
        undecided = self.undecided_decisions()
        if undecided:
            return "publication decisions remain undecided: " + ", ".join(undecided)
        if (
            self.record_type_safety_mode == "not-used"
            and self.row_sensitive_resolution_metres is None
        ):
            return (
                "record_type_safety_mode='not-used' requires an approved row-level "
                "sensitivity control that already incorporates record type"
            )
        if self.precision_mode == "approved":
            if (
                not isinstance(self.sensitive_snapshot_version, str)
                or not self.sensitive_snapshot_version.strip()
            ):
                return "approved precision has no bound sensitive-species snapshot version"
            if not isinstance(self.sensitive_snapshot_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", self.sensitive_snapshot_sha256
            ):
                return "approved precision has no valid sensitive-species snapshot digest"
        if not isinstance(self.approved_by, str) or not self.approved_by.strip():
            return "it has no non-blank named approver"
        if self.approved_by != self.approved_by.strip():
            return "the approver name has leading or trailing whitespace"
        if not isinstance(self.approver_role, str) or not self.approver_role.strip():
            return "it has no non-blank BRERC approver role"
        if self.approver_role != self.approver_role.strip():
            return "the approver role has leading or trailing whitespace"
        if self.approver_organisation != REQUIRED_APPROVER_ORGANISATION:
            return f"approver_organisation must be exactly {REQUIRED_APPROVER_ORGANISATION!r}"
        if not isinstance(self.evidence_reference, str) or not self.evidence_reference.strip():
            return "it has no non-blank retained BRERC evidence reference"
        if self.evidence_reference != self.evidence_reference.strip():
            return "the evidence reference has leading or trailing whitespace"
        try:
            approved_on = self._iso_date(self.approved_on, "approved_on")
            review_due = self._iso_date(self.review_due, "review_due")
        except InvalidPolicy as exc:
            return str(exc)

        today = as_of or date.today()
        if approved_on > today:
            return "approved_on is in the future"
        if review_due < approved_on:
            return "review_due is before approved_on"
        # The due date remains valid for that calendar day. It becomes expired
        # on the following day, avoiding a timezone-dependent midnight race.
        if review_due < today:
            return "its policy review is overdue"
        if self.public_id_salt is not None and not isinstance(self.public_id_salt, str):
            return "public_id_salt is not a string"
        if not isinstance(self.approval_digest, str) or not self.approval_digest:
            return "its approval is not bound to the policy decisions"
        if not hmac.compare_digest(self.approval_digest, self._expected_approval_digest()):
            return "the policy decisions changed after approval"
        return None

    def is_approved(self, *, as_of: date | None = None) -> bool:
        """True only for a complete, current approval by a named person.

        `development_only` overrides everything: a development policy is never
        approved, so it cannot be mistaken for one that is.
        """
        return self._approval_problem(as_of=as_of) is None

    def assert_approved(self, *, as_of: date | None = None) -> None:
        """Raise unless a named person has approved a still-current policy."""
        problem = self._approval_problem(as_of=as_of)
        if problem is not None:
            raise PolicyNotApproved(
                f"publication policy '{self.version}' is not currently approved: "
                f"{problem}. A named BRERC data owner must approve and periodically "
                "review the resolution, place-name, record-id, licensing and "
                "suppression rules before any real release."
            )

    def validate(self) -> None:
        """Raise if the policy asks for a resolution the client cannot draw.

        Called by `run_pipeline` before any row is processed. A policy naming an
        unrenderable resolution would otherwise fail one record at a time, deep
        inside the gate, and read as a data problem rather than a policy error.
        """
        boolean_decisions = (
            "development_only",
            "publish_place_names",
            "publish_original_record_ids",
            "publish_individual_records",
            "publish_abundance",
            "publish_record_type",
            "publish_record_verification",
            "coarsen_unpublishable_resolutions",
        )
        for field_name in boolean_decisions:
            if type(getattr(self, field_name)) is not bool:
                raise InvalidPolicy(
                    f"{field_name} must be a real boolean, not "
                    f"{type(getattr(self, field_name)).__name__}"
                )

        mode_sets = {
            "precision_mode": PRECISION_MODES,
            "suppression_mode": SUPPRESSION_MODES,
            "licensing_mode": LICENSING_MODES,
            "record_type_safety_mode": RECORD_TYPE_SAFETY_MODES,
            "row_level_records_mode": ROW_LEVEL_RECORDS_MODES,
            "verification_publication_mode": VERIFICATION_PUBLICATION_MODES,
        }
        for field_name, permitted in mode_sets.items():
            value = getattr(self, field_name)
            if not isinstance(value, str) or value not in permitted:
                raise InvalidPolicy(
                    f"{field_name}={value!r} is invalid. Permitted: {sorted(permitted)}"
                )
        if self.sensitive_snapshot_version is not None and (
            not isinstance(self.sensitive_snapshot_version, str)
            or not self.sensitive_snapshot_version.strip()
            or self.sensitive_snapshot_version != self.sensitive_snapshot_version.strip()
        ):
            raise InvalidPolicy("sensitive_snapshot_version must be a non-blank trimmed string")
        for field_name in (
            "sensitive_snapshot_sha256",
            "species_dictionary_sha256",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise InvalidPolicy(f"{field_name} must be a lowercase SHA-256 digest")

        named = {
            "ordinary_resolution_metres": self.ordinary_resolution_metres,
            "map_cell_resolution_metres": self.map_cell_resolution_metres,
            "default_sensitive_metres": self.default_sensitive_metres,
        }
        if self.row_sensitive_resolution_metres is not None:
            named["row_sensitive_resolution_metres"] = self.row_sensitive_resolution_metres
        for label, metres in named.items():
            if type(metres) is not int or metres not in EMITTABLE_RESOLUTIONS_METRES:
                raise InvalidPolicy(
                    f"{label}={metres} is not a resolution the client can draw. "
                    f"Permitted: {sorted(EMITTABLE_RESOLUTIONS_METRES)}."
                )
        for mapping_name, mapping in (
            ("sensitive_resolution_metres", self.sensitive_resolution_metres),
            ("sensitive_record_type_metres", self.sensitive_record_type_metres),
        ):
            for key, metres in mapping.items():
                if type(metres) is not int or metres not in EMITTABLE_RESOLUTIONS_METRES:
                    raise InvalidPolicy(
                        f"{mapping_name}[{key!r}]={metres} is not a resolution the "
                        f"client can draw. Permitted: "
                        f"{sorted(EMITTABLE_RESOLUTIONS_METRES)}."
                    )
        sensitive_floors = {
            "default_sensitive_metres": self.default_sensitive_metres,
            **{
                f"sensitive_resolution_metres[{key!r}]": metres
                for key, metres in self.sensitive_resolution_metres.items()
            },
            **{
                f"sensitive_record_type_metres[{key!r}]": metres
                for key, metres in self.sensitive_record_type_metres.items()
            },
        }
        if self.row_sensitive_resolution_metres is not None:
            sensitive_floors["row_sensitive_resolution_metres"] = (
                self.row_sensitive_resolution_metres
            )
        finer = [
            f"{label}={metres}"
            for label, metres in sensitive_floors.items()
            if metres < self.ordinary_resolution_metres
        ]
        if finer:
            raise InvalidPolicy(
                "sensitive resolutions must never be finer than "
                f"ordinary_resolution_metres={self.ordinary_resolution_metres}: " + ", ".join(finer)
            )
        if type(self.min_records_per_cell) is not int or self.min_records_per_cell < 1:
            raise InvalidPolicy("min_records_per_cell must be at least 1")
        if self.suppression_mode == "none" and self.min_records_per_cell != 1:
            raise InvalidPolicy("suppression_mode='none' requires min_records_per_cell=1")
        if self.suppression_mode == "minimum-count" and self.min_records_per_cell < 2:
            raise InvalidPolicy("suppression_mode='minimum-count' requires min_records_per_cell>=2")
        if self.licensing_mode == "not-applicable" and self.allowed_licence_values is not None:
            raise InvalidPolicy(
                "licensing_mode='not-applicable' requires allowed_licence_values=None"
            )
        if self.licensing_mode == "all-publication-allow-list" and not self.allowed_licence_values:
            raise InvalidPolicy(
                "licensing_mode='all-publication-allow-list' requires at least one "
                "allowed licence value"
            )
        if (
            self.verification_publication_mode == "unavailable"
            and self.accepted_verification_values is not None
        ):
            raise InvalidPolicy(
                "verification_publication_mode='unavailable' requires "
                "accepted_verification_values=None"
            )
        if (
            self.verification_publication_mode == "publish"
            and not self.development_only
            and not self.accepted_verification_values
        ):
            raise InvalidPolicy(
                "production verification publication requires a nonempty explicit "
                "accepted_verification_values vocabulary"
            )
        if self.record_type_safety_mode == "not-used" and (
            self.sensitive_record_type_metres or self.record_type_vocabulary
        ):
            raise InvalidPolicy(
                "record_type_safety_mode='not-used' requires no record-type rules or vocabulary"
            )
        if self.record_type_safety_mode == "rules" and (
            not self.sensitive_record_type_metres or not self.record_type_vocabulary
        ):
            raise InvalidPolicy(
                "record_type_safety_mode='rules' requires both sensitive rules and "
                "the complete record_type_vocabulary"
            )
        missing_types = set(self.sensitive_record_type_metres) - set(self.record_type_vocabulary)
        if missing_types:
            raise InvalidPolicy(
                "sensitive record-type rules are outside record_type_vocabulary: "
                f"{sorted(missing_types)}"
            )
        if self.row_level_records_mode == "aggregates-only" and self.publish_individual_records:
            raise InvalidPolicy(
                "row_level_records_mode='aggregates-only' requires publish_individual_records=False"
            )
        if self.row_level_records_mode == "aggregates-only":
            enabled = [
                name
                for name in (
                    "publish_place_names",
                    "publish_original_record_ids",
                    "publish_abundance",
                    "publish_record_type",
                    "publish_record_verification",
                )
                if getattr(self, name)
            ]
            if enabled:
                raise InvalidPolicy(
                    "row_level_records_mode='aggregates-only' requires all row-level "
                    f"publication fields off: {', '.join(enabled)}"
                )
        if self.row_level_records_mode == "publish" and not self.publish_individual_records:
            raise InvalidPolicy(
                "row_level_records_mode='publish' requires publish_individual_records=True"
            )
        if self.unknown_species_action not in {"withhold", "coarsest"}:
            raise InvalidPolicy(
                f"unknown_species_action={self.unknown_species_action!r} must be "
                '"withhold" or "coarsest". There is deliberately no "ordinary" '
                "option: an unresolved taxon must never be treated as safe."
            )
        if self.non_sensitive_values and self.row_sensitive_resolution_metres is None:
            raise InvalidPolicy(
                "non_sensitive_values is configured without "
                "row_sensitive_resolution_metres; the source vocabulary would have "
                "no enforceable location rule."
            )
        if (
            not isinstance(self.public_source_label, str)
            or self.public_source_label not in PUBLIC_SOURCE_LABELS
        ):
            raise InvalidPolicy(
                "public_source_label must be one of the reviewed organisational "
                f"labels: {sorted(PUBLIC_SOURCE_LABELS)}; raw source text may contain PII"
            )
        if not self.publish_individual_records and (
            self.publish_abundance or self.publish_record_type or self.publish_record_verification
        ):
            raise InvalidPolicy("optional row fields require publish_individual_records=True")
        if self.publish_record_verification and self.verification_publication_mode != "publish":
            raise InvalidPolicy(
                "publish_record_verification=True requires verification_publication_mode='publish'"
            )
        if not self.publish_original_record_ids and not self.public_id_salt:
            # Checked here, before any row, rather than at the first call to
            # public_record_id(). A policy that raises halfway through a run
            # leaves a half-built payload and reads as a data fault; a policy
            # that refuses at the start reads as what it is - a missing setting.
            raise InvalidPolicy(
                f"policy '{self.version}' can neither derive a public record id "
                "(no public_id_salt) nor publish the original (publish_original_"
                "record_ids is False). Set a salt - kept out of the repository - "
                "or set publish_original_record_ids=True deliberately."
            )
        if (
            not self.publish_original_record_ids
            and self.public_id_salt
            and len(self.public_id_salt.encode("utf-8")) < MIN_PUBLIC_ID_SECRET_BYTES
        ):
            raise InvalidPolicy(
                "public_id_salt must be at least "
                f"{MIN_PUBLIC_ID_SECRET_BYTES} UTF-8 bytes and supplied from an "
                "external secret store. Length is only a baseline; use a "
                "cryptographically random value, never a repository literal."
            )

    # -- resolution decisions -------------------------------------------------

    def undecided_decisions(self) -> tuple[str, ...]:
        """Approval-bound decisions that have not been settled."""
        return tuple(
            field_name
            for field_name in (
                "precision_mode",
                "suppression_mode",
                "licensing_mode",
                "record_type_safety_mode",
                "row_level_records_mode",
                "verification_publication_mode",
            )
            if getattr(self, field_name) == "undecided"
        )

    def has_sensitive_species_rule(self, species_id: object) -> bool:
        """True when the policy explicitly lists this taxon as sensitive.

        A per-species resolution is not merely a formatting override: its
        presence is itself a sensitivity decision.  Callers must not need a
        second, separately-maintained flag before the rule takes effect.
        """
        if species_id is None or isinstance(species_id, bool):
            return False
        key = str(species_id).strip().upper()
        return bool(key) and key in self.sensitive_resolution_metres

    def resolution_for(self, species_id: str | None, *, sensitive: bool, known: bool) -> int | None:
        """Required resolution, or None when the record must be withheld.

        Membership in ``sensitive_resolution_metres`` is authoritative even if
        a caller supplies ``sensitive=False``.  This prevents a stale external
        flag from silently disabling an explicit policy rule.
        """
        if not known or species_id is None:
            if self.unknown_species_action == "withhold":
                return None
            return COARSEST_EMITTABLE_METRES
        if sensitive or self.has_sensitive_species_rule(species_id):
            key = str(species_id).strip().upper()
            return self.sensitive_resolution_metres.get(key, self.default_sensitive_metres)
        return self.ordinary_resolution_metres

    def resolution_for_record_type(self, record_type: object) -> int | None:
        """Coarser resolution demanded by a sensitive record type, if any."""
        if not self.sensitive_record_type_metres or record_type is None:
            return None
        key = str(record_type).strip().casefold()
        if not key:
            return None
        return self.sensitive_record_type_metres.get(key)

    def record_type_is_known(self, record_type: object) -> bool:
        """Whether a value belongs to the complete approved record-type vocabulary."""
        if record_type is None:
            return False
        key = str(record_type).strip().casefold()
        return bool(key) and key in self.record_type_vocabulary

    def licence_permits_publication(self, licence: object) -> bool:
        """True when this record's licence allows public use.

        ``not-applicable`` is an affirmative BRERC decision that the source
        licence code does not govern this public use. ``all-publication-allow-list``
        is fail-closed: a missing or unrecognised code withholds the record from
        rows, cells, year series and totals. ``undecided`` also fails closed.
        """
        if self.licensing_mode == "not-applicable":
            return True
        if self.licensing_mode != "all-publication-allow-list":
            return False
        if licence is None:
            return False
        return str(licence).strip().casefold() in self.allowed_licence_values

    def is_row_sensitive(self, raw: object) -> bool:
        """Interpret a source row's sensitivity flag without guessing.

        Only a value explicitly listed in ``non_sensitive_values`` is allowed
        down the ordinary-location path. This makes missing, blank and newly
        introduced codes safe by default instead of silently treating them as
        ``No``.
        """
        text = "" if raw is None else str(raw).strip().casefold()
        # Belt and braces: validate() rejects a blank allow-value, but this
        # method remains fail-closed even if somebody calls it before validate.
        return not text or text not in self.non_sensitive_values

    # -- identifiers ----------------------------------------------------------

    def public_record_id(self, original: object) -> str:
        """A stable, non-reversible public id derived from the original.

        HMAC-SHA256 with the policy salt, truncated. Deterministic, so the same
        record keeps the same public id across releases; not reversible without
        the salt, so a published id cannot be traced back to a BRERC row.

        Truncation to 32 hex characters (128 bits) keeps identifiers compact while
        making accidental collisions negligible at BRERC's scale. `run_pipeline`
        still asserts uniqueness within a run so a collision fails loudly.
        """
        text = str(original)
        if self.publish_original_record_ids:
            return text
        if not self.public_id_salt:
            raise PolicyNotApproved(
                "public_id_salt is not set. Either set a salt (kept out of the "
                "repository) or set publish_original_record_ids=True deliberately."
            )
        if len(self.public_id_salt.encode("utf-8")) < MIN_PUBLIC_ID_SECRET_BYTES:
            raise InvalidPolicy(
                f"public_id_salt must be at least {MIN_PUBLIC_ID_SECRET_BYTES} UTF-8 bytes"
            )
        digest = hmac.new(self.public_id_salt.encode("utf-8"), text.encode("utf-8"), hashlib.sha256)
        return digest.hexdigest()[:32]

    def with_approval(
        self,
        *,
        approved_by: str,
        approver_role: str,
        approver_organisation: str,
        evidence_reference: str,
        approved_on: str,
        review_due: str,
    ) -> PublicationPolicy:
        """Return an approval bound to retained evidence from a BRERC owner."""
        if self.development_only:
            raise PolicyNotApproved(
                f"policy '{self.version}' is marked development_only and cannot be "
                "approved. Build a real policy from BRERC's answers instead."
            )
        candidate = replace(
            self,
            approved_by=approved_by,
            approver_role=approver_role,
            approver_organisation=approver_organisation,
            evidence_reference=evidence_reference,
            approved_on=approved_on,
            review_due=review_due,
            approval_digest=None,
        )
        candidate.validate()
        approved = replace(
            candidate,
            approval_digest=candidate._expected_approval_digest(),
        )
        approved.assert_approved()
        return approved

    def describe(self) -> dict[str, object]:
        """A summary safe to write into a run report or a handover document."""
        return {
            "version": self.version,
            "approved": self.is_approved(),
            "approvedBy": self.approved_by,
            "approverRole": self.approver_role,
            "approverOrganisation": self.approver_organisation,
            "evidenceReference": self.evidence_reference,
            "approvedOn": self.approved_on,
            "reviewDue": self.review_due,
            "approvalDigest": self.approval_digest,
            "developmentOnly": self.development_only,
            "precisionMode": self.precision_mode,
            "suppressionMode": self.suppression_mode,
            "licensingMode": self.licensing_mode,
            "recordTypeSafetyMode": self.record_type_safety_mode,
            "rowLevelRecordsMode": self.row_level_records_mode,
            "verificationPublicationMode": self.verification_publication_mode,
            "sensitiveSnapshotVersion": self.sensitive_snapshot_version,
            "sensitiveSnapshotSha256": self.sensitive_snapshot_sha256,
            "speciesDictionarySha256": self.species_dictionary_sha256,
            "ordinaryResolutionMetres": self.ordinary_resolution_metres,
            "mapCellResolutionMetres": self.map_cell_resolution_metres,
            "defaultSensitiveMetres": self.default_sensitive_metres,
            "rowSensitiveResolutionMetres": self.row_sensitive_resolution_metres,
            "perSpeciesOverrides": len(self.sensitive_resolution_metres),
            "sensitiveRecordTypes": len(self.sensitive_record_type_metres),
            "recordTypeVocabularySize": len(self.record_type_vocabulary),
            "unknownSpeciesAction": self.unknown_species_action,
            "publishPlaceNames": self.publish_place_names,
            "publicSourceLabel": self.public_source_label,
            "publishIndividualRecords": self.publish_individual_records,
            "individualRecordSchemaVersion": INDIVIDUAL_RECORD_SCHEMA_VERSION,
            "individualRecordBaseFields": list(INDIVIDUAL_RECORD_BASE_FIELDS),
            "individualRecordControlledFields": dict(INDIVIDUAL_RECORD_CONTROLLED_FIELDS),
            "publishAbundance": self.publish_abundance,
            "publishRecordType": self.publish_record_type,
            "publishRecordVerification": self.publish_record_verification,
            "publishOriginalRecordIds": self.publish_original_record_ids,
            "minRecordsPerCell": self.min_records_per_cell,
            "suppressionScope": SUPPRESSION_SCOPE,
            "suppressionCountBasis": SUPPRESSION_COUNT_BASIS,
            "suppressionCohort": list(SUPPRESSION_COHORT),
            "suppressionSurfaces": list(SUPPRESSION_SURFACES),
            "licenceEnforced": self.allowed_licence_values is not None,
            "rowSensitivityConfigured": bool(self.non_sensitive_values),
            "coarsenUnpublishableResolutions": self.coarsen_unpublishable_resolutions,
        }

    def approval_artifact(self) -> dict[str, object]:
        """Return the exact secret-free policy envelope consumed by deployment.

        The public-id key itself is never included—only the SHA-256 fingerprint
        already bound into the approval digest. The loader resolves the key
        independently from its secret store and reconstructs this envelope;
        any altered decision, approval field or key fails ``assert_approved``.
        """
        self.validate()
        self.assert_approved()
        return {
            "artifactFormat": "brerc-publication-policy/v1",
            "status": "approved",
            "approval": {
                "approvedBy": self.approved_by,
                "approverRole": self.approver_role,
                "approverOrganisation": self.approver_organisation,
                "evidenceReference": self.evidence_reference,
                "approvedOn": self.approved_on,
                "reviewDue": self.review_due,
                "approvalDigest": self.approval_digest,
            },
            "decisions": self._decision_document(),
        }


#: The null policy: no approver, no salt, no agreed resolutions. `validate()`
#: refuses it, so `run_pipeline` cannot run under it. Exported so that "no policy
#: has been decided" is a value that can be named, passed around and asserted on,
#: rather than a None that some code path might quietly accept.
UNAPPROVED_POLICY = PublicationPolicy(version="unapproved-draft")

#: For tests and synthetic-data development ONLY. `development_only=True` means
#: `is_approved()` is False and `assert_approved()` raises, so this cannot reach
#: a real release however it is wired up.
DEVELOPMENT_POLICY = PublicationPolicy(
    version="development-only",
    development_only=True,
    precision_mode="approved",
    suppression_mode="none",
    licensing_mode="not-applicable",
    record_type_safety_mode="not-used",
    row_level_records_mode="publish",
    verification_publication_mode="publish",
    ordinary_resolution_metres=FINEST_EMITTABLE_METRES,
    default_sensitive_metres=COARSEST_EMITTABLE_METRES,
    unknown_species_action="withhold",
    publish_place_names=False,
    publish_original_record_ids=False,
    publish_individual_records=True,
    publish_abundance=True,
    publish_record_type=True,
    publish_record_verification=True,
    public_id_salt="development-salt-not-secret-32bytes",
    min_records_per_cell=1,
)
