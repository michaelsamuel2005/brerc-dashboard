"""End-to-end tests for the safety boundary.

The capstone is `TestNothingLeaks`: raw rows carrying every forbidden field go in,
and the public payloads are asserted clean coming out.

Every run names its policy. `DEVELOPMENT_POLICY` publishes ordinary records at
100 m, sensitive ones at 10 km, withholds unresolved taxa, withholds place names,
and derives non-reversible record ids - which is what the frontend contract can
carry, NOT what BRERC has authorised.
"""

import dataclasses
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from etl.contract import FORBIDDEN_FIELDS, assert_no_forbidden_fields
from etl.gridref import precision_metres
from etl.pipeline import (
    DEFAULT_PAGE_SIZE,
    CandidatePreview,
    ColumnMap,
    DuplicatePublicId,
    MissingColumns,
    UnmappedControlColumn,
    build_candidate_payloads,
    build_payloads,
    read_csv,
    run_pipeline,
)
from etl.policy import (
    DEVELOPMENT_POLICY,
    UNAPPROVED_POLICY,
    InvalidPolicy,
    PolicyNotApproved,
    PublicationPolicy,
)
from etl.sensitivity import SENSITIVE_SNAPSHOT_SHA256, SENSITIVE_SNAPSHOT_VERSION
from etl.source_contract import BRERC_MAIN_DATA_DASH
from etl.species import SpeciesDictionary, SpeciesRecord

DEV = DEVELOPMENT_POLICY
DEV_NO_VERIFICATION = dataclasses.replace(
    DEVELOPMENT_POLICY,
    version="development-without-verification",
    verification_publication_mode="unavailable",
    sensitive_record_action="generalise",
    publish_record_verification=False,
)

COLUMNS = ColumnMap(
    record_id="RecordKey",
    species_id="SPECIES_No",
    scientific_name="TaxonName",
    grid_ref="GridRef",
    year="RecordDate",
    common_name="CommonName",
    place="LocationName",
    abundance="Abundance",
    record_type="RecordType",
    verified="Verified",
    source="Source",
    licence="Licence",
)

SENSITIVE_ID = "2028"
ORDINARY_ID = "999999"

VIEW_COLUMNS = ColumnMap(
    record_id="unique_no",
    species_id="species_no",
    scientific_name="scientific_name",
    grid_ref="grid_ref",
    year="year_end",
    common_name="common_name",
    place="place",
    abundance="abundance",
    record_type="record_type",
    source="source",
    licence="licence",
    sensitivity="sensitive",
)

VIEW_POLICY = PublicationPolicy(
    version="main-data-dash-test",
    development_only=True,
    precision_mode="approved",
    suppression_mode="none",
    licensing_mode="not-applicable",
    record_type_safety_mode="not-used",
    row_level_records_mode="aggregates-only",
    verification_publication_mode="unavailable",
    sensitive_record_action="generalise",
    ordinary_resolution_metres=100,
    default_sensitive_metres=10000,
    row_sensitive_resolution_metres=1000,
    non_sensitive_values=frozenset({"no"}),
    public_id_salt="test" * 8,
)


def row(**over):
    base = {
        "RecordKey": "5610349",
        "SPECIES_No": ORDINARY_ID,
        "TaxonName": "Anguis fragilis",
        "CommonName": "Slow-worm",
        "GridRef": "ST585725",
        "RecordDate": "2000",
        "LocationName": "Brandon Hill",
        "Abundance": "3",
        "RecordType": "field record",
        "Verified": "Accepted - correct",
        "Source": "recorder",
        "Licence": "CC-BY",
    }
    base.update(over)
    return base


def view_row(**over):
    """A minimal row shaped exactly like dashboard.main_data_dash."""
    base = {
        "unique_no": "5610349.00",
        "species_no": ORDINARY_ID,
        "scientific_name": "Anguis fragilis",
        "common_name": "Slow-worm",
        "grid_ref": "ST587721",
        "year_end": "2024",
        "place": "Brandon Hill",
        "abundance": "1",
        "record_type": "field record",
        "source": "BRERC",
        "licence": "y",
        "sensitive": "No",
    }
    base.update(over)
    return base


def run(rows, columns=COLUMNS, *, policy=DEV, dictionary=None):
    return run_pipeline(rows, columns, policy=policy, dictionary=dictionary)


class TestColumnMappingIsExplicit(unittest.TestCase):
    def test_a_missing_required_column_raises_before_processing(self):
        rows = [{"RecordKey": "1", "TaxonName": "x", "GridRef": "ST5872", "RecordDate": "2000"}]
        with self.assertRaises(MissingColumns) as ctx:
            run(rows)
        self.assertIn("SPECIES_No", str(ctx.exception))

    def test_the_error_names_what_was_available(self):
        with self.assertRaises(MissingColumns) as ctx:
            run([{"wrong": 1}])
        self.assertIn("Available", str(ctx.exception))

    def test_a_differently_named_species_column_works_once_mapped(self):
        # The real defect in the old filtering.py: it assumed "species_id".
        columns = ColumnMap(
            record_id="id",
            species_id="taxon_key",
            scientific_name="name",
            grid_ref="ref",
            year="yr",
        )
        rows = [
            {
                "id": "1",
                "taxon_key": ORDINARY_ID,
                "name": "Anguis fragilis",
                "ref": "ST585725",
                "yr": "2000",
            }
        ]
        records, report = run(rows, columns, policy=DEV_NO_VERIFICATION)
        self.assertEqual(len(records), 1)
        self.assertTrue(report.reconciles())

    def test_optional_columns_may_be_absent(self):
        columns = ColumnMap(
            record_id="id", species_id="sp", scientific_name="name", grid_ref="ref", year="yr"
        )
        records, _ = run(
            [
                {
                    "id": "1",
                    "sp": ORDINARY_ID,
                    "name": "Anguis fragilis",
                    "ref": "ST585725",
                    "yr": "2000",
                }
            ],
            columns,
            policy=DEV_NO_VERIFICATION,
        )
        self.assertIsNone(records[0].common_name)
        self.assertEqual(records[0].source, "BRERC")

    def test_raw_source_text_is_replaced_by_the_controlled_public_label(self):
        private = "Jane Recorder, 12 Acacia Avenue"
        records, report = run([row(Source=private)])
        self.assertEqual(records[0].source, "BRERC")
        self.assertNotIn(private, str(build_candidate_payloads(records, report)))

    def test_empty_input_does_not_raise(self):
        records, report = run([])
        self.assertEqual(records, [])
        self.assertTrue(report.reconciles())


