"""Tests for the reviewed ``dashboard.main_data_dash`` source contract."""

import dataclasses
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from etl.identifiers import DuplicateSourceIdentifier
from etl.pipeline import (
    ColumnMap,
    build_candidate_payloads,
    build_payloads,
    run_pipeline,
    run_pipeline_for_source as _run_pipeline_for_source,
)
from etl.policy import DEVELOPMENT_POLICY, InvalidPolicy, PolicyNotApproved, PublicationPolicy
from etl.sensitivity import SENSITIVE_SNAPSHOT_SHA256, SENSITIVE_SNAPSHOT_VERSION
from etl.species import SpeciesDictionary, SpeciesRecord
from etl.source_contract import (
    BRERC_MAIN_DATA_DASH,
    BRERC_MAIN_DATA_DASH_COLUMNS,
    PENDING_DATE_MDB_MODIFIED,
    PIPELINE_MAPPING_TARGETS,
    IncrementalLoadBlocked,
    InvalidLoadMode,
    LoadMode,
    SourceColumn,
    SourceContract,
    SourceContractError,
    SourceMetadata,
    parse_load_mode,
)
from etl.view_identity import (
    VIEW_CAPTURE_EVIDENCE_PROFILE,
    VIEW_DEFINITION_DIGEST_PROFILE,
    VIEW_IDENTITY_PROFILE,
    ObservedViewDefinition,
    ViewDefinitionApproval,
)


def metadata_from_contract(contract: SourceContract = BRERC_MAIN_DATA_DASH) -> SourceMetadata:
    """Build synthetic metadata without shipping an attestation factory."""
    return SourceMetadata(
        schema=contract.schema,
        name=contract.name,
        object_type=contract.object_type,
        columns=tuple(
            SourceColumn(
                spec.name,
                spec.data_type,
                spec.character_maximum_length,
                spec.numeric_precision,
                spec.numeric_scale,
            )
            for spec in contract.columns
        ),
        observed_view=(SYNTHETIC_OBSERVED_VIEW if contract.view_approval is not None else None),
        observed_catalog_columns_sha256=(
            contract.view_approval.catalog_columns_sha256
            if contract.view_approval is not None
            else None
        ),
    )


VIEW_COLUMNS = ColumnMap(
    record_id="unique_no",
    species_id="species_no",
    scientific_name="scientific_name",
    grid_ref="grid_ref",
    year="year_end",
    common_name="common_name",
    abundance="abundance",
    record_type="record_type",
    licence="licence",
    sensitivity="sensitive",
)

VIEW_DICTIONARY = SpeciesDictionary(
    [SpeciesRecord("999999", "Anguis fragilis", "Slow-worm", False)]
)

VIEW_POLICY = PublicationPolicy(
    version="view-test",
    precision_mode="approved",
    suppression_mode="none",
    licensing_mode="not-applicable",
    record_type_safety_mode="not-used",
    row_level_records_mode="publish",
    verification_publication_mode="unavailable",
    sensitive_snapshot_version=SENSITIVE_SNAPSHOT_VERSION,
    sensitive_snapshot_sha256=SENSITIVE_SNAPSHOT_SHA256,
    ordinary_resolution_metres=100,
    default_sensitive_metres=10000,
    row_sensitive_resolution_metres=1000,
    non_sensitive_values=frozenset({"no"}),
    species_dictionary_sha256=VIEW_DICTIONARY.digest(),
    publish_individual_records=True,
    public_id_salt="test" * 8,
).with_approval(
    approved_by="Synthetic test approver",
    approver_role="Test data owner",
    approver_organisation="BRERC",
    evidence_reference="BRERC-TEST-VIEW-001",
    approved_on=date.today().isoformat(),
    review_due=(date.today() + timedelta(days=365)).isoformat(),
)


def run_pipeline_for_source(*args, dictionary=VIEW_DICTIONARY, **kwargs):
    """Exercise the source boundary with the exact policy-bound test dictionary."""
    return _run_pipeline_for_source(*args, dictionary=dictionary, **kwargs)


VIEW_PROJECTION = (*VIEW_COLUMNS.required(), *VIEW_COLUMNS.optional())

