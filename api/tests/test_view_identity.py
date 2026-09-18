"""Adversarial tests for PostgreSQL view identity and BRERC approval evidence."""

import copy
import unittest
from datetime import date, timedelta

from etl.view_identity import (
    EXPECTED_CAPTURE_SESSION,
    VIEW_APPROVAL_ARTIFACT_FORMAT,
    VIEW_CAPTURE_ARTIFACT_FORMAT,
    VIEW_DEFINITION_DIGEST_PROFILE,
    VIEW_IDENTITY_PROFILE,
    ObservedViewDefinition,
    ViewCaptureEvidence,
    ViewDefinitionApproval,
    ViewIdentityError,
    postgres_major_version,
    source_columns_sha256,
    view_definition_sha256,
)

COLUMNS = (
    {"name": "species_no", "type": "text", "length": None, "precision": None, "scale": None},
    {
        "name": "unique_no",
        "type": "numeric",
        "length": None,
        "precision": 13,
        "scale": 2,
    },
)


def observation(**changes) -> ObservedViewDefinition:
    values = {
        "schema": "dashboard",
        "name": "main_data_dash",
        "relkind": "v",
        "definition": 'SELECT md."scientific_name"\nFROM main_data.records AS md',
        "postgres_server_version_num": 160004,
        "owner": "postgres",
        "reloptions": ("security_barrier=true",),
    }
    values.update(changes)
    return ObservedViewDefinition(**values)


def approval(**changes) -> ViewDefinitionApproval:
    observed = observation()
    evidence = ViewCaptureEvidence.from_document(capture_document())
    values = {
        "source_version": "BRERC-main-data-dash-v1",
        "source_environment": "BRERC production",
        "client_reference_document_sha256": "a" * 64,
        "schema": observed.schema,
        "name": observed.name,
        "relkind": observed.relkind,
        "postgres_server_version_num": observed.postgres_server_version_num,
        "owner": observed.owner,
        "reloptions": observed.reloptions,
        "columns_sha256": source_columns_sha256(COLUMNS),
        "catalog_columns_sha256": evidence.catalog_columns_sha256,
        "definition_sha256": observed.definition_sha256,
        "capture_evidence_sha256": evidence.capture_sha256,
        "approved_by": "Maude Example",
        "approver_role": "BRERC data owner",
        "approver_organisation": "BRERC",
        "captured_at_utc": "2026-08-10T00:00:00Z",
        "approved_on": date.today().isoformat(),
        "evidence_reference": "BRERC-EMAIL-2026-08-10",
        "review_expires_on": (date.today() + timedelta(days=365)).isoformat(),
    }
    values.update(changes)
    return ViewDefinitionApproval(**values)


def capture_document() -> dict[str, object]:
    observed = observation()
    columns = []
    for ordinal, column in enumerate(COLUMNS, start=1):
        columns.append(
            {
                "ordinal_position": ordinal,
                "column_name": column["name"],
                "data_type": column["type"],
                "udt_schema": "pg_catalog",
                "udt_name": "text" if column["type"] == "text" else "numeric",
                "character_maximum_length": column["length"],
                "numeric_precision": column["precision"],
                "numeric_scale": column["scale"],
                "is_nullable": "YES",
                "collation_schema": None,
                "collation_name": None,
            }
        )
    return {
        "artifact_format": VIEW_CAPTURE_ARTIFACT_FORMAT,
        "captured_at_utc": "2026-08-10T00:00:00.000000Z",
        "postgres": {
            "database": "private_database_name",
            "server_version": "16.4",
            "server_version_num": observed.postgres_server_version_num,
            "server_major": observed.postgres_major,
            "server_encoding": "UTF8",
            "captured_by_database_role": "private_role",
        },
        "session": dict(EXPECTED_CAPTURE_SESSION),
        "object": {
            "schema": observed.schema,
            "name": observed.name,
            "qualified_name": "dashboard.main_data_dash",
            "relation_oid": 12345,
            "relkind": observed.relkind,
            "relpersistence": "p",
            "owner": observed.owner,
            "reloptions": list(observed.reloptions),
        },
        "view_definition": observed.definition,
        "view_definition_utf8_hex": observed.definition.encode("utf-8").hex(),
        "columns": columns,
    }