class TestMainDataDashSensitivityControl(unittest.TestCase):
    """Regression for the real view field that the export path did not carry."""

    DICTIONARY = SpeciesDictionary(
        [SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", False)]
    )

    def test_yes_on_an_ordinary_species_is_never_published_finer_than_one_kilometre(self):
        records, report = run([view_row(sensitive="Yes")], VIEW_COLUMNS, policy=VIEW_POLICY)
        self.assertTrue(report.reconciles())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].grid_ref, "ST5872")
        self.assertEqual(records[0].precision_metres, 1000)

    def test_explicit_no_keeps_the_ordinary_one_hundred_metre_resolution(self):
        records, _ = run([view_row(sensitive="No")], VIEW_COLUMNS, policy=VIEW_POLICY)
        self.assertEqual(records[0].grid_ref, "ST587721")
        self.assertEqual(records[0].precision_metres, 100)

    def test_only_the_configured_no_vocabulary_is_treated_as_not_sensitive(self):
        for marker in (None, "", "   ", "Yes", "Unknown", "nan", "0"):
            with self.subTest(marker=marker):
                records, _ = run([view_row(sensitive=marker)], VIEW_COLUMNS, policy=VIEW_POLICY)
                self.assertGreaterEqual(records[0].precision_metres, 1000)

    def test_no_does_not_override_a_sensitive_taxon(self):
        records, _ = run(
            [view_row(species_no=SENSITIVE_ID, sensitive="No")],
            VIEW_COLUMNS,
            policy=VIEW_POLICY,
        )
        self.assertEqual(records[0].precision_metres, 10000)

    def test_live_view_id_name_mismatch_is_withheld_not_relabelled_by_name(self):
        # Before this regression, supplying a dictionary made the name lookup
        # replace the live view's mapped species_no. This row therefore changed
        # from the sensitive id 2028 to the ordinary id 999999 and leaked at
        # 100 m. The source id is now authoritative and disagreement is fatal.
        records, report = run(
            [view_row(species_no=SENSITIVE_ID, sensitive="No")],
            VIEW_COLUMNS,
            policy=VIEW_POLICY,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(records, [])
        self.assertEqual(report.withheld["species-identity-mismatch"], 1)
        self.assertTrue(report.reconciles())

    def test_matching_live_view_id_is_preserved_as_the_aggregation_key(self):
        records, report = run(
            [view_row()],
            VIEW_COLUMNS,
            policy=VIEW_POLICY,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(records[0].species_id, ORDINARY_ID)
        self.assertTrue(report.reconciles())

    def test_a_coarse_source_reference_is_never_sharpened(self):
        records, _ = run(
            [view_row(grid_ref="ST57", sensitive="Yes")],
            VIEW_COLUMNS,
            policy=VIEW_POLICY,
        )
        self.assertEqual(records[0].grid_ref, "ST57")
        self.assertEqual(records[0].precision_metres, 10000)

    def test_a_later_row_missing_the_mapped_control_fails_before_processing(self):
        second = view_row(unique_no="2.00")
        del second["sensitive"]
        with self.assertRaises(MissingColumns) as ctx:
            run([view_row(), second], VIEW_COLUMNS, policy=VIEW_POLICY)
        self.assertIn("sensitive", str(ctx.exception))

    def test_the_legacy_export_mapping_refuses_a_view_control_it_would_ignore(self):
        legacy_shaped = row(sensitive="Yes")
        with self.assertRaises(UnmappedControlColumn) as ctx:
            run([legacy_shaped])
        self.assertIn("sensitive", str(ctx.exception))

    def test_mapping_the_control_without_a_row_resolution_is_invalid(self):
        with self.assertRaises(InvalidPolicy) as ctx:
            run([view_row()], VIEW_COLUMNS, policy=DEV)
        self.assertIn("row_sensitive_resolution_metres", str(ctx.exception))

    def test_a_case_mismatched_mapping_fails_loudly(self):
        wrong = dataclasses.replace(VIEW_COLUMNS, sensitivity="Sensitive")
        with self.assertRaises(MissingColumns):
            run([view_row()], wrong, policy=VIEW_POLICY)


class TestSafeV1SensitiveRecordWithholding(unittest.TestCase):
    """The approved safe-v1 shape excludes every sensitive-record axis.

    These are pipeline tests rather than unit tests for ``generalise``: they
    prove that withheld rows never become public ids, records, cells or counts.
    """

    POLICY = dataclasses.replace(
        VIEW_POLICY,
        version="safe-v1-withholding-test",
        sensitive_record_action="withhold",
        ordinary_resolution_metres=1000,
        record_type_safety_mode="rules",
        sensitive_record_type_metres={"bat roost": 10000},
        record_type_vocabulary=frozenset({"field record", "bat roost"}),
    )

    def test_all_runtime_sensitivity_axes_are_absent_from_every_public_surface(self):
        rows = [
            view_row(unique_no="ordinary", sensitive="No"),
            view_row(unique_no="row-yes", sensitive="Yes"),
            view_row(unique_no="row-blank", sensitive=""),
            view_row(
                unique_no="taxon",
                species_no=SENSITIVE_ID,
                scientific_name="Allium sphaerocephalon",
                common_name="Round-headed leek",
                sensitive="No",
            ),
            view_row(unique_no="record-type", sensitive="No", record_type="bat roost"),
        ]

        records, report = run(rows, VIEW_COLUMNS, policy=self.POLICY)

        self.assertEqual(
            [record.record_id for record in records], [self.POLICY.public_record_id("ordinary")]
        )
        self.assertEqual(
            [(record.grid_ref, record.precision_metres) for record in records], [("ST5872", 1000)]
        )
        self.assertEqual(report.withheld["sensitive-record-withheld"], 4)
        self.assertEqual(report.records_public, 1)
        self.assertEqual(report.sensitive_record_action, "withhold")
        self.assertTrue(report.reconciles())
        self.assertEqual(
            [(cell.cell_id, cell.record_count) for cell in report.aggregation.cells],
            [("ST5872", 1)],
        )

        payloads = build_candidate_payloads(records, report)
        self.assertEqual(payloads["cells"]["cells"][0]["recordCount"], 1)
        self.assertEqual(payloads["records"]["items"], [])
        for private_value in ("row-yes", "row-blank", "taxon", "record-type"):
            self.assertNotIn(private_value, str(payloads))

    def test_dictionary_sensitivity_alone_withholds_without_spatial_output(self):
        dictionary = SpeciesDictionary(
            [SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", True)]
        )

        records, report = run(
            [view_row(unique_no="dictionary-sensitive", sensitive="No")],
            VIEW_COLUMNS,
            policy=self.POLICY,
            dictionary=dictionary,
        )

        self.assertEqual(records, [])
        self.assertEqual(report.withheld, {"sensitive-record-withheld": 1})
        self.assertEqual(report.aggregation.cells, ())
        self.assertTrue(report.reconciles())

    def test_k_one_retains_an_ordinary_singleton_and_never_sharpens_coarse_input(self):
        fine, fine_report = run(
            [view_row(unique_no="singleton", sensitive="No")],
            VIEW_COLUMNS,
            policy=self.POLICY,
        )
        coarse, coarse_report = run(
            [view_row(unique_no="coarse", sensitive="No", grid_ref="ST57")],
            VIEW_COLUMNS,
            policy=self.POLICY,
        )

        self.assertEqual(self.POLICY.min_records_per_cell, 1)
        self.assertEqual((fine[0].grid_ref, fine[0].precision_metres), ("ST5872", 1000))
        self.assertEqual((coarse[0].grid_ref, coarse[0].precision_metres), ("ST57", 10000))
        self.assertEqual(fine_report.records_suppressed, 0)
        self.assertEqual(coarse_report.records_suppressed, 0)


class TestThePolicyIsRequiredAndValidated(unittest.TestCase):
    def test_omitting_the_policy_is_a_type_error(self):
        with self.assertRaises(TypeError):
            run_pipeline([row()], COLUMNS)  # type: ignore[call-arg]

    def test_an_invalid_policy_fails_before_any_row_is_processed(self):
        bad = PublicationPolicy(
            version="bad", ordinary_resolution_metres=2000, public_id_salt="x" * 32
        )
        with self.assertRaises(InvalidPolicy):
            run([row()], policy=bad)

    def test_the_report_records_which_policy_ran_and_whether_it_was_approved(self):
        _, report = run([row()])
        self.assertEqual(report.policy_version, DEV.version)
        self.assertFalse(report.policy_approved)  # development_only


class TestReleasePayloadBoundary(unittest.TestCase):
    DICTIONARY = SpeciesDictionary(
        [SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", False)]
    )

    def approved_policy(self) -> PublicationPolicy:
        today = date.today()
        return PublicationPolicy(
            version="release-test-v1",
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="rules",
            row_level_records_mode="aggregates-only",
            verification_publication_mode="unavailable",
            sensitive_record_action="generalise",
            sensitive_snapshot_version=SENSITIVE_SNAPSHOT_VERSION,
            sensitive_snapshot_sha256=SENSITIVE_SNAPSHOT_SHA256,
            ordinary_resolution_metres=100,
            default_sensitive_metres=10000,
            sensitive_record_type_metres={"bat roost": 10000},
            record_type_vocabulary=frozenset({"field record", "bat roost"}),
            species_dictionary_sha256=self.DICTIONARY.digest(),
            public_id_salt="release-test-secret-material-32bytes",
        ).with_approval(
            approved_by="Synthetic test owner",
            approver_role="Test data owner",
            approver_organisation="BRERC",
            evidence_reference="BRERC-TEST-RELEASE-001",
            approved_on=today.isoformat(),
            review_due=(today + timedelta(days=365)).isoformat(),
        )

    def test_a_stale_sensitive_snapshot_is_rejected_before_rows_are_read(self):
        def must_not_iterate():
            raise AssertionError("stale precision evidence touched a source row")
            yield {}

        stale = dataclasses.replace(
            self.approved_policy(),
            sensitive_snapshot_sha256="0" * 64,
        )
        with self.assertRaises(InvalidPolicy):
            run_pipeline(must_not_iterate(), COLUMNS, policy=stale)

    def test_an_unbound_species_dictionary_cannot_contribute_sensitivity(self):
        dictionary = SpeciesDictionary(
            [SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", True)]
        )
        with self.assertRaises(InvalidPolicy):
            run([row()], policy=self.approved_policy(), dictionary=dictionary)

    def test_a_bound_dictionary_cannot_be_omitted_from_an_approved_run(self):
        touched = False

        def must_not_iterate():
            nonlocal touched
            touched = True
            yield row(SPECIES_No="777777", TaxonName="Synthetic unlisted taxon")

        with self.assertRaises(InvalidPolicy):
            run_pipeline(must_not_iterate(), COLUMNS, policy=self.approved_policy())
        self.assertFalse(touched)

    def test_an_unlisted_id_is_not_treated_as_known_by_shape_alone(self):
        policy = dataclasses.replace(
            self.approved_policy(),
            species_dictionary_sha256=None,
            approval_digest=None,
        ).with_approval(
            approved_by="Synthetic test owner",
            approver_role="Test data owner",
            approver_organisation="BRERC",
            evidence_reference="BRERC-TEST-NO-DICTIONARY-001",
            approved_on=date.today().isoformat(),
            review_due=(date.today() + timedelta(days=365)).isoformat(),
        )
        records, report = run(
            [row(SPECIES_No="777777", TaxonName="Synthetic unlisted taxon")],
            policy=policy,
        )
        self.assertEqual(records, [])
        self.assertEqual(report.withheld["species-not-permitted"], 1)

    def test_a_changed_species_dictionary_invalidates_the_bound_run(self):
        today = date.today()
        approved_dictionary = SpeciesDictionary(
            [SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", False)]
        )
        changed_dictionary = SpeciesDictionary(
            [SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", True)]
        )
        bound = dataclasses.replace(
            self.approved_policy(),
            species_dictionary_sha256=approved_dictionary.digest(),
        ).with_approval(
            approved_by="Synthetic test owner",
            approver_role="Test data owner",
            approver_organisation="BRERC",
            evidence_reference="BRERC-TEST-DICTIONARY-001",
            approved_on=today.isoformat(),
            review_due=(today + timedelta(days=365)).isoformat(),
        )
        records, _ = run([row()], policy=bound, dictionary=approved_dictionary)
        self.assertEqual(len(records), 1)
        with self.assertRaises(InvalidPolicy):
            run([row()], policy=bound, dictionary=changed_dictionary)

    def test_an_unapproved_candidate_cannot_become_a_release_payload(self):
        records, report = run([row()])
        self.assertTrue(build_candidate_payloads(records, report)["records"])
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                records,
                report,
                policy=DEV,
                source_contract=BRERC_MAIN_DATA_DASH,
            )

    def test_candidate_preview_is_neither_a_dict_nor_json_serialisable(self):
        records, report = run([row()])
        preview = build_candidate_payloads(records, report)
        self.assertIsInstance(preview, CandidatePreview)
        self.assertNotIsInstance(preview, dict)
        with self.assertRaises(TypeError):
            json.dumps(preview)

    def test_candidate_preview_cannot_be_passed_to_the_release_builder(self):
        records, report = run([row()])
        preview = build_candidate_payloads(records, report)
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                preview,
                policy=self.approved_policy(),
                source_contract=BRERC_MAIN_DATA_DASH,
            )

    def test_candidate_preview_returns_defensive_copies(self):
        records, report = run([row()])
        preview = build_candidate_payloads(records, report)
        first = preview["records"]
        first["items"].clear()
        self.assertTrue(preview["records"]["items"])

    def test_even_an_approved_plain_pipeline_remains_candidate_only(self):
        policy = self.approved_policy()
        records, report = run([row()], policy=policy, dictionary=self.DICTIONARY)
        with self.assertRaises(PolicyNotApproved) as ctx:
            build_payloads(
                records,
                report,
                policy=policy,
                source_contract=BRERC_MAIN_DATA_DASH,
            )
        self.assertIn("ValidatedSourceRun", str(ctx.exception))

    def test_a_changed_policy_cannot_release_records_made_under_old_decisions(self):
        policy = self.approved_policy()
        records, report = run([row()], policy=policy, dictionary=self.DICTIONARY)
        changed = dataclasses.replace(policy, ordinary_resolution_metres=1000)
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                records,
                report,
                policy=changed,
                source_contract=BRERC_MAIN_DATA_DASH,
            )

    def test_a_different_approval_cannot_release_an_existing_candidate(self):
        first = self.approved_policy()
        records, report = run([row()], policy=first, dictionary=self.DICTIONARY)
        today = date.today()
        second = dataclasses.replace(first, approval_digest=None).with_approval(
            approved_by="Different synthetic owner",
            approver_role="Test data owner",
            approver_organisation="BRERC",
            evidence_reference="BRERC-TEST-RELEASE-002",
            approved_on=today.isoformat(),
            review_due=(today + timedelta(days=365)).isoformat(),
        )
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                records,
                report,
                policy=second,
                source_contract=BRERC_MAIN_DATA_DASH,
            )

    def test_records_from_another_run_cannot_be_paired_with_an_approved_report(self):
        policy = self.approved_policy()
        first_records, first_report = run(
            [row(RecordKey="first")], policy=policy, dictionary=self.DICTIONARY
        )
        other_records, _ = run(
            [row(RecordKey="second", RecordDate="2024")],
            policy=policy,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(len(first_records), len(other_records))
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                other_records,
                first_report,
                policy=policy,
                source_contract=BRERC_MAIN_DATA_DASH,
            )

    def test_a_projection_that_omits_sensitive_can_never_use_the_generic_release_path(self):
        policy = self.approved_policy()
        projected = row()
        records, report = run([projected], policy=policy, dictionary=self.DICTIONARY)
        self.assertEqual(records[0].precision_metres, 100)
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                records,
                report,
                policy=policy,
                source_contract=BRERC_MAIN_DATA_DASH,
            )

    def test_the_null_policy_refuses_to_run_rather_than_publishing_nothing(self):
        # A run that quietly yields zero records looks like a data problem. A
        # refusal names the actual cause: nobody has decided what may be shown.
        with self.assertRaises(InvalidPolicy) as ctx:
            run([row(RecordKey=str(i)) for i in range(5)], policy=UNAPPROVED_POLICY)
        self.assertIn("unapproved-draft", str(ctx.exception))


class TestNothingLeaks(unittest.TestCase):
    """Raw rows carrying every forbidden field must produce clean payloads."""

    SENSITIVE_COLUMNS = dataclasses.replace(COLUMNS, sensitivity="Sensitivity")
    SENSITIVE_POLICY = dataclasses.replace(
        DEV,
        row_sensitive_resolution_metres=1000,
        non_sensitive_values=frozenset({"no"}),
    )

    def dirty_row(self, **over):
        return row(
            Recorder1="A Recorder",
            BLISS="internal-note",
            Eastings=358500,
            Northings=172500,
            easting=358500,
            northing=172500,
            Comments="found under a tin near the path",
            Sensitivity="HIGH",
            PreciseGridRef="ST5850072500",
            PreciseDate="2000-06-14",
            **over,
        )

    def test_forbidden_fields_never_reach_the_payloads(self):
        rows = [self.dirty_row(RecordKey=str(i)) for i in range(5)]
        records, report = run(rows, self.SENSITIVE_COLUMNS, policy=self.SENSITIVE_POLICY)
        self.assertEqual(len(records), len(rows))
        self.assertEqual(report.records_public, len(rows))
        self.assertTrue(report.reconciles())
        payloads = build_candidate_payloads(records, report)
        self.assertEqual(assert_no_forbidden_fields(payloads), [])

    def test_the_test_data_really_does_contain_the_forbidden_fields(self):
        # Guards against a vacuous pass if the alias set grows but the fixture
        # does not. This tests detection; the separate pipeline tests prove the
        # row-level sensitivity value changes the public resolution.
        found = assert_no_forbidden_fields(dict.fromkeys(FORBIDDEN_FIELDS, "hostile"))
        self.assertEqual(len(found), len(FORBIDDEN_FIELDS))

    def test_precise_coordinates_are_absent_from_every_record(self):
        records, _ = run([self.dirty_row()], self.SENSITIVE_COLUMNS, policy=self.SENSITIVE_POLICY)
        self.assertEqual(len(records), 1)
        for item in (r.to_api() for r in records):
            for value in item.values():
                self.assertNotIn("358500", str(value))
                self.assertNotIn("ST5850072500", str(value))

    def test_recorder_name_is_absent_from_every_record(self):
        records, _ = run([self.dirty_row()], self.SENSITIVE_COLUMNS, policy=self.SENSITIVE_POLICY)
        self.assertEqual(len(records), 1)
        for item in (r.to_api() for r in records):
            self.assertNotIn("A Recorder", str(item))


class TestPlaceNamesAreGatedByPolicy(unittest.TestCase):
    """A place name can defeat generalisation entirely. A 10 km square beside
    "Private garden, 12 Acacia Avenue" is not generalised in any useful sense."""

    def test_place_is_withheld_by_default(self):
        records, _ = run([row(LocationName="Private garden, 12 Acacia Avenue")])
        self.assertIsNone(records[0].place)

    def test_the_place_string_does_not_survive_anywhere_in_the_payload(self):
        records, report = run([row(LocationName="Private garden, 12 Acacia Avenue")])
        self.assertNotIn("Acacia", str(build_candidate_payloads(records, report)))

    def test_place_is_published_only_when_the_policy_says_so(self):
        policy = PublicationPolicy(
            version="t",
            development_only=True,
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="not-used",
            row_level_records_mode="publish",
            verification_publication_mode="unavailable",
            ordinary_resolution_metres=100,
            publish_place_names=True,
            publish_individual_records=True,
            public_id_salt="x" * 32,
        )
        records, _ = run([row(LocationName="Brandon Hill")], policy=policy)
        self.assertEqual(records[0].place, "Brandon Hill")


class TestPublicRecordIdsAreNotReversible(unittest.TestCase):
    def test_the_brerc_record_number_is_not_published(self):
        records, _ = run([row(RecordKey="5610349")])
        self.assertNotEqual(records[0].record_id, "5610349")
        self.assertNotIn("5610349", records[0].record_id)

    def test_the_original_appears_nowhere_in_the_payload(self):
        records, report = run([row(RecordKey="5610349")])
        self.assertNotIn("5610349", str(build_candidate_payloads(records, report)))

    def test_ids_are_stable_across_runs(self):
        first, _ = run([row(RecordKey="5610349")])
        second, _ = run([row(RecordKey="5610349")])
        self.assertEqual(first[0].record_id, second[0].record_id)

    def test_distinct_records_keep_distinct_ids(self):
        rows = [row(RecordKey=str(i), GridRef="ST585725") for i in range(200)]
        records, _ = run(rows)
        self.assertEqual(len({r.record_id for r in records}), 200)

    def test_a_duplicated_source_id_is_a_loud_failure_not_a_silent_merge(self):
        rows = [
            row(RecordKey="same", GridRef="ST585725"),
            row(RecordKey="same", GridRef="ST597728"),
        ]
        with self.assertRaises(DuplicatePublicId):
            run(rows)


class TestSensitiveRecordsAreGeneralisedNotDropped(unittest.TestCase):
    def test_a_sensitive_record_survives_at_a_coarser_resolution(self):
        records, _ = run([row(SPECIES_No=SENSITIVE_ID, GridRef="ST5877972166")])
        self.assertEqual(len(records), 1)  # not dropped
        self.assertEqual(records[0].precision_metres, DEV.default_sensitive_metres)
        self.assertEqual(records[0].grid_ref, "ST57")

    def test_an_ordinary_record_keeps_the_policy_resolution(self):
        records, _ = run([row(GridRef="ST585725")])
        self.assertEqual(records[0].precision_metres, 100)

    def test_mixed_input_yields_cells_at_both_resolutions(self):
        rows = [
            row(RecordKey="a", GridRef="ST585725"),
            row(RecordKey="b", SPECIES_No=SENSITIVE_ID, GridRef="ST587721"),
        ]
        _, report = run(rows)
        self.assertEqual(report.aggregation.resolutions_emitted, (1000, 10000))

    def test_no_public_record_is_finer_than_its_species_allows(self):
        rows = [
            row(RecordKey=str(i), SPECIES_No=SENSITIVE_ID, GridRef=ref)
            for i, ref in enumerate(["ST5877972166", "ST58777216", "ST587721", "ST5872"])
        ]
        records, _ = run(rows)
        for rec in records:
            self.assertGreaterEqual(rec.precision_metres, DEV.default_sensitive_metres)

    def test_map_base_resolution_comes_from_the_policy(self):
        policy = dataclasses.replace(
            DEV,
            version="ten-kilometre-map-development",
            map_cell_resolution_metres=10000,
        )
        _, report = run([row(GridRef="ST585725")], policy=policy)
        self.assertEqual(
            [(cell.cell_id, cell.precision_metres) for cell in report.aggregation.cells],
            [("ST57", 10000)],
        )


class TestSensitiveRecordTypes(unittest.TestCase):
    """The second sensitivity axis: 47 types align to ``sensitive=yes`` in the
    supplied workbook, with two anomalies still requiring BRERC resolution."""

    POLICY = PublicationPolicy(
        version="t",
        development_only=True,
        sensitive_record_action="generalise",
        precision_mode="approved",
        suppression_mode="none",
        licensing_mode="not-applicable",
        record_type_safety_mode="rules",
        row_level_records_mode="aggregates-only",
        verification_publication_mode="unavailable",
        ordinary_resolution_metres=100,
        default_sensitive_metres=10000,
        sensitive_record_type_metres={
            "bat roost": 10000,
            "bedding (badger sensitive record)": 10000,
        },
        record_type_vocabulary=frozenset(
            {
                "field record",
                "bat roost",
                "bedding (badger sensitive record)",
            }
        ),
        public_id_salt="x" * 32,
    )

    def test_a_common_species_at_a_bat_roost_is_still_coarsened(self):
        records, _ = run([row(RecordType="bat roost", GridRef="ST5877972166")], policy=self.POLICY)
        self.assertEqual(records[0].precision_metres, 10000)

    def test_a_badger_sett_record_is_coarsened(self):
        records, _ = run(
            [row(RecordType="bedding (badger sensitive record)", GridRef="ST5877972166")],
            policy=self.POLICY,
        )
        self.assertEqual(records[0].precision_metres, 10000)

    def test_an_ordinary_record_type_is_unaffected(self):
        records, _ = run(
            [row(RecordType="field record", GridRef="ST5877972166")], policy=self.POLICY
        )
        self.assertEqual(records[0].precision_metres, 100)

    def test_blank_or_new_record_types_are_withheld_not_assumed_ordinary(self):
        for value in (None, "", "new survey method"):
            with self.subTest(value=value):
                records, report = run([row(RecordType=value)], policy=self.POLICY)
                self.assertEqual(records, [])
                self.assertEqual(report.withheld["record-type-not-permitted"], 1)
                self.assertTrue(report.reconciles())

    def test_configured_rules_cannot_run_without_a_record_type_mapping(self):
        unmapped = dataclasses.replace(COLUMNS, record_type=None)
        for rows in ([], [row()]):
            with self.subTest(rows=len(rows)), self.assertRaises(InvalidPolicy) as ctx:
                run(rows, columns=unmapped, policy=self.POLICY)
            self.assertIn("left dormant", str(ctx.exception))

    def test_a_mapped_record_type_must_exist_on_every_row(self):
        source = row()
        del source["RecordType"]
        with self.assertRaises(MissingColumns) as ctx:
            run([source], policy=self.POLICY)
        self.assertIn("RecordType", str(ctx.exception))

    def test_a_different_unmapped_record_type_alias_is_refused(self):
        columns = dataclasses.replace(COLUMNS, record_type="Kind")
        source = row(Kind="field record")
        with self.assertRaises(UnmappedControlColumn) as ctx:
            run([source], columns=columns, policy=self.POLICY)
        self.assertIn("RecordType", str(ctx.exception))


class TestLicenceGate(unittest.TestCase):
    POLICY = PublicationPolicy(
        version="t",
        development_only=True,
        sensitive_record_action="generalise",
        precision_mode="approved",
        suppression_mode="none",
        licensing_mode="all-publication-allow-list",
        record_type_safety_mode="not-used",
        row_level_records_mode="aggregates-only",
        verification_publication_mode="unavailable",
        ordinary_resolution_metres=100,
        allowed_licence_values=frozenset({"cc-by", "ogl"}),
        public_id_salt="x" * 32,
    )

    def test_a_permitted_licence_publishes(self):
        records, _ = run([row(Licence="CC-BY")], policy=self.POLICY)
        self.assertEqual(len(records), 1)

    def test_an_unrecognised_licence_is_withheld_with_a_reason(self):
        records, report = run([row(Licence="all rights reserved")], policy=self.POLICY)
        self.assertEqual(records, [])
        self.assertIn("licence-not-permitted", report.withheld)
        self.assertTrue(report.reconciles())

    def test_a_missing_licence_fails_closed(self):
        records, _ = run([row(Licence="")], policy=self.POLICY)
        self.assertEqual(records, [])

    def test_an_explicit_not_applicable_decision_does_not_gate(self):
        records, _ = run([row(Licence="anything at all")])
        self.assertEqual(len(records), 1)


class TestSuppressionIsConsistentAcrossTheWholeView(unittest.TestCase):
    """Hiding a sparse map cell while still listing its records in the table, and
    counting them in the year series, does not suppress anything."""

    POLICY = PublicationPolicy(
        version="t",
        development_only=True,
        precision_mode="approved",
        suppression_mode="minimum-count",
        licensing_mode="not-applicable",
        record_type_safety_mode="not-used",
        row_level_records_mode="aggregates-only",
        verification_publication_mode="unavailable",
        sensitive_record_action="generalise",
        ordinary_resolution_metres=100,
        min_records_per_cell=2,
        public_id_salt="x" * 32,
    )

    def rows(self):
        # ST5872 gets two records; ST5972 gets one and must be suppressed.
        return [
            row(RecordKey="a", GridRef="ST585725"),
            row(RecordKey="b", GridRef="ST587721"),
            row(RecordKey="c", GridRef="ST597728"),
        ]

    def test_the_sparse_cell_is_not_published(self):
        _, report = run(self.rows(), policy=self.POLICY)
        self.assertEqual([c.cell_id for c in report.aggregation.cells], ["ST5872"])

    def test_its_records_are_not_published_either(self):
        records, _ = run(self.rows(), policy=self.POLICY)
        self.assertEqual(len(records), 2)
        self.assertNotIn("ST5972", {r.grid_ref[:6] for r in records})

    def test_the_year_series_matches_the_surviving_records(self):
        records, report = run(self.rows(), policy=self.POLICY)
        payloads = build_candidate_payloads(records, report)
        self.assertEqual(sum(p["count"] for p in payloads["meta"]["recordsByYear"]), len(records))

    def test_suppressed_rows_are_counted_and_the_run_still_reconciles(self):
        _, report = run(self.rows(), policy=self.POLICY)
        self.assertEqual(report.records_suppressed, 1)
        self.assertEqual(report.cell_cohorts_suppressed, 1)
        # The final aggregation is rebuilt from survivors; its local low-count
        # number is correctly zero, so the pipeline ledger must retain the
        # pre-rebuild cohort count separately.
        self.assertEqual(report.aggregation.cells_suppressed_low_count, 0)
        self.assertEqual(report.withheld["suppressed-sparse-cell"], 1)
        self.assertTrue(report.reconciles())

    def test_the_cell_totals_equal_the_published_record_count(self):
        records, report = run(self.rows(), policy=self.POLICY)
        self.assertEqual(sum(c.record_count for c in report.aggregation.cells), len(records))

    def test_unrelated_species_cannot_combine_to_clear_a_suppression_threshold(self):
        rows = [
            row(RecordKey="a", SPECIES_No="999998", GridRef="ST585725"),
            row(RecordKey="b", SPECIES_No="999999", GridRef="ST585725"),
        ]
        records, report = run(rows, policy=self.POLICY)
        self.assertEqual(records, [])
        self.assertEqual(report.records_suppressed, 2)
        self.assertEqual(report.aggregation.cells, ())

    def test_different_years_cannot_combine_to_clear_a_suppression_threshold(self):
        rows = [
            row(RecordKey="a", RecordDate="2023", GridRef="ST585725"),
            row(RecordKey="b", RecordDate="2024", GridRef="ST585725"),
        ]
        records, report = run(rows, policy=self.POLICY)
        self.assertEqual(records, [])
        self.assertEqual(report.records_suppressed, 2)
        self.assertEqual(report.aggregation.cells, ())

    def test_sensitive_candidates_are_suppressed_under_the_same_cohort_rule(self):
        records, report = run(
            [row(SPECIES_No=SENSITIVE_ID, GridRef="ST587721")],
            policy=self.POLICY,
        )
        self.assertEqual(records, [])
        self.assertEqual(report.records_suppressed, 1)
        self.assertEqual(report.cell_cohorts_suppressed, 1)
        self.assertTrue(report.reconciles())


class TestPayloadsAreSpeciesScoped(unittest.TestCase):
    def test_a_multi_species_candidate_requires_an_explicit_species(self):
        records, report = run(
            [
                row(RecordKey="a", SPECIES_No="999998"),
                row(RecordKey="b", SPECIES_No="999999"),
            ]
        )
        with self.assertRaises(ValueError):
            build_candidate_payloads(records, report)
        scoped = build_candidate_payloads(records, report, species_id="999999")
        self.assertEqual(scoped["records"]["total"], 1)
        self.assertEqual(scoped["cells"]["cells"][0]["recordCount"], 1)

    def test_year_filter_keeps_records_cells_and_totals_in_sync(self):
        records, report = run(
            [
                row(RecordKey="a", RecordDate="2023"),
                row(RecordKey="b", RecordDate="2024"),
            ]
        )
        all_years = build_candidate_payloads(records, report)
        selected = build_candidate_payloads(records, report, year=2023)
        self.assertEqual(all_years["records"]["total"], 2)
        self.assertEqual(all_years["cells"]["cells"][0]["recordCount"], 2)
        self.assertEqual(selected["records"]["total"], 1)
        self.assertEqual(selected["cells"]["cells"][0]["recordCount"], 1)
        self.assertEqual(selected["meta"]["recordsByYear"], [{"year": 2023, "count": 1}])


class TestIndividualRecordPublicationIsExplicit(unittest.TestCase):
    def test_aggregate_and_row_verification_decisions_are_independent(self):
        cases = (
            # Global aggregate verification, occurrence rows, per-row verdicts.
            ("unavailable-aggregates", "unavailable", False, False, False, False),
            ("unavailable-rows", "unavailable", True, False, False, False),
            ("publish-aggregates", "publish", False, False, True, False),
            ("publish-rows", "publish", True, True, True, True),
            # The HOLD regression: aggregate counts may be public while each
            # occurrence verdict remains independently withheld.
            ("publish-rows-verdict-hidden", "publish", True, False, True, False),
        )
        for (
            name,
            verification_mode,
            publish_rows,
            publish_row_verdict,
            aggregate_available,
            row_verdict_visible,
        ) in cases:
            with self.subTest(name=name):
                policy = PublicationPolicy(
                    version=name,
                    development_only=True,
                    precision_mode="approved",
                    suppression_mode="none",
                    licensing_mode="not-applicable",
                    record_type_safety_mode="not-used",
                    row_level_records_mode=("publish" if publish_rows else "aggregates-only"),
                    verification_publication_mode=verification_mode,
                    ordinary_resolution_metres=100,
                    publish_individual_records=publish_rows,
                    publish_record_verification=publish_row_verdict,
                    public_id_salt="x" * 32,
                )
                records, report = run([row(Verified="Accepted")], policy=policy)
                payloads = build_candidate_payloads(records, report)
                cell = payloads["cells"]["cells"][0]
                items = payloads["records"]["items"]

                self.assertEqual(report.verification_available, aggregate_available)
                self.assertEqual(
                    payloads["cells"]["verificationAvailable"],
                    aggregate_available,
                )
                self.assertEqual("verifiedCount" in cell, aggregate_available)
                self.assertEqual(bool(items), publish_rows)
                self.assertEqual(
                    payloads["records"]["publication"]["fields"]["verification"],
                    row_verdict_visible,
                )
                if items:
                    self.assertEqual("verified" in items[0], row_verdict_visible)

    def test_default_policy_publishes_cells_but_no_individual_rows(self):
        policy = PublicationPolicy(
            version="aggregates-only",
            development_only=True,
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="not-used",
            row_level_records_mode="aggregates-only",
            verification_publication_mode="unavailable",
            ordinary_resolution_metres=100,
            public_id_salt="x" * 32,
        )
        records, report = run([row()], policy=policy)
        self.assertEqual(len(records), 1)  # internal aggregation candidate
        payloads = build_candidate_payloads(records, report)
        self.assertEqual(payloads["records"]["items"], [])
        self.assertEqual(payloads["records"]["total"], 0)
        self.assertEqual(
            payloads["records"]["publication"],
            {
                "mode": "aggregates-only",
                "fields": {
                    "abundance": False,
                    "place": False,
                    "recordType": False,
                    "verification": False,
                },
            },
        )
        self.assertEqual(payloads["cells"]["cells"][0]["recordCount"], 1)

    def test_row_fields_are_independently_withheld(self):
        policy = PublicationPolicy(
            version="rows-with-minimal-fields",
            development_only=True,
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="not-used",
            row_level_records_mode="publish",
            verification_publication_mode="unavailable",
            ordinary_resolution_metres=100,
            publish_individual_records=True,
            publish_abundance=False,
            publish_record_type=False,
            public_id_salt="x" * 32,
        )
        records, report = run(
            [row(Abundance="one occupied nest", RecordType="bat roost")],
            policy=policy,
        )
        item = build_candidate_payloads(records, report)["records"]["items"][0]
        self.assertIsNone(item["abundance"])
        self.assertIsNone(item["recordType"])

    def test_aggregate_verification_does_not_enable_row_verification(self):
        policy = PublicationPolicy(
            version="aggregate-verification-only",
            development_only=True,
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="not-used",
            row_level_records_mode="aggregates-only",
            verification_publication_mode="publish",
            ordinary_resolution_metres=100,
            public_id_salt="x" * 32,
        )
        records, report = run([row(Verified="Accepted")], policy=policy)
        payloads = build_candidate_payloads(records, report)
        self.assertTrue(payloads["cells"]["verificationAvailable"])
        self.assertEqual(payloads["cells"]["cells"][0]["verifiedCount"], 1)
        self.assertFalse(payloads["records"]["publication"]["fields"]["verification"])
        self.assertEqual(payloads["records"]["items"], [])

    def test_aggregate_verification_with_rows_does_not_expose_row_verdicts(self):
        policy = PublicationPolicy(
            version="aggregate-verification-with-rows",
            development_only=True,
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="not-used",
            row_level_records_mode="publish",
            verification_publication_mode="publish",
            ordinary_resolution_metres=100,
            publish_individual_records=True,
            publish_record_verification=False,
            public_id_salt="x" * 32,
        )
        records, report = run([row(Verified="Accepted")], policy=policy)
        payloads = build_candidate_payloads(records, report)
        self.assertTrue(payloads["cells"]["verificationAvailable"])
        self.assertEqual(payloads["cells"]["cells"][0]["verifiedCount"], 1)
        self.assertFalse(payloads["records"]["publication"]["fields"]["verification"])
        self.assertNotIn("verified", payloads["records"]["items"][0])

    def test_row_verification_decision_is_bound_into_report_and_candidate_digest(self):
        hidden = dataclasses.replace(
            DEVELOPMENT_POLICY,
            version="row-verdict-hidden",
            publish_record_verification=False,
        )
        visible = dataclasses.replace(
            DEVELOPMENT_POLICY,
            version="row-verdict-visible",
            publish_record_verification=True,
        )
        hidden_records, hidden_report = run([row()], policy=hidden)
        visible_records, visible_report = run([row()], policy=visible)

        self.assertEqual(hidden_records, visible_records)
        self.assertFalse(hidden_report.summary()["publishRecordVerification"])
        self.assertTrue(visible_report.summary()["publishRecordVerification"])
        self.assertNotEqual(hidden_report.candidate_digest, visible_report.candidate_digest)

    def test_unavailable_verification_ignores_a_mapped_verdict_column(self):
        policy = PublicationPolicy(
            version="verification-unavailable",
            development_only=True,
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="not-used",
            row_level_records_mode="publish",
            verification_publication_mode="unavailable",
            ordinary_resolution_metres=100,
            publish_individual_records=True,
            public_id_salt="x" * 32,
        )
        records, report = run([row(Verified="Accepted")], policy=policy)
        payloads = build_candidate_payloads(records, report)
        self.assertEqual(records[0].verified, "unknown")
        self.assertFalse(payloads["cells"]["verificationAvailable"])
        self.assertNotIn("verifiedCount", payloads["cells"]["cells"][0])
        self.assertNotIn("verified", payloads["records"]["items"][0])

    def test_publish_verification_requires_a_mapped_verdict_column(self):
        unmapped = dataclasses.replace(COLUMNS, verified=None)
        with self.assertRaises(InvalidPolicy):
            run([row()], columns=unmapped, policy=DEV)


class TestWithheldRowsAreAccountedFor(unittest.TestCase):
    def test_every_row_is_published_or_withheld_with_a_reason(self):
        rows = [
            row(RecordKey="a"),
            row(RecordKey="b", GridRef=""),
            row(RecordKey="c", GridRef="nonsense"),
            row(RecordKey="d", RecordDate=""),
            row(RecordKey="e", TaxonName=""),
            row(RecordKey=""),
        ]
        _, report = run(rows)
        self.assertEqual(report.rows_in, 6)
        self.assertEqual(report.records_public, 1)
        self.assertEqual(report.rows_withheld, 5)
        self.assertTrue(report.reconciles())

    def test_reconciliation_is_exact_not_an_inequality(self):
        # `<=` would pass while rows vanished, which is the failure this detects.
        rows = [row(RecordKey=str(i)) for i in range(10)]
        _, report = run(rows)
        self.assertEqual(report.rows_in, report.records_public + report.rows_withheld)

    def test_withholding_reasons_are_named(self):
        rows = [row(RecordKey="b", GridRef=""), row(RecordKey="c", GridRef="nonsense")]
        _, report = run(rows)
        self.assertIn("missing-grid-ref", report.withheld)
        self.assertIn("unparseable-grid-ref", report.withheld)

    def test_an_out_of_range_year_is_withheld(self):
        for bad in ("", "not-a-year", "0042", "9999", 2023.1, "2023.1"):
            with self.subTest(year=bad):
                _, report = run([row(RecordDate=bad)])
                self.assertEqual(report.records_public, 0)
                self.assertIn("unusable-year", report.withheld)

    def test_an_iso_date_yields_its_year(self):
        records, _ = run([row(RecordDate="2011-06-14")])
        self.assertEqual(records[0].year, 2011)

    def test_the_summary_is_structural_and_carries_no_record_content(self):
        _, report = run([row(LocationName="Private garden, 12 Acacia Avenue")])
        summary = str(report.summary())
        self.assertNotIn("Acacia", summary)
        self.assertNotIn("ST585725", summary)
        self.assertIn("rowsIn", summary)


class TestSpeciesDictionaryJoin(unittest.TestCase):
    """The real exports carry no species-id column, so the gate cannot run on an
    occurrence row alone - every row is resolved through the dictionary by name."""

    DICTIONARY = SpeciesDictionary(
        [
            SpeciesRecord("999999", "Anguis fragilis", "Slow-worm", False),
            SpeciesRecord("2028", "Allium sphaerocephalon", "Round-headed leek", True),
        ]
    )

    COLUMNS = ColumnMap(
        record_id="unique_No",
        species_id="SPECIES_NO",
        scientific_name="Scientific_Name",
        grid_ref="Grid_Ref",
        year="YearEnd",
        common_name="Common_Name",
    )

    def source_row(self, **over):
        base = {
            "unique_No": "1",
            "Scientific_Name": "Anguis fragilis",
            "Common_Name": "Slow-worm",
            "Grid_Ref": "ST5877972166",
            "YearEnd": 2023,
        }
        base.update(over)
        return base

    def test_the_species_id_column_may_be_absent_entirely(self):
        records, report = run(
            [self.source_row()],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].species_id, ORDINARY_ID)
        self.assertTrue(report.reconciles())

    def test_a_present_species_id_is_authoritative_and_cross_checked(self):
        records, report = run(
            [self.source_row(SPECIES_NO=ORDINARY_ID)],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(records[0].species_id, ORDINARY_ID)
        self.assertTrue(report.reconciles())

    def test_a_present_but_blank_species_id_never_falls_back_to_the_name(self):
        records, report = run(
            [self.source_row(SPECIES_NO="  ")],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(records, [])
        self.assertEqual(report.withheld["missing-species-id"], 1)
        self.assertTrue(report.reconciles())

    def test_a_partially_missing_species_id_column_is_a_shape_error(self):
        with_id = self.source_row(unique_No="1", SPECIES_NO=ORDINARY_ID)
        without_id = self.source_row(unique_No="2")
        with self.assertRaises(MissingColumns) as ctx:
            run(
                [with_id, without_id],
                self.COLUMNS,
                policy=DEV_NO_VERIFICATION,
                dictionary=self.DICTIONARY,
            )
        self.assertIn("SPECIES_NO", str(ctx.exception))

    def test_a_resolved_ordinary_name_publishes_at_the_policy_resolution(self):
        records, _ = run(
            [self.source_row()],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(records[0].precision_metres, 100)

    def test_a_resolved_sensitive_name_is_coarsened(self):
        records, _ = run(
            [self.source_row(Scientific_Name="Allium sphaerocephalon")],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(records[0].precision_metres, 10000)

    def test_the_dictionary_sensitivity_flag_is_honoured_for_an_unlisted_id(self):
        # An id absent from our retained snapshot, flagged sensitive by BRERC.
        dictionary = SpeciesDictionary([SpeciesRecord("777777", "Newly protected sp.", None, True)])
        records, _ = run(
            [self.source_row(Scientific_Name="Newly protected sp.")],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=dictionary,
        )
        self.assertEqual(records[0].precision_metres, 10000)

    def test_an_unresolved_name_is_withheld_not_treated_as_ordinary(self):
        records, report = run(
            [self.source_row(Scientific_Name="Nonexistent sp.")],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=self.DICTIONARY,
        )
        self.assertEqual(records, [])
        self.assertIn("species-not-permitted", report.withheld)
        self.assertTrue(report.reconciles())

    def test_an_ambiguous_dictionary_name_is_withheld_even_when_an_id_is_present(self):
        dictionary = SpeciesDictionary(
            [
                SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", False),
                SpeciesRecord(SENSITIVE_ID, "Anguis fragilis", "Slow-worm", True),
            ]
        )
        records, report = run(
            [self.source_row(SPECIES_NO=ORDINARY_ID)],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=dictionary,
        )
        self.assertEqual(records, [])
        self.assertEqual(report.withheld["ambiguous-species-name"], 1)
        self.assertTrue(report.reconciles())

    def test_an_ambiguous_dictionary_name_cannot_be_used_as_a_fallback(self):
        dictionary = SpeciesDictionary(
            [
                SpeciesRecord(ORDINARY_ID, "Anguis fragilis", "Slow-worm", False),
                SpeciesRecord(SENSITIVE_ID, "Anguis fragilis", "Slow-worm", True),
            ]
        )
        records, report = run(
            [self.source_row()],
            self.COLUMNS,
            policy=DEV_NO_VERIFICATION,
            dictionary=dictionary,
        )
        self.assertEqual(records, [])
        self.assertEqual(report.withheld["ambiguous-species-name"], 1)
        self.assertTrue(report.reconciles())


class TestPayloadKeysMatchTheStrictSchemas(unittest.TestCase):
    """The client schemas are .strict(): an unrecognised key is a HARD failure.

    A stray key does not degrade gracefully - the parse throws, the query fails,
    and the UI renders a network error. So the key sets are asserted here rather
    than discovered in a browser.
    """

    def test_the_cell_payload_carries_exactly_what_the_schema_accepts(self):
        # web/src/lib/api/schemas.ts:
        #   CellDistributionSchema = z.object({ verificationAvailable, cells }).strict()
        records, report = run([row(GridRef="ST585725")])
        payload = build_candidate_payloads(records, report)["cells"]
        self.assertEqual(set(payload), {"verificationAvailable", "cells"})
        self.assertTrue(payload["verificationAvailable"])

    def test_the_record_page_payload_carries_exactly_what_the_schema_accepts(self):
        #   RecordPageSchema also carries the explicit publication capabilities.
        records, report = run([row(GridRef="ST585725")])
        payload = build_candidate_payloads(records, report)["records"]
        self.assertEqual(
            set(payload),
            {"items", "page", "pageSize", "total", "publication"},
        )
        self.assertEqual(
            payload["publication"],
            {
                "mode": "individual-records",
                "fields": {
                    "abundance": True,
                    "place": False,
                    "recordType": True,
                    "verification": True,
                },
            },
        )

    def test_a_record_row_carries_exactly_what_the_schema_accepts(self):
        #   RecordRowSchema, .strict()
        records, _ = run([row()])
        self.assertEqual(
            set(records[0].to_api()),
            {
                "id",
                "scientificName",
                "commonName",
                "gridRef",
                "precisionMetres",
                "place",
                "year",
                "abundance",
                "recordType",
                "verified",
                "source",
            },
        )

    def test_a_grid_cell_carries_exactly_what_the_schema_accepts(self):
        #   GridCellSchema, .strict()
        _, report = run([row()])
        self.assertEqual(
            set(report.aggregation.cells[0].to_api()),
            {"cellId", "precisionMetres", "recordCount", "verifiedCount"},
        )

    def test_derived_figures_live_outside_the_contract_shapes(self):
        # Kept under "meta" precisely so nothing can drift into a strict schema.
        records, report = run([row()])
        payloads = build_candidate_payloads(records, report)
        self.assertEqual(set(payloads.keys()), {"cells", "records", "meta"})
        self.assertIn("recordsByYear", payloads["meta"])
        self.assertIn("totalRecords", payloads["meta"])

    def test_an_extra_key_would_be_caught_before_it_reached_a_browser(self):
        from etl.pipeline import CELL_DISTRIBUTION_KEYS, _assert_exact_keys

        with self.assertRaises(AssertionError) as ctx:
            _assert_exact_keys(
                {"cells": [], "totalRecords": 3}, CELL_DISTRIBUTION_KEYS, "CellDistributionSchema"
            )
        self.assertIn("totalRecords", str(ctx.exception))


class TestPaging(unittest.TestCase):
    def test_a_later_page_returns_the_next_window(self):
        rows = [row(RecordKey=str(i), GridRef="ST585725") for i in range(250)]
        records, report = run(rows)
        first = build_candidate_payloads(records, report, page_size=100, page=1)["records"]
        second = build_candidate_payloads(records, report, page_size=100, page=2)["records"]
        third = build_candidate_payloads(records, report, page_size=100, page=3)["records"]
        self.assertEqual(len(first["items"]), 100)
        self.assertEqual(len(second["items"]), 100)
        self.assertEqual(len(third["items"]), 50)
        ids = {r["id"] for r in first["items"]} | {r["id"] for r in second["items"]}
        self.assertEqual(len(ids), 200)

    def test_every_page_reports_the_same_total(self):
        rows = [row(RecordKey=str(i), GridRef="ST585725") for i in range(250)]
        records, report = run(rows)
        for page in (1, 2, 3, 4):
            payload = build_candidate_payloads(records, report, page_size=100, page=page)["records"]
            self.assertEqual(payload["total"], 250)
            self.assertGreater(payload["pageSize"], 0)
            self.assertGreaterEqual(payload["page"], 1)

    def test_a_page_beyond_the_end_is_empty_but_still_valid(self):
        records, report = run([row()])
        payload = build_candidate_payloads(records, report, page_size=100, page=9)["records"]
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["page"], 9)
        self.assertGreater(payload["pageSize"], 0)

    def test_a_page_below_one_is_rejected(self):
        records, report = run([row()])
        with self.assertRaises(ValueError):
            build_candidate_payloads(records, report, page=0)

    def test_page_and_page_size_require_real_positive_integers(self):
        records, report = run([row()])
        for argument in (True, 1.5, "1", None):
            with self.subTest(page=argument), self.assertRaises(ValueError):
                build_candidate_payloads(records, report, page=argument)  # type: ignore[arg-type]
            with self.subTest(page_size=argument), self.assertRaises(ValueError):
                build_candidate_payloads(  # type: ignore[arg-type]
                    records,
                    report,
                    page_size=argument,
                )


class TestPayloadsMatchTheClientContract(unittest.TestCase):
    def test_cell_ids_resolve_to_their_stated_precision(self):
        rows = [
            row(RecordKey="a", GridRef="ST585725"),
            row(RecordKey="b", SPECIES_No=SENSITIVE_ID, GridRef="ST587721"),
        ]
        records, report = run(rows)
        for species_id in {record.species_id for record in records}:
            payload = build_candidate_payloads(records, report, species_id=species_id)
            for cell in payload["cells"]["cells"]:
                self.assertEqual(precision_metres(cell["cellId"]), cell["precisionMetres"])

    def test_record_grid_refs_resolve_to_their_stated_precision(self):
        records, report = run([row(GridRef="ST585725")])
        for item in build_candidate_payloads(records, report)["records"]["items"]:
            self.assertEqual(precision_metres(item["gridRef"]), item["precisionMetres"])

    def test_page_size_is_positive_even_for_an_empty_result_set(self):
        # RecordPageSchema.pageSize is z.number().int().positive(). An earlier
        # version used len(records), so an empty result produced pageSize 0 and
        # the client rendered a network error instead of an empty state.
        records, report = run([])
        payload = build_candidate_payloads(records, report)["records"]
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["total"], 0)
        self.assertGreater(payload["pageSize"], 0)
        self.assertEqual(payload["pageSize"], DEFAULT_PAGE_SIZE)

    def test_page_size_is_positive_for_a_single_record(self):
        records, report = run([row()])
        self.assertGreater(build_candidate_payloads(records, report)["records"]["pageSize"], 0)

    def test_a_page_size_below_one_is_rejected(self):
        records, report = run([row()])
        with self.assertRaises(ValueError):
            build_candidate_payloads(records, report, page_size=0)

    def test_a_page_never_exceeds_its_stated_size(self):
        rows = [row(RecordKey=str(i), GridRef="ST585725") for i in range(250)]
        records, report = run(rows)
        payload = build_candidate_payloads(records, report)["records"]
        self.assertEqual(len(payload["items"]), DEFAULT_PAGE_SIZE)
        self.assertEqual(payload["total"], 250)

    def test_year_range_is_null_for_an_empty_result_set(self):
        records, report = run([])
        self.assertIsNone(build_candidate_payloads(records, report)["meta"]["yearRange"])

    def test_verified_count_never_exceeds_record_count(self):
        rows = [
            row(RecordKey=str(i), Verified=v)
            for i, v in enumerate(
                ["Accepted", "Rejected - not accepted", "Unconfirmed", "Accepted"]
            )
        ]
        records, report = run(rows)
        for cell in build_candidate_payloads(records, report)["cells"]["cells"]:
            self.assertLessEqual(cell["verifiedCount"], cell["recordCount"])

    def test_a_rejected_verdict_is_not_counted_as_verified(self):
        rows = [row(RecordKey="a", Verified="Rejected - not accepted")]
        records, report = run(rows)
        self.assertEqual(records[0].verified, "rejected")
        self.assertEqual(
            build_candidate_payloads(records, report)["cells"]["cells"][0]["verifiedCount"], 0
        )

    def test_an_unconfirmed_verdict_is_not_counted_as_verified(self):
        records, report = run([row(RecordKey="a", Verified="not verified")])
        self.assertEqual(records[0].verified, "unconfirmed")
        self.assertEqual(
            build_candidate_payloads(records, report)["cells"]["cells"][0]["verifiedCount"], 0
        )

    def test_a_policy_vocabulary_overrides_the_heuristic(self):
        policy = PublicationPolicy(
            version="t",
            development_only=True,
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="not-used",
            row_level_records_mode="aggregates-only",
            verification_publication_mode="publish",
            ordinary_resolution_metres=100,
            accepted_verification_values=frozenset({"brerc verified"}),
            public_id_salt="x" * 32,
        )
        records, _ = run(
            [
                row(RecordKey="a", Verified="BRERC verified"),
                row(RecordKey="b", Verified="Accepted"),
            ],
            policy=policy,
        )
        self.assertEqual(records[0].verified, "accepted")
        # Outside BRERC's stated vocabulary, so it cannot be read as accepted.
        self.assertEqual(records[1].verified, "unknown")

    def test_year_range_and_series_agree_with_the_records(self):
        rows = [row(RecordKey="a", RecordDate="1999"), row(RecordKey="b", RecordDate="2024")]
        records, report = run(rows)
        payloads = build_candidate_payloads(records, report)
        self.assertEqual(payloads["meta"]["yearRange"], {"min": 1999, "max": 2024})
        self.assertEqual(sum(p["count"] for p in payloads["meta"]["recordsByYear"]), len(records))


class TestCsvAdapter(unittest.TestCase):
    def test_reads_a_csv_into_the_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            path.write_text(
                "RecordKey,SPECIES_No,TaxonName,CommonName,GridRef,RecordDate,"
                "LocationName,Abundance,RecordType,Verified,Source,Licence,Recorder1\n"
                "1,999999,Anguis fragilis,Slow-worm,ST585725,2000,Brandon Hill,3,"
                "field record,Accepted,recorder,CC-BY,A Person\n",
                encoding="utf-8",
            )
            records, report = run(read_csv(path))
            self.assertEqual(len(records), 1)
            preview = build_candidate_payloads(records, report)
            inspected = {key: preview[key] for key in ("cells", "records", "meta")}
            self.assertEqual(assert_no_forbidden_fields(inspected), [])


class TestRealBrercDateFormats(unittest.TestCase):
    """Date shapes taken from the client's own sample exports.

    An earlier `_to_year` took the first four characters, which parsed 0 of 998
    rows in the varied sample and 6 of 918 in the reptile sample.
    """

    def test_uk_day_first_dates(self):
        from etl.pipeline import _to_year

        for raw, expected in (
            ("23/03/2023", 2023),
            ("27/03/2023", 2023),
            ("04/09/2020", 2020),
            ("02/06/2016", 2016),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_to_year(raw), expected)

    def test_vague_date_ranges_take_the_end_year(self):
        from etl.pipeline import _to_year

        # Matches the semantics of the source's own YearEnd column.
        self.assertEqual(_to_year("04/08/2023 - 17/10/2023"), 2023)
        self.assertEqual(_to_year("31/07/2019 - 16/09/2019"), 2019)
        self.assertEqual(_to_year("01/12/1999 - 05/01/2001"), 2001)

    def test_bare_years(self):
        from etl.pipeline import _to_year

        for raw in ("2017", "2021", "2020"):
            self.assertEqual(_to_year(raw), int(raw))

    def test_integer_and_float_year_columns(self):
        from etl.pipeline import _to_year

        self.assertEqual(_to_year(2023), 2023)  # YearEnd is int64
        self.assertEqual(_to_year(2023.0), 2023)  # after a NaN-bearing read
        self.assertEqual(_to_year("2023.0"), 2023)  # CSV text after a NaN-bearing read
        self.assertIsNone(_to_year(2023.1))  # never silently truncate malformed data
        self.assertIsNone(_to_year("2023.1"))

    def test_datetime_values(self):
        import datetime

        from etl.pipeline import _to_year

        self.assertEqual(_to_year(datetime.date(2011, 6, 14)), 2011)
        self.assertEqual(_to_year(datetime.datetime(2011, 6, 14)), 2011)

    def test_implausible_and_unusable_values_are_rejected(self):
        from etl.pipeline import _to_year

        for raw in ("", "   ", "junk", "0042", "9999", None, True, float("nan")):
            with self.subTest(raw=raw):
                self.assertIsNone(_to_year(raw))

    def test_day_and_month_are_never_mistaken_for_a_year(self):
        from etl.pipeline import _to_year

        # 1-2 digit components cannot match the 4-digit year pattern.
        self.assertEqual(_to_year("01/02/1999"), 1999)
        self.assertEqual(_to_year("31/12/2024"), 2024)

    def test_a_full_export_row_shape_parses(self):
        columns = ColumnMap(
            record_id="unique_No",
            species_id="SPECIES_NO",
            scientific_name="Scientific_Name",
            grid_ref="Grid_Ref",
            year="YearEnd",
            common_name="Common_Name",
            place="Place",
            abundance="Abundance",
            record_type="Record_Type",
            verified="verified",
            source="Source",
            licence="licence",
        )
        rows = [
            {
                "unique_No": 5610349,
                "SPECIES_NO": ORDINARY_ID,
                "Scientific_Name": "Anguis fragilis",
                "Common_Name": "Slow-worm",
                "Grid_Ref": "ST5877972166",
                "YearEnd": 2023,
                "Place": "Brandon Hill",
                "Abundance": "3",
                "Record_Type": "field record",
                "verified": "Accepted - correct",
                "Source": "recorder",
                "licence": "",
            }
        ]
        records, report = run(rows, columns)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].year, 2023)
        self.assertEqual(records[0].verified, "accepted")
        self.assertTrue(report.reconciles())


if __name__ == "__main__":
    unittest.main(verbosity=1)