# A synthetic reviewed source identity used only to exercise the positive
# release path. The real BRERC contract intentionally has no such approval yet
# and therefore cannot cross the release boundary.
SYNTHETIC_OBSERVED_VIEW = ObservedViewDefinition(
    schema="dashboard",
    name="main_data_dash",
    relkind="v",
    definition="SELECT synthetic_reviewed_view",
    postgres_server_version_num=160004,
    owner="postgres",
    reloptions=(),
)
SYNTHETIC_VIEW_APPROVAL = ViewDefinitionApproval(
    source_version="synthetic-view-v1",
    source_environment="synthetic test database",
    client_reference_document_sha256=(BRERC_MAIN_DATA_DASH.client_reference_document_sha256),
    schema="dashboard",
    name="main_data_dash",
    relkind="v",
    postgres_server_version_num=SYNTHETIC_OBSERVED_VIEW.postgres_server_version_num,
    owner=SYNTHETIC_OBSERVED_VIEW.owner,
    reloptions=SYNTHETIC_OBSERVED_VIEW.reloptions,
    columns_sha256=BRERC_MAIN_DATA_DASH.columns_sha256(),
    catalog_columns_sha256=BRERC_MAIN_DATA_DASH.columns_sha256(),
    definition_sha256=SYNTHETIC_OBSERVED_VIEW.definition_sha256,
    capture_evidence_sha256="b" * 64,
    approved_by="Synthetic test data owner",
    approver_role="Test data owner",
    approver_organisation="BRERC",
    captured_at_utc="2026-08-10T00:00:00Z",
    approved_on=date.today().isoformat(),
    evidence_reference="TEST-EVIDENCE-ONLY",
)
RELEASE_READY_CONTRACT = dataclasses.replace(
    BRERC_MAIN_DATA_DASH,
    version="synthetic-reviewed-view-test",
    required_source_environment="synthetic test database",
    view_approval=SYNTHETIC_VIEW_APPROVAL,
    release_blockers=(),
)

# Independent literal transcription of the supplied PDF. Do not derive this
# from source_contract.py: its purpose is to turn any accidental manifest edit
# into a red test.
EXPECTED_PDF_SCHEMA = (
    ("scientific_name", "character varying", 120, None, None),
    ("common_name", "character varying", 120, None, None),
    ("grid_ref", "character varying", 25, None, None),
    ("place", "character varying", 254, None, None),
    ("date_of_record", "character varying", 50, None, None),
    ("abundance", "character varying", 35, None, None),
    ("sex_stage", "character varying", 45, None, None),
    ("record_type", "character varying", 55, None, None),
    ("start_date", "date", None, None, None),
    ("species_no", "character varying", 20, None, None),
    ("precise_date", "date", None, None, None),
    ("vague_date", "character varying", 35, None, None),
    ("vitality", "character varying", 15, None, None),
    ("digital_or_paper", "character varying", 10, None, None),
    ("date_entered", "date", None, None, None),
    ("bnes", "character varying", 4, None, None),
    ("bcc", "character varying", 3, None, None),
    ("sglos", "character varying", 4, None, None),
    ("nsom", "character varying", 4, None, None),
    ("year_end", "character varying", 5, None, None),
    ("year_start", "character varying", 5, None, None),
    ("end_date", "date", None, None, None),
    ("comments", "character varying", 254, None, None),
    ("source", "character varying", 50, None, None),
    ("bliss", "character varying", 100, None, None),
    ("taxa_brerc", "character varying", 60, None, None),
    ("unique_no", "numeric", None, 13, 2),
    ("licence", "character varying", 1, None, None),
    ("sensitive", "character varying", 4, None, None),
    ("taxo_id", "character varying", 20, None, None),
    ("easting", "numeric", None, 13, 2),
    ("northing", "numeric", None, 13, 2),
    ("taxa_nb", "text", None, None, None),
    ("brerc_status", "text", None, None, None),
    ("national_status", "text", None, None, None),
    ("legal_protection", "text", None, None, None),
    ("bap", "text", None, None, None),
    ("rspb", "text", None, None, None),
    ("brerc_notable", "text", None, None, None),
)


def view_row(**changes):
    row = {
        "unique_no": "1.00",
        "species_no": "999999",
        "scientific_name": "Anguis fragilis",
        "grid_ref": "ST587721",
        "year_end": "2024",
        "common_name": "Slow-worm",
        "abundance": "1",
        "record_type": "field record",
        "licence": "y",
        "sensitive": "No",
    }
    row.update(changes)
    return row


def replace_column(metadata: SourceMetadata, target_name: str, **changes) -> SourceMetadata:
    columns = tuple(
        dataclasses.replace(column, **changes) if column.name == target_name else column
        for column in metadata.columns
    )
    return dataclasses.replace(metadata, columns=columns)