class TestExactDefinitionDigest(unittest.TestCase):
    def test_one_character_or_whitespace_change_changes_the_digest(self):
        baseline = "SELECT 1"
        variants = ("SELECT 2", "SELECT 1 ", "SELECT\n1", "select 1")
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    view_definition_sha256(baseline),
                    view_definition_sha256(changed),
                )

    def test_non_ascii_text_is_hashed_as_exact_utf8(self):
        self.assertNotEqual(
            view_definition_sha256("SELECT 'é'"),
            view_definition_sha256("SELECT 'é'"),
        )

    def test_empty_nul_and_unpaired_surrogate_text_are_rejected(self):
        for value in (None, "", "SELECT\x00x", "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(ViewIdentityError):
                view_definition_sha256(value)

    def test_postgres_major_is_derived_without_accepting_bool_or_string(self):
        self.assertEqual(postgres_major_version(90624), 9)
        self.assertEqual(postgres_major_version(160004), 16)
        for value in (True, "160004", 89999):
            with self.subTest(value=value), self.assertRaises(ViewIdentityError):
                postgres_major_version(value)


class TestObservedIdentity(unittest.TestCase):
    def test_repr_never_contains_the_view_sql(self):
        observed = observation(definition="SELECT private_internal_name")
        self.assertNotIn("private_internal_name", repr(observed))

    def test_reloptions_are_canonical_and_object_must_be_an_ordinary_view(self):
        cases = (
            {"reloptions": ["security_barrier=true"]},
            {"reloptions": ("z=1", "a=1")},
            {"reloptions": ("a=1", "a=1")},
            {"relkind": "m"},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ViewIdentityError):
                observation(**changes)

    def test_column_order_is_part_of_the_identity(self):
        forward = source_columns_sha256(COLUMNS)
        reverse = source_columns_sha256(tuple(reversed(COLUMNS)))
        self.assertNotEqual(forward, reverse)

    def test_owner_options_sql_and_major_are_all_bound(self):
        observed = observation()
        columns_digest = source_columns_sha256(COLUMNS)
        baseline = observed.identity_sha256(columns_digest, columns_digest)
        changes = (
            {"owner": "other_owner"},
            {"reloptions": ()},
            {"definition": observed.definition + " "},
            {"postgres_server_version_num": 170001},
        )
        for change in changes:
            with self.subTest(change=change):
                self.assertNotEqual(
                    baseline,
                    observation(**change).identity_sha256(
                        columns_digest,
                        columns_digest,
                    ),
                )


class TestRawCaptureEvidence(unittest.TestCase):
    def test_exact_capture_builds_a_sanitised_pending_approval(self):
        evidence = ViewCaptureEvidence.from_document(capture_document())
        pending = evidence.pending_approval_document()
        rendered = str(pending)
        self.assertEqual(evidence.columns_sha256, source_columns_sha256(COLUMNS))
        self.assertEqual(pending["status"], "pending-brerc-approval")
        self.assertIsNone(pending["sourceEnvironment"])
        self.assertEqual(pending["approval"]["approvedBy"], None)
        self.assertIsNone(pending["approval"]["approverOrganisation"])
        self.assertNotIn("private_database_name", rendered)
        self.assertNotIn("private_role", rendered)
        self.assertNotIn(observation().definition, rendered)

    def test_hex_is_the_authority_and_must_match_the_json_text_exactly(self):
        for value in ("00", "ABCDEF", observation().definition.encode("utf-8").hex() + "00"):
            document = capture_document()
            document["view_definition_utf8_hex"] = value
            with self.subTest(value=value), self.assertRaises(ViewIdentityError):
                ViewCaptureEvidence.from_document(document)

    def test_wrong_object_kind_identity_persistence_and_server_context_fail(self):
        mutations = (
            ("object", "schema", "public"),
            ("object", "relkind", "m"),
            ("object", "relpersistence", "t"),
            ("postgres", "server_encoding", "LATIN1"),
            ("postgres", "server_major", 15),
        )
        for section, key, value in mutations:
            document = capture_document()
            document[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ViewIdentityError):
                ViewCaptureEvidence.from_document(document)

    def test_column_ordinals_and_capture_keys_are_exact(self):
        wrong_ordinal = capture_document()
        wrong_ordinal["columns"][0]["ordinal_position"] = 2
        extra_key = capture_document()
        extra_key["rows"] = [{"sensitive": "Yes"}]
        for document in (wrong_ordinal, extra_key):
            with self.subTest(document=document), self.assertRaises(ViewIdentityError):
                ViewCaptureEvidence.from_document(document)

    def test_complete_catalog_metadata_is_bound_into_the_identity(self):
        baseline = ViewCaptureEvidence.from_document(capture_document())
        mutations = (
            ("udt_name", "domain_name"),
            ("is_nullable", "NO"),
        )
        for key, value in mutations:
            document = capture_document()
            document["columns"][0][key] = value
            changed = ViewCaptureEvidence.from_document(document)
            with self.subTest(key=key):
                self.assertNotEqual(
                    changed.catalog_columns_sha256,
                    baseline.catalog_columns_sha256,
                )
                self.assertNotEqual(changed.identity_sha256, baseline.identity_sha256)
                self.assertNotEqual(changed.capture_sha256, baseline.capture_sha256)

        collated = capture_document()
        collated["columns"][0]["collation_schema"] = "pg_catalog"
        collated["columns"][0]["collation_name"] = "C"
        changed = ViewCaptureEvidence.from_document(collated)
        self.assertNotEqual(changed.catalog_columns_sha256, baseline.catalog_columns_sha256)
        self.assertNotEqual(changed.identity_sha256, baseline.identity_sha256)

    def test_serialisable_column_documents_cannot_mutate_captured_evidence(self):
        evidence = ViewCaptureEvidence.from_document(capture_document())
        expected_columns = evidence.columns_sha256
        expected_identity = evidence.identity_sha256
        exported = evidence.columns_document
        exported[0]["name"] = "attacker_changed_name"
        self.assertEqual(evidence.columns_sha256, expected_columns)
        self.assertEqual(evidence.identity_sha256, expected_identity)

    def test_digest_profile_rejects_session_setting_drift(self):
        for key, value in (
            ("TimeZone", "Europe/London"),
            ("standard_conforming_strings", "off"),
            ("extra_float_digits", "1"),
        ):
            document = capture_document()
            document["session"][key] = value
            with self.subTest(key=key), self.assertRaises(ViewIdentityError):
                ViewCaptureEvidence.from_document(document)


class TestApprovalEnvelope(unittest.TestCase):
    def test_document_round_trip_is_exact(self):
        expected = approval()
        actual = ViewDefinitionApproval.from_document(expected.to_document())
        self.assertEqual(actual, expected)
        self.assertEqual(actual.identity_sha256, expected.identity_sha256)

    def test_document_names_the_fixed_profiles(self):
        document = approval().to_document()
        self.assertEqual(document["artifactFormat"], VIEW_APPROVAL_ARTIFACT_FORMAT)
        self.assertEqual(document["digest"]["profile"], VIEW_DEFINITION_DIGEST_PROFILE)
        self.assertEqual(document["digest"]["identityProfile"], VIEW_IDENTITY_PROFILE)

    def test_pending_status_is_not_an_approval(self):
        document = approval().to_document()
        document["status"] = "pending-brerc-approval"
        with self.assertRaises(ViewIdentityError):
            ViewDefinitionApproval.from_document(document)

    def test_missing_extra_and_nested_extra_fields_are_rejected(self):
        cases = []
        missing = approval().to_document()
        del missing["approval"]
        cases.append(missing)
        extra = approval().to_document()
        extra["note"] = "looks harmless"
        cases.append(extra)
        nested = approval().to_document()
        nested["source"]["database"] = "internal"
        cases.append(nested)
        for document in cases:
            with self.subTest(document=document), self.assertRaises(ViewIdentityError):
                ViewDefinitionApproval.from_document(document)

    def test_digest_profile_and_identity_digest_cannot_be_substituted(self):
        for field_name in ("profile", "identityProfile", "identitySha256"):
            document = approval().to_document()
            document["digest"][field_name] = "f" * 64
            with self.subTest(field=field_name), self.assertRaises(ViewIdentityError):
                ViewDefinitionApproval.from_document(document)

    def test_placeholder_and_future_approval_evidence_is_rejected(self):
        cases = (
            {"approved_by": "TBD"},
            {"approver_role": "pending"},
            {"approver_organisation": "placeholder"},
            {"source_environment": "unknown"},
            {"evidence_reference": "unknown"},
            {"approved_on": (date.today() + timedelta(days=1)).isoformat()},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ViewIdentityError):
                approval(**changes)

    def test_capture_cannot_postdate_the_approval_or_current_time(self):
        tomorrow = date.today() + timedelta(days=1)
        cases = (
            {
                "captured_at_utc": f"{tomorrow.isoformat()}T00:00:00Z",
                "approved_on": date.today().isoformat(),
            },
            {
                "captured_at_utc": f"{tomorrow.isoformat()}T00:00:00Z",
                "approved_on": tomorrow.isoformat(),
            },
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ViewIdentityError):
                approval(**changes)

    def test_expired_approval_is_valid_evidence_but_not_current_authority(self):
        expired = approval(
            captured_at_utc=(date.today() - timedelta(days=3)).isoformat() + "T00:00:00Z",
            approved_on=(date.today() - timedelta(days=2)).isoformat(),
            review_expires_on=(date.today() - timedelta(days=1)).isoformat(),
        )
        self.assertFalse(expired.is_current())
        with self.assertRaises(ViewIdentityError):
            expired.assert_current()

    def test_every_observed_identity_change_is_reported(self):
        approved = approval()
        cases = (
            observation(definition=observation().definition + " "),
            observation(owner="other"),
            observation(reloptions=()),
            observation(postgres_server_version_num=170001),
        )
        for observed in cases:
            with self.subTest(observed=observed):
                self.assertTrue(approved.differences(observed))

    def test_tampering_with_any_approved_identity_field_breaks_manifest_validation(self):
        baseline = approval().to_document()
        mutations = (
            ("source", "owner", "other"),
            ("source", "columnsSha256", "f" * 64),
            ("digest", "definitionSha256", "f" * 64),
        )
        for section, key, value in mutations:
            document = copy.deepcopy(baseline)
            document[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ViewIdentityError):
                ViewDefinitionApproval.from_document(document)


if __name__ == "__main__":
    unittest.main(verbosity=1)
