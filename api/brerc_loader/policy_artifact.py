"""Strict reconstruction of a BRERC-approved publication policy artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from etl.policy import (
    PUBLICATION_POLICY_ARTIFACT_FORMAT,
    InvalidPolicy,
    PolicyNotApproved,
    PublicationPolicy,
)

from .errors import LoaderPolicyInvalid

POLICY_ARTIFACT_FORMAT = PUBLICATION_POLICY_ARTIFACT_FORMAT
MAX_POLICY_ARTIFACT_BYTES = 1024 * 1024

_ROOT_KEYS = frozenset({"artifactFormat", "status", "approval", "decisions"})
_APPROVAL_KEYS = frozenset(
    {
        "approvedBy",
        "approverRole",
        "approverOrganisation",
        "evidenceReference",
        "approvedOn",
        "reviewDue",
        "approvalAuthorityBasis",
        "delegatingAuthorityName",
        "delegatingAuthorityRole",
        "delegatingAuthorityOrganisation",
        "delegationScope",
        "delegatedOn",
        "delegationEvidenceReference",
        "approvalDigest",
    }
)
_DECISION_KEYS = frozenset(
    {
        "version",
        "developmentOnly",
        "precisionMode",
        "suppressionMode",
        "licensingMode",
        "recordTypeSafetyMode",
        "rowLevelRecordsMode",
        "verificationPublicationMode",
        "sensitiveRecordAction",
        "sensitiveSnapshotVersion",
        "sensitiveSnapshotSha256",
        "speciesDictionarySha256",
        "ordinaryResolutionMetres",
        "mapCellResolutionMetres",
        "sensitiveResolutionMetres",
        "defaultSensitiveMetres",
        "rowSensitiveResolutionMetres",
        "unknownSpeciesAction",
        "publishPlaceNames",
        "publicSourceLabel",
        "publishIndividualRecords",
        "individualRecordSchemaVersion",
        "individualRecordBaseFields",
        "individualRecordControlledFields",
        "publishAbundance",
        "publishRecordType",
        "publishRecordVerification",
        "publishOriginalRecordIds",
        "publicIdScheme",
        "publicIdKeyFingerprint",
        "minRecordsPerCell",
        "suppressionScope",
        "suppressionCountBasis",
        "suppressionCohort",
        "suppressionSurfaces",
        "acceptedVerificationValues",
        "allowedLicenceValues",
        "nonSensitiveValues",
        "sensitiveRecordTypeMetres",
        "recordTypeVocabulary",
        "coarsenUnpublishableResolutions",
    }
)


def _invalid() -> LoaderPolicyInvalid:
    return LoaderPolicyInvalid()


def _object(value: object, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _invalid()
    return value


def _strict_json(data: bytes) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if not isinstance(key, str) or key in result:
                raise _invalid()
            result[key] = value
        return result

    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except LoaderPolicyInvalid:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise _invalid() from None
    return _object(document, _ROOT_KEYS)


def _string(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\n" in value
        or "\r" in value
    ):
        raise _invalid()
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise _invalid()
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid()
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _string_list(value: object, *, nullable: bool = False) -> frozenset[str] | None:
    if nullable and value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _invalid()
    if len(value) != len(set(value)):
        raise _invalid()
    return frozenset(_string(item) for item in value)


def _resolution_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _invalid()
    result: dict[str, int] = {}
    for key, metres in value.items():
        normalised = _string(key)
        if normalised in result:
            raise _invalid()
        result[normalised] = _integer(metres)
    return result


def policy_artifact_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_publication_policy_artifact(
    path: str | Path,
    *,
    expected_sha256: str,
    public_id_secret: bytes,
) -> PublicationPolicy:
    """Load exact retained bytes and prove they match the runtime secret/key."""
    artifact_path = Path(path)
    try:
        size = artifact_path.stat().st_size
        raw = artifact_path.read_bytes()
    except OSError:
        raise _invalid() from None
    if not 1 <= size <= MAX_POLICY_ARTIFACT_BYTES or len(raw) != size:
        raise _invalid()
    return parse_publication_policy_artifact(
        raw,
        expected_sha256=expected_sha256,
        public_id_secret=public_id_secret,
    )


def parse_publication_policy_artifact(
    raw: bytes,
    *,
    expected_sha256: str,
    public_id_secret: bytes,
) -> PublicationPolicy:
    """Parse already-snapshotted bytes without a path-replacement race."""
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or not isinstance(public_id_secret, bytes)
        or len(public_id_secret) < 32
    ):
        raise _invalid()
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_POLICY_ARTIFACT_BYTES:
        raise _invalid()
    if policy_artifact_sha256(raw) != expected_sha256:
        raise _invalid()

    document = _strict_json(raw)
    if document["artifactFormat"] != POLICY_ARTIFACT_FORMAT or document["status"] != "approved":
        raise _invalid()
    approval = _object(document["approval"], _APPROVAL_KEYS)
    decisions = _object(document["decisions"], _DECISION_KEYS)
    if _boolean(decisions["developmentOnly"]):
        raise _invalid()
    if _boolean(decisions["publishOriginalRecordIds"]):
        # The destination schema intentionally has no slot for a reversible
        # BRERC identifier; the loader only supports HMAC public IDs.
        raise _invalid()

    try:
        policy = PublicationPolicy(
            version=_string(decisions["version"]),
            approved_by=_string(approval["approvedBy"]),
            approver_role=_string(approval["approverRole"]),
            approver_organisation=_string(approval["approverOrganisation"]),
            evidence_reference=_string(approval["evidenceReference"]),
            approved_on=_string(approval["approvedOn"]),
            review_due=_string(approval["reviewDue"]),
            approval_authority_basis=_string(approval["approvalAuthorityBasis"]),
            delegating_authority_name=_optional_string(approval["delegatingAuthorityName"]),
            delegating_authority_role=_optional_string(approval["delegatingAuthorityRole"]),
            delegating_authority_organisation=_optional_string(
                approval["delegatingAuthorityOrganisation"]
            ),
            delegation_scope=_optional_string(approval["delegationScope"]),
            delegated_on=_optional_string(approval["delegatedOn"]),
            delegation_evidence_reference=_optional_string(approval["delegationEvidenceReference"]),
            approval_digest=_string(approval["approvalDigest"]),
            development_only=False,
            precision_mode=_string(decisions["precisionMode"]),
            suppression_mode=_string(decisions["suppressionMode"]),
            licensing_mode=_string(decisions["licensingMode"]),
            record_type_safety_mode=_string(decisions["recordTypeSafetyMode"]),
            row_level_records_mode=_string(decisions["rowLevelRecordsMode"]),
            verification_publication_mode=_string(decisions["verificationPublicationMode"]),
            sensitive_record_action=_string(decisions["sensitiveRecordAction"]),
            sensitive_snapshot_version=_optional_string(decisions["sensitiveSnapshotVersion"]),
            sensitive_snapshot_sha256=_optional_string(decisions["sensitiveSnapshotSha256"]),
            species_dictionary_sha256=_optional_string(decisions["speciesDictionarySha256"]),
            ordinary_resolution_metres=_integer(decisions["ordinaryResolutionMetres"]),
            map_cell_resolution_metres=_integer(decisions["mapCellResolutionMetres"]),
            sensitive_resolution_metres=_resolution_map(decisions["sensitiveResolutionMetres"]),
            default_sensitive_metres=_integer(decisions["defaultSensitiveMetres"]),
            row_sensitive_resolution_metres=_optional_integer(
                decisions["rowSensitiveResolutionMetres"]
            ),
            unknown_species_action=_string(decisions["unknownSpeciesAction"]),
            publish_place_names=_boolean(decisions["publishPlaceNames"]),
            public_source_label=_string(decisions["publicSourceLabel"]),
            publish_individual_records=_boolean(decisions["publishIndividualRecords"]),
            publish_abundance=_boolean(decisions["publishAbundance"]),
            publish_record_type=_boolean(decisions["publishRecordType"]),
            publish_record_verification=_boolean(decisions["publishRecordVerification"]),
            publish_original_record_ids=False,
            public_id_salt=public_id_secret.decode("utf-8"),
            min_records_per_cell=_integer(decisions["minRecordsPerCell"]),
            accepted_verification_values=_string_list(
                decisions["acceptedVerificationValues"], nullable=True
            ),
            allowed_licence_values=_string_list(decisions["allowedLicenceValues"], nullable=True),
            non_sensitive_values=_string_list(decisions["nonSensitiveValues"]) or frozenset(),
            sensitive_record_type_metres=_resolution_map(decisions["sensitiveRecordTypeMetres"]),
            record_type_vocabulary=_string_list(decisions["recordTypeVocabulary"]) or frozenset(),
            coarsen_unpublishable_resolutions=_boolean(
                decisions["coarsenUnpublishableResolutions"]
            ),
        )
        policy.validate()
        policy.assert_approved()
    except (InvalidPolicy, PolicyNotApproved, UnicodeDecodeError, ValueError, TypeError):
        raise _invalid() from None
    if policy.approval_artifact() != document:
        raise _invalid()
    return policy