class TestConfirmedManifest(unittest.TestCase):
    def test_the_pdf_manifest_contains_exactly_39_unique_columns(self):
        names = [column.name for column in BRERC_MAIN_DATA_DASH_COLUMNS]
        self.assertEqual(len(names), 39)
        self.assertEqual(len(set(names)), 39)

    def test_the_complete_manifest_is_pinned_independently_from_the_implementation(self):
        actual = tuple(
            (
                column.name,
                column.data_type,
                column.character_maximum_length,
                column.numeric_precision,
                column.numeric_scale,
            )
            for column in BRERC_MAIN_DATA_DASH_COLUMNS
        )
        self.assertEqual(actual, EXPECTED_PDF_SCHEMA)

    def test_load_bearing_view_fields_have_the_exact_supplied_types(self):
        by_name = {column.name: column for column in BRERC_MAIN_DATA_DASH_COLUMNS}
        self.assertEqual(by_name["sensitive"].character_maximum_length, 4)
        self.assertEqual(by_name["grid_ref"].character_maximum_length, 25)
        for name in ("unique_no", "easting", "northing"):
            self.assertEqual(by_name[name].data_type, "numeric")
            self.assertEqual(by_name[name].numeric_precision, 13)
            self.assertEqual(by_name[name].numeric_scale, 2)

    def test_the_incremental_marker_is_not_falsely_counted_as_pdf_confirmed(self):
        names = {column.name for column in BRERC_MAIN_DATA_DASH_COLUMNS}
        self.assertNotIn("date_mdb_modified", names)
        self.assertEqual(PENDING_DATE_MDB_MODIFIED.name, "date_mdb_modified")

    def test_the_received_client_document_checksum_is_pinned_as_provenance_only(self):
        self.assertEqual(
            BRERC_MAIN_DATA_DASH.client_reference_document_sha256,
            "567f614773df83609c3dd1a63f6b5d44fd98406d67ef60f2e5eb66f1fcebb72d",
        )
        self.assertIsNone(BRERC_MAIN_DATA_DASH.view_approval)

    def test_repository_reference_manifest_is_explicitly_not_live_approval(self):
        path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "brerc-main-data-dash-view-reference.json"
        )
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            document["receivedDocument"]["sha256"],
            BRERC_MAIN_DATA_DASH.client_reference_document_sha256,
        )
        self.assertEqual(
            document["liveCapture"]["definitionDigestProfile"],
            VIEW_DEFINITION_DIGEST_PROFILE,
        )
        self.assertEqual(
            document["liveCapture"]["identityProfile"],
            VIEW_IDENTITY_PROFILE,
        )
        self.assertEqual(
            document["liveCapture"]["captureEvidenceProfile"],
            VIEW_CAPTURE_EVIDENCE_PROFILE,
        )
        self.assertIsNone(document["approvedLiveViewIdentity"])

    def test_core_port_keeps_connector_and_endpoint_authority_blocked(self):
        rendered = "\n".join(BRERC_MAIN_DATA_DASH.release_blockers)
        self.assertIn("connector is not present", rendered)
        self.assertIn("atomic loader are not present", rendered)
        self.assertIn("species dictionary", rendered)
        self.assertIn("database/service identity", rendered)
        self.assertIn("deployment assertions only", rendered)


class TestInitialSchemaPreflight(unittest.TestCase):
    def test_the_exact_39_column_view_passes_with_honest_readiness_warnings(self):
        report = BRERC_MAIN_DATA_DASH.validate_initial(metadata_from_contract())
        self.assertEqual(report.confirmed_columns, 39)
        self.assertFalse(report.incremental_supported)
        self.assertFalse(report.release_supported)
        self.assertEqual(len(report.warnings), 2)
        self.assertTrue(any("date_mdb_modified" in warning for warning in report.warnings))
        self.assertTrue(any("view SQL" in warning for warning in report.warnings))

    def test_a_reviewed_view_identity_is_checked_and_marks_the_contract_release_ready(self):
        report = RELEASE_READY_CONTRACT.validate_initial(
            metadata_from_contract(RELEASE_READY_CONTRACT)
        )
        self.assertTrue(report.release_supported)
        self.assertEqual(len(report.warnings), 1)  # incremental loading remains blocked

        mismatched = dataclasses.replace(
            metadata_from_contract(RELEASE_READY_CONTRACT),
            observed_view=dataclasses.replace(
                SYNTHETIC_OBSERVED_VIEW,
                definition=SYNTHETIC_OBSERVED_VIEW.definition + " ",
            ),
        )
        with self.assertRaises(SourceContractError):
            RELEASE_READY_CONTRACT.validate_initial(mismatched)

    def test_the_promised_date_column_requires_a_new_versioned_contract(self):
        current = metadata_from_contract()
        changed = dataclasses.replace(
            current,
            columns=(
                *current.columns,
                SourceColumn(
                    PENDING_DATE_MDB_MODIFIED.name,
                    PENDING_DATE_MDB_MODIFIED.data_type,
                ),
            ),
        )
        with self.assertRaises(SourceContractError):
            BRERC_MAIN_DATA_DASH.validate_initial(changed)

    def test_missing_renamed_extra_and_wrongly_typed_columns_all_fail(self):
        good = metadata_from_contract()
        cases = {
            "missing": dataclasses.replace(
                good,
                columns=tuple(c for c in good.columns if c.name != "sensitive"),
            ),
            "renamed": dataclasses.replace(
                good,
                columns=tuple(
                    dataclasses.replace(c, name="sensitivity") if c.name == "sensitive" else c
                    for c in good.columns
                ),
            ),
            "extra": dataclasses.replace(
                good,
                columns=(*good.columns, SourceColumn("unexpected", "text")),
            ),
            "wrong type": replace_column(good, "sensitive", data_type="text"),
            "wrong length": replace_column(good, "sensitive", character_maximum_length=5),
            "wrong scale": replace_column(good, "unique_no", numeric_scale=0),
        }
        for name, metadata in cases.items():
            with self.subTest(name=name), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_initial(metadata)

    def test_removing_or_case_changing_each_confirmed_column_fails(self):
        good = metadata_from_contract()
        for target in good.columns:
            with self.subTest(missing=target.name), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_initial(
                    dataclasses.replace(
                        good,
                        columns=tuple(c for c in good.columns if c.name != target.name),
                    )
                )
            with self.subTest(case_changed=target.name), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_initial(
                    replace_column(good, target.name, name=target.name.upper())
                )

    def test_mutating_every_type_and_size_constraint_fails(self):
        good = metadata_from_contract()
        for target in good.columns:
            with self.subTest(type=target.name), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_initial(
                    replace_column(good, target.name, data_type="boolean")
                )
            if target.character_maximum_length is not None:
                with self.subTest(length=target.name), self.assertRaises(SourceContractError):
                    BRERC_MAIN_DATA_DASH.validate_initial(
                        replace_column(
                            good,
                            target.name,
                            character_maximum_length=target.character_maximum_length + 1,
                        )
                    )
            if target.numeric_precision is not None:
                with self.subTest(precision=target.name), self.assertRaises(SourceContractError):
                    BRERC_MAIN_DATA_DASH.validate_initial(
                        replace_column(
                            good,
                            target.name,
                            numeric_precision=target.numeric_precision + 1,
                        )
                    )
            if target.numeric_scale is not None:
                with self.subTest(scale=target.name), self.assertRaises(SourceContractError):
                    BRERC_MAIN_DATA_DASH.validate_initial(
                        replace_column(
                            good,
                            target.name,
                            numeric_scale=target.numeric_scale + 1,
                        )
                    )

    def test_duplicate_metadata_and_wrong_object_identity_fail(self):
        good = metadata_from_contract()
        reordered = (good.columns[1], good.columns[0], *good.columns[2:])
        cases = (
            dataclasses.replace(good, columns=(*good.columns, good.columns[0])),
            dataclasses.replace(good, columns=reordered),
            dataclasses.replace(good, schema="public"),
            dataclasses.replace(good, name="other_view"),
            dataclasses.replace(good, object_type="table"),
        )
        for metadata in cases:
            with self.subTest(metadata=metadata), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_initial(metadata)

    def test_an_empty_header_is_still_checked(self):
        empty = SourceMetadata("dashboard", "main_data_dash", "view", ())
        with self.assertRaises(SourceContractError):
            BRERC_MAIN_DATA_DASH.validate_initial(empty)

    def test_information_schema_rows_are_converted_without_record_content(self):
        column = SourceColumn.from_information_schema(
            {
                "column_name": "unique_no",
                "data_type": "numeric",
                "character_maximum_length": None,
                "numeric_precision": 13,
                "numeric_scale": 2,
            }
        )
        self.assertEqual(column, SourceColumn("unique_no", "numeric", None, 13, 2))

    def test_approval_cannot_choose_its_own_environment_or_organisation(self):
        cases = (
            dataclasses.replace(
                SYNTHETIC_VIEW_APPROVAL,
                source_environment="local development",
            ),
            dataclasses.replace(
                SYNTHETIC_VIEW_APPROVAL,
                approver_organisation="Not BRERC",
            ),
        )
        for approval in cases:
            with self.subTest(approval=approval), self.assertRaises(SourceContractError):
                dataclasses.replace(
                    BRERC_MAIN_DATA_DASH,
                    required_source_environment="synthetic test database",
                    view_approval=approval,
                )

    def test_view_approval_requires_an_independently_pinned_environment(self):
        with self.assertRaises(SourceContractError):
            dataclasses.replace(
                BRERC_MAIN_DATA_DASH,
                view_approval=SYNTHETIC_VIEW_APPROVAL,
            )


class TestResultHeaderPreflight(unittest.TestCase):
    def test_an_exact_header_passes_even_when_there_are_zero_rows(self):
        BRERC_MAIN_DATA_DASH.validate_result_header(VIEW_PROJECTION, VIEW_PROJECTION)

    def test_missing_extra_reordered_and_case_changed_headers_fail(self):
        cases = (
            VIEW_PROJECTION[:-1],
            (*VIEW_PROJECTION, "comments"),
            (VIEW_PROJECTION[1], VIEW_PROJECTION[0], *VIEW_PROJECTION[2:]),
            tuple("Sensitive" if c == "sensitive" else c for c in VIEW_PROJECTION),
        )
        for header in cases:
            with self.subTest(header=header), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_result_header(header, VIEW_PROJECTION)

    def test_empty_duplicate_and_out_of_contract_projections_fail(self):
        cases = (
            (),
            (*VIEW_PROJECTION, VIEW_PROJECTION[0]),
            (*VIEW_PROJECTION, "date_mdb_modified"),
        )
        for projection in cases:
            with self.subTest(projection=projection), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_result_header(projection, projection)


class TestSafetyMappingPreflight(unittest.TestCase):
    def test_the_exact_view_mapping_and_policy_pass(self):
        BRERC_MAIN_DATA_DASH.validate_safety_mapping(VIEW_COLUMNS, VIEW_POLICY)

    def test_a_contract_must_define_every_and_only_column_map_target(self):
        without_common_name = tuple(
            item for item in BRERC_MAIN_DATA_DASH.pipeline_mapping if item[0] != "common_name"
        )
        with_unknown_target = (
            *BRERC_MAIN_DATA_DASH.pipeline_mapping,
            ("unreviewed_target", "comments"),
        )
        for mapping in (without_common_name, with_unknown_target):
            with self.subTest(mapping=mapping), self.assertRaises(SourceContractError):
                dataclasses.replace(BRERC_MAIN_DATA_DASH, pipeline_mapping=mapping)

    def test_the_required_mapping_targets_track_the_column_map_dataclass(self):
        self.assertEqual(
            PIPELINE_MAPPING_TARGETS,
            {field.name for field in dataclasses.fields(ColumnMap)},
        )

    def test_wrong_missing_or_case_changed_sensitivity_mapping_fails(self):
        for mapped in (None, "Sensitivity", "sensitivity"):
            with self.subTest(mapped=mapped), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_safety_mapping(
                    dataclasses.replace(VIEW_COLUMNS, sensitivity=mapped),
                    VIEW_POLICY,
                )

    def test_the_source_identity_mapping_must_be_exact(self):
        wrong = dataclasses.replace(VIEW_COLUMNS, record_id="date_entered")
        with self.assertRaises(SourceContractError):
            BRERC_MAIN_DATA_DASH.validate_safety_mapping(wrong, VIEW_POLICY)

    def test_every_output_bearing_mapping_is_pinned_against_semantic_smuggling(self):
        for attribute, expected in BRERC_MAIN_DATA_DASH.pipeline_mapping:
            malicious = "easting" if expected != "easting" else "northing"
            with self.subTest(attribute=attribute), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_safety_mapping(
                    dataclasses.replace(VIEW_COLUMNS, **{attribute: malicious}),
                    VIEW_POLICY,
                )

    def test_comments_cannot_be_relabelled_as_a_public_species_name(self):
        malicious = dataclasses.replace(VIEW_COLUMNS, scientific_name="comments")
        with self.assertRaises(SourceContractError):
            BRERC_MAIN_DATA_DASH.validate_safety_mapping(malicious, VIEW_POLICY)

    def test_row_resolution_and_non_sensitive_vocabulary_cannot_drift(self):
        policies = (
            dataclasses.replace(VIEW_POLICY, row_sensitive_resolution_metres=None),
            dataclasses.replace(VIEW_POLICY, row_sensitive_resolution_metres=10000),
            dataclasses.replace(VIEW_POLICY, non_sensitive_values=frozenset({"no", "n"})),
            dataclasses.replace(VIEW_POLICY, non_sensitive_values=frozenset()),
        )
        for policy in policies:
            with self.subTest(policy=policy), self.assertRaises(SourceContractError):
                BRERC_MAIN_DATA_DASH.validate_safety_mapping(VIEW_COLUMNS, policy)

    def test_live_wrapper_checks_metadata_even_for_zero_rows(self):
        wrong_header = dataclasses.replace(
            metadata_from_contract(),
            columns=tuple(
                column for column in metadata_from_contract().columns if column.name != "sensitive"
            ),
        )
        with self.assertRaises(SourceContractError):
            run_pipeline_for_source(
                [],
                VIEW_COLUMNS,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=wrong_header,
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=VIEW_POLICY,
            )

    def test_live_wrapper_refuses_an_export_mapping_before_reading_rows(self):
        wrong = dataclasses.replace(VIEW_COLUMNS, sensitivity=None)
        with self.assertRaises(SourceContractError):
            run_pipeline_for_source(
                [],
                wrong,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=metadata_from_contract(),
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=VIEW_POLICY,
            )

    def test_live_wrapper_requires_a_genuinely_approved_publication_policy(self):
        def must_not_iterate():
            raise AssertionError("unapproved source run touched source rows")
            yield {}

        with self.assertRaises(PolicyNotApproved):
            run_pipeline_for_source(
                must_not_iterate(),
                VIEW_COLUMNS,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=metadata_from_contract(),
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=DEVELOPMENT_POLICY,
            )

    def test_view_identity_mismatch_fails_before_source_rows_are_read(self):
        def must_not_iterate():
            raise AssertionError("view mismatch touched source rows")
            yield {}

        changed_observation = dataclasses.replace(
            SYNTHETIC_OBSERVED_VIEW,
            definition=SYNTHETIC_OBSERVED_VIEW.definition + " ",
        )
        with self.assertRaises(SourceContractError):
            run_pipeline_for_source(
                must_not_iterate(),
                VIEW_COLUMNS,
                source_contract=RELEASE_READY_CONTRACT,
                source_metadata=dataclasses.replace(
                    metadata_from_contract(RELEASE_READY_CONTRACT),
                    observed_view=changed_observation,
                ),
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=VIEW_POLICY,
            )

    def test_catalogue_column_mismatch_fails_before_source_rows_are_read(self):
        def must_not_iterate():
            raise AssertionError("catalogue mismatch touched source rows")
            yield {}

        metadata = dataclasses.replace(
            metadata_from_contract(RELEASE_READY_CONTRACT),
            observed_catalog_columns_sha256="f" * 64,
        )
        with self.assertRaises(SourceContractError):
            run_pipeline_for_source(
                must_not_iterate(),
                VIEW_COLUMNS,
                source_contract=RELEASE_READY_CONTRACT,
                source_metadata=metadata,
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=VIEW_POLICY,
            )

    def test_invalid_approved_policy_fails_before_reading_a_row(self):
        def must_not_iterate():
            raise AssertionError("invalid source policy touched source rows")
            yield {}

        # with_approval() itself refuses invalid rules. Mutating a previously
        # valid approved dataclass models accidental post-approval reuse and
        # proves the production wrapper still validates before touching rows.
        invalid = dataclasses.replace(VIEW_POLICY, ordinary_resolution_metres=2000)
        with self.assertRaises(InvalidPolicy):
            run_pipeline_for_source(
                must_not_iterate(),
                VIEW_COLUMNS,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=metadata_from_contract(),
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=invalid,
            )

    def test_live_wrapper_checks_the_cursor_header_for_an_empty_batch(self):
        with self.assertRaises(SourceContractError):
            run_pipeline_for_source(
                [],
                VIEW_COLUMNS,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=metadata_from_contract(),
                source_result_columns=VIEW_PROJECTION[:-1],
                load_mode=LoadMode.INITIAL,
                policy=VIEW_POLICY,
            )

    def test_live_wrapper_rejects_rows_that_do_not_match_the_validated_header(self):
        missing_control = view_row()
        del missing_control["sensitive"]
        cases = (
            view_row(easting=358700),
            missing_control,
        )
        for source_row in cases:
            with self.subTest(keys=tuple(source_row)), self.assertRaises(SourceContractError):
                run_pipeline_for_source(
                    [source_row],
                    VIEW_COLUMNS,
                    source_contract=BRERC_MAIN_DATA_DASH,
                    source_metadata=metadata_from_contract(),
                    source_result_columns=VIEW_PROJECTION,
                    load_mode=LoadMode.INITIAL,
                    policy=VIEW_POLICY,
                )

    def test_equivalent_database_keys_produce_the_same_public_hmac(self):
        ids = []
        for source_id in ("1", "1.0", "1.00"):
            records, _ = run_pipeline_for_source(
                [view_row(unique_no=source_id)],
                VIEW_COLUMNS,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=metadata_from_contract(),
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=VIEW_POLICY,
            )
            ids.append(records[0].record_id)
        self.assertEqual(len(set(ids)), 1)

    def test_a_one_shot_cursor_header_iterator_is_not_consumed_twice(self):
        records, _ = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=BRERC_MAIN_DATA_DASH,
            source_metadata=metadata_from_contract(),
            source_result_columns=(column for column in VIEW_PROJECTION),
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        self.assertEqual(len(records), 1)

    def test_the_current_column_only_contract_cannot_cross_the_release_boundary(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=BRERC_MAIN_DATA_DASH,
            source_metadata=metadata_from_contract(),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        records, report = validated
        with self.assertRaises(SourceContractError) as ctx:
            build_payloads(
                validated,
                policy=VIEW_POLICY,
                source_contract=BRERC_MAIN_DATA_DASH,
            )
        self.assertIn("BLOCKED_SOURCE_RELEASE", str(ctx.exception))

    def test_live_view_never_claims_zero_verified_when_verification_is_unavailable(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=BRERC_MAIN_DATA_DASH,
            source_metadata=metadata_from_contract(),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        records, report = validated
        payloads = build_candidate_payloads(records, report)
        self.assertFalse(report.verification_available)
        self.assertFalse(payloads["meta"]["verificationAvailable"])
        self.assertFalse(payloads["cells"]["verificationAvailable"])
        self.assertNotIn("verifiedCount", payloads["cells"]["cells"][0])
        self.assertNotIn("verifiedCount", payloads["meta"]["recordsByYear"][0])
        self.assertNotIn("verified", payloads["records"]["items"][0])
        self.assertEqual(
            payloads["records"]["publication"],
            {
                "mode": "individual-records",
                "fields": {
                    "abundance": False,
                    "place": False,
                    "recordType": False,
                    "verification": False,
                },
            },
        )

    def test_a_reviewed_source_candidate_can_cross_the_release_boundary(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        payloads = build_payloads(
            validated,
            policy=VIEW_POLICY,
            source_contract=RELEASE_READY_CONTRACT,
        )
        self.assertEqual(payloads["records"]["total"], 1)

    def test_observed_view_digests_are_bound_into_the_immutable_audit_report(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        _, report = validated
        self.assertEqual(
            report.observed_view_definition_digest,
            SYNTHETIC_OBSERVED_VIEW.definition_sha256,
        )
        self.assertEqual(
            report.observed_view_identity_digest,
            SYNTHETIC_VIEW_APPROVAL.identity_sha256,
        )

    def test_a_different_view_approval_cannot_release_an_existing_validated_run(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        changed_approval = dataclasses.replace(
            SYNTHETIC_VIEW_APPROVAL,
            source_version="synthetic-view-v2",
        )
        changed_contract = dataclasses.replace(
            RELEASE_READY_CONTRACT,
            view_approval=changed_approval,
        )
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                validated,
                policy=VIEW_POLICY,
                source_contract=changed_contract,
            )

    def test_an_approved_report_cannot_be_paired_with_other_records(self):
        first_records, first_report = run_pipeline_for_source(
            [view_row(unique_no="1.00", year_end="2020")],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        other_records, _ = run_pipeline_for_source(
            [view_row(unique_no="2.00", year_end="2024")],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        self.assertEqual(len(first_records), len(other_records))
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                other_records,
                first_report,
                policy=VIEW_POLICY,
                source_contract=RELEASE_READY_CONTRACT,
            )

    def test_release_rejects_a_different_source_contract(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        changed = dataclasses.replace(
            RELEASE_READY_CONTRACT,
            version="unreviewed-change",
        )
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                validated,
                policy=VIEW_POLICY,
                source_contract=changed,
            )

    def test_inspection_report_cannot_toggle_individual_rows_after_transformation(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        _, report = validated
        report.publish_individual_records = False
        payloads = build_payloads(
            validated,
            policy=VIEW_POLICY,
            source_contract=RELEASE_READY_CONTRACT,
        )
        self.assertEqual(payloads["records"]["total"], 1)

    def test_inspection_report_cannot_invent_verification_or_audit_counts(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        _, report = validated
        report.verification_available = True
        report.records_suppressed = 999
        report.withheld.clear()
        _, fresh_report = validated
        self.assertFalse(fresh_report.verification_available)
        self.assertNotEqual(fresh_report.records_suppressed, 999)
        build_payloads(
            validated,
            policy=VIEW_POLICY,
            source_contract=RELEASE_READY_CONTRACT,
        )

    def test_private_audit_snapshot_mutation_is_detected_at_release(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        validated._report.records_suppressed = 999  # type: ignore[attr-defined]
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                validated,
                policy=VIEW_POLICY,
                source_contract=RELEASE_READY_CONTRACT,
            )

    def test_private_row_verification_capability_mutation_is_detected_at_release(self):
        validated = run_pipeline_for_source(
            [view_row()],
            VIEW_COLUMNS,
            source_contract=RELEASE_READY_CONTRACT,
            source_metadata=metadata_from_contract(RELEASE_READY_CONTRACT),
            source_result_columns=VIEW_PROJECTION,
            load_mode=LoadMode.INITIAL,
            policy=VIEW_POLICY,
        )
        validated._report.publish_record_verification = True  # type: ignore[attr-defined]
        with self.assertRaises(PolicyNotApproved):
            build_payloads(
                validated,
                policy=VIEW_POLICY,
                source_contract=RELEASE_READY_CONTRACT,
            )

    def test_mutable_report_strings_cannot_forge_source_attestation(self):
        records, report = run_pipeline(
            [view_row()],
            VIEW_COLUMNS,
            policy=VIEW_POLICY,
            dictionary=VIEW_DICTIONARY,
        )
        report.source_contract_version = RELEASE_READY_CONTRACT.version
        report.source_contract_digest = RELEASE_READY_CONTRACT.digest()
        with self.assertRaises(PolicyNotApproved) as ctx:
            build_payloads(
                records,
                report,
                policy=VIEW_POLICY,
                source_contract=RELEASE_READY_CONTRACT,
            )
        self.assertIn("ValidatedSourceRun", str(ctx.exception))

    def test_equivalent_keys_in_one_batch_stop_the_candidate(self):
        with self.assertRaises(DuplicateSourceIdentifier):
            run_pipeline_for_source(
                [view_row(unique_no="1"), view_row(unique_no="1.00")],
                VIEW_COLUMNS,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=metadata_from_contract(),
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INITIAL,
                policy=VIEW_POLICY,
            )


class TestIncrementalModeRemainsBlocked(unittest.TestCase):
    def test_initial_is_the_only_supported_mode(self):
        BRERC_MAIN_DATA_DASH.require_mode(LoadMode.INITIAL)
        with self.assertRaises(IncrementalLoadBlocked) as ctx:
            BRERC_MAIN_DATA_DASH.require_mode(LoadMode.INCREMENTAL)
        self.assertEqual(ctx.exception.blockers, BRERC_MAIN_DATA_DASH.incremental_blockers)
        self.assertIn("date_mdb_modified", str(ctx.exception))
        self.assertIn("deletions", str(ctx.exception))
        self.assertIn("lookup-table", str(ctx.exception))
        self.assertIn("complete replacement candidate", str(ctx.exception))

    def test_the_live_wrapper_blocks_incremental_before_reading_a_row(self):
        def must_not_iterate():
            raise AssertionError("incremental mode touched source rows")
            yield {}

        with self.assertRaises(IncrementalLoadBlocked):
            run_pipeline_for_source(
                must_not_iterate(),
                VIEW_COLUMNS,
                source_contract=BRERC_MAIN_DATA_DASH,
                source_metadata=metadata_from_contract(),
                source_result_columns=VIEW_PROJECTION,
                load_mode=LoadMode.INCREMENTAL,
                policy=VIEW_POLICY,
            )

    def test_modes_are_explicit_commands_not_a_persistent_boolean_flag(self):
        self.assertIs(parse_load_mode("initial"), LoadMode.INITIAL)
        self.assertIs(parse_load_mode(" INCREMENTAL "), LoadMode.INCREMENTAL)
        for value in (None, True, False, "", "full", "true", "initial-load"):
            with self.subTest(value=value), self.assertRaises(InvalidLoadMode):
                parse_load_mode(value)

    def test_the_contract_rejects_raw_values_that_bypass_the_parser(self):
        for value in ("initial", "incremental", None, True, False, 1):
            with self.subTest(value=value), self.assertRaises(InvalidLoadMode):
                BRERC_MAIN_DATA_DASH.require_mode(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=1)
