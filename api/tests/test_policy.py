"""Tests for the publication policy.

The policy carries the decisions that are BRERC's rather than ours. These tests
exist so that a wrong policy fails loudly at configuration time, and so that the
guards against publishing under an unapproved or development policy cannot be
removed without a test going red.
"""

import unittest
from datetime import date, timedelta

from etl.gridref import PUBLIC_RESOLUTIONS_METRES
from etl.policy import (
    COARSEST_EMITTABLE_METRES,
    DEVELOPMENT_POLICY,
    EMITTABLE_RESOLUTIONS_METRES,
    FINEST_EMITTABLE_METRES,
    INDIVIDUAL_RECORD_BASE_FIELDS,
    INDIVIDUAL_RECORD_CONTROLLED_FIELDS,
    INDIVIDUAL_RECORD_SCHEMA_VERSION,
    SUPPRESSION_COHORT,
    SUPPRESSION_COUNT_BASIS,
    SUPPRESSION_SCOPE,
    SUPPRESSION_SURFACES,
    UNAPPROVED_POLICY,
    InvalidPolicy,
    PolicyNotApproved,
    PublicationPolicy,
)
from etl.sensitivity import SENSITIVE_SNAPSHOT_SHA256, SENSITIVE_SNAPSHOT_VERSION


def decision_ready_policy(**overrides) -> PublicationPolicy:
    """A synthetic, internally coherent policy with every BRERC choice made."""
    values = {
        "version": "v",
        "precision_mode": "approved",
        "suppression_mode": "none",
        "licensing_mode": "not-applicable",
        "record_type_safety_mode": "not-used",
        "row_level_records_mode": "aggregates-only",
        "verification_publication_mode": "unavailable",
        "sensitive_snapshot_version": SENSITIVE_SNAPSHOT_VERSION,
        "sensitive_snapshot_sha256": SENSITIVE_SNAPSHOT_SHA256,
        # ``not-used`` is only valid for approval when the source's row-level
        # sensitivity control is explicitly approved as incorporating type.
        "row_sensitive_resolution_metres": 1000,
        "non_sensitive_values": frozenset({"no"}),
        "ordinary_resolution_metres": 100,
        "public_id_salt": "x" * 32,
    }
    values.update(overrides)
    return PublicationPolicy(**values)


def approve(
    policy: PublicationPolicy,
    *,
    approved_by: str = "Synthetic BRERC owner",
    approver_role: str = "Data owner",
    approver_organisation: str = "BRERC",
    evidence_reference: str = "BRERC-TEST-001",
    approved_on: str | None = None,
    review_due: str | None = None,
) -> PublicationPolicy:
    today = date.today()
    return policy.with_approval(
        approved_by=approved_by,
        approver_role=approver_role,
        approver_organisation=approver_organisation,
        evidence_reference=evidence_reference,
        approved_on=today.isoformat() if approved_on is None else approved_on,
        review_due=(
            (today + timedelta(days=365)).isoformat() if review_due is None else review_due
        ),
    )


class TestOneSourceOfTruthForResolutions(unittest.TestCase):
    def test_the_policy_module_does_not_restate_the_resolution_set(self):
        # Restating it would let the two silently disagree, and the client would
        # be handed a square it cannot draw.
        self.assertIs(EMITTABLE_RESOLUTIONS_METRES, PUBLIC_RESOLUTIONS_METRES)

    def test_the_bounds_are_derived_not_typed_out(self):
        self.assertEqual(FINEST_EMITTABLE_METRES, min(PUBLIC_RESOLUTIONS_METRES))
        self.assertEqual(COARSEST_EMITTABLE_METRES, max(PUBLIC_RESOLUTIONS_METRES))

    def test_neither_tetrads_nor_hectads_are_emittable(self):
        self.assertNotIn(2000, EMITTABLE_RESOLUTIONS_METRES)
        self.assertNotIn(100000, EMITTABLE_RESOLUTIONS_METRES)


class TestApproval(unittest.TestCase):
    def test_the_default_policy_is_not_approved(self):
        self.assertFalse(UNAPPROVED_POLICY.is_approved())
        with self.assertRaises(PolicyNotApproved):
            UNAPPROVED_POLICY.assert_approved()

    def test_the_development_policy_can_never_report_itself_approved(self):
        # An earlier version set approved_by to a placeholder string, which made
        # is_approved() true and let assert_approved() pass. A development policy
        # that satisfies the production guard defeats the guard entirely.
        self.assertTrue(DEVELOPMENT_POLICY.development_only)
        self.assertFalse(DEVELOPMENT_POLICY.is_approved())
        with self.assertRaises(PolicyNotApproved):
            DEVELOPMENT_POLICY.assert_approved()

    def test_a_development_policy_cannot_be_approved_even_explicitly(self):
        with self.assertRaises(PolicyNotApproved):
            approve(DEVELOPMENT_POLICY)

    def test_setting_the_approval_fields_directly_still_fails(self):
        # dataclasses.replace bypasses with_approval; is_approved must still refuse.
        import dataclasses

        forged = dataclasses.replace(
            DEVELOPMENT_POLICY, approved_by="A Person", approved_on="2026-08-01"
        )
        self.assertFalse(forged.is_approved())

    def test_a_real_policy_can_be_approved(self):
        policy = decision_ready_policy(version="brerc-1.0")
        self.assertFalse(policy.is_approved())
        approved = approve(
            policy,
            approved_by="Tim Corner",
            approver_role="BRERC data owner",
            evidence_reference="BRERC-POLICY-2026-08",
        )
        self.assertTrue(approved.is_approved())
        approved.assert_approved()  # must not raise
        self.assertEqual(approved.approved_by, "Tim Corner")

    def test_approval_needs_both_a_name_and_a_date(self):
        import dataclasses

        base = PublicationPolicy(version="v")
        self.assertFalse(dataclasses.replace(base, approved_by="X").is_approved())
        self.assertFalse(dataclasses.replace(base, approved_on="2026-08-01").is_approved())

    def test_approval_requires_a_nonblank_trimmed_name_and_canonical_dates(self):
        today = date.today()
        due = (today + timedelta(days=30)).isoformat()
        base = decision_ready_policy()
        for approver in ("", "   ", " Name "):
            with self.subTest(approver=approver), self.assertRaises(PolicyNotApproved):
                approve(base, approved_by=approver, approved_on=today.isoformat(), review_due=due)
        for approved_on in ("not-a-date", "2026-2-03", "2026-02-30"):
            with self.subTest(approved_on=approved_on), self.assertRaises(PolicyNotApproved):
                approve(base, approved_on=approved_on, review_due=due)

    def test_approval_requires_brerc_authority_and_retained_evidence(self):
        base = decision_ready_policy()
        cases = (
            {"approver_role": ""},
            {"approver_role": " Data owner "},
            {"approver_organisation": "Consultancy"},
            {"approver_organisation": "brerc"},
            {"evidence_reference": ""},
            {"evidence_reference": " BRERC-1 "},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(PolicyNotApproved):
                approve(base, **values)

    def test_every_publication_decision_must_be_explicit_before_approval(self):
        import dataclasses

        base = decision_ready_policy()
        for field_name in (
            "precision_mode",
            "suppression_mode",
            "licensing_mode",
            "record_type_safety_mode",
            "row_level_records_mode",
            "verification_publication_mode",
        ):
            with self.subTest(field=field_name), self.assertRaises(PolicyNotApproved):
                approve(dataclasses.replace(base, **{field_name: "undecided"}))

    def test_future_approval_and_invalid_or_expired_review_are_refused(self):
        today = date.today()
        base = decision_ready_policy()
        cases = (
            ((today + timedelta(days=1)).isoformat(), (today + timedelta(days=30)).isoformat()),
            (today.isoformat(), (today - timedelta(days=1)).isoformat()),
            (today.isoformat(), "not-a-date"),
        )
        for approved_on, review_due in cases:
            with (
                self.subTest(approved_on=approved_on, review_due=review_due),
                self.assertRaises(PolicyNotApproved),
            ):
                approve(base, approved_on=approved_on, review_due=review_due)

    def test_the_review_due_date_is_inclusive_then_expires(self):
        today = date.today()
        policy = approve(
            decision_ready_policy(),
            approved_on=today.isoformat(),
            review_due=today.isoformat(),
        )
        self.assertTrue(policy.is_approved(as_of=today))
        self.assertFalse(policy.is_approved(as_of=today + timedelta(days=1)))
        with self.assertRaises(PolicyNotApproved):
            policy.assert_approved(as_of=today + timedelta(days=1))

    def test_changing_any_publication_decision_invalidates_the_approval(self):
        import dataclasses

        today = date.today()
        approved = PublicationPolicy(
            version="v1",
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="rules",
            row_level_records_mode="aggregates-only",
            verification_publication_mode="unavailable",
            sensitive_snapshot_version=SENSITIVE_SNAPSHOT_VERSION,
            sensitive_snapshot_sha256=SENSITIVE_SNAPSHOT_SHA256,
            ordinary_resolution_metres=100,
            map_cell_resolution_metres=1000,
            default_sensitive_metres=10000,
            row_sensitive_resolution_metres=1000,
            sensitive_resolution_metres={"2028": 10000},
            non_sensitive_values=frozenset({"no"}),
            sensitive_record_type_metres={"bat roost": 10000},
            record_type_vocabulary=frozenset({"field record", "bat roost"}),
            public_id_salt="a-strong-synthetic-secret-value-01",
        )
        approved = approve(
            approved,
            approved_on=today.isoformat(),
            review_due=(today + timedelta(days=365)).isoformat(),
        )
        mutations = {
            "version": "v2",
            "development_only": True,
            "precision_mode": "undecided",
            "suppression_mode": "minimum-count",
            "licensing_mode": "all-publication-allow-list",
            "record_type_safety_mode": "not-used",
            "row_level_records_mode": "publish",
            "verification_publication_mode": "publish",
            "sensitive_snapshot_version": "another-snapshot",
            "sensitive_snapshot_sha256": "0" * 64,
            "species_dictionary_sha256": "1" * 64,
            "ordinary_resolution_metres": 1000,
            "map_cell_resolution_metres": 10000,
            "sensitive_resolution_metres": {"2028": 1000},
            "default_sensitive_metres": 1000,
            "row_sensitive_resolution_metres": 10000,
            "unknown_species_action": "coarsest",
            "publish_place_names": True,
            "public_source_label": "Not approved",
            "publish_individual_records": True,
            "publish_abundance": True,
            "publish_record_type": True,
            "publish_record_verification": True,
            "publish_original_record_ids": True,
            "public_id_salt": "a-different-strong-secret-value-02",
            "min_records_per_cell": 2,
            "accepted_verification_values": frozenset({"accepted"}),
            "allowed_licence_values": frozenset({"public"}),
            "non_sensitive_values": frozenset({"n"}),
            "sensitive_record_type_metres": {"nest": 10000},
            "record_type_vocabulary": frozenset({"field record", "bat roost", "nest"}),
            "approver_role": "Another role",
            "approver_organisation": "Not BRERC",
            "evidence_reference": "BRERC-OTHER",
            "coarsen_unpublishable_resolutions": True,
        }
        self.assertTrue(approved.is_approved())
        for field_name, replacement in mutations.items():
            with self.subTest(field=field_name):
                changed = dataclasses.replace(approved, **{field_name: replacement})
                self.assertFalse(changed.is_approved())
                with self.assertRaises(PolicyNotApproved):
                    changed.assert_approved()

    def test_approval_document_binds_suppression_and_individual_row_semantics(self):
        description = approve(decision_ready_policy()).describe()
        self.assertEqual(description["suppressionScope"], SUPPRESSION_SCOPE)
        self.assertEqual(description["suppressionCountBasis"], SUPPRESSION_COUNT_BASIS)
        self.assertEqual(description["suppressionCohort"], list(SUPPRESSION_COHORT))
        self.assertEqual(description["suppressionSurfaces"], list(SUPPRESSION_SURFACES))
        self.assertEqual(
            description["individualRecordSchemaVersion"],
            INDIVIDUAL_RECORD_SCHEMA_VERSION,
        )
        self.assertEqual(
            description["individualRecordBaseFields"],
            list(INDIVIDUAL_RECORD_BASE_FIELDS),
        )
        self.assertEqual(
            description["individualRecordControlledFields"],
            dict(INDIVIDUAL_RECORD_CONTROLLED_FIELDS),
        )


class TestValidation(unittest.TestCase):
    def test_an_undrawable_ordinary_resolution_is_rejected(self):
        for metres in (2000, 100000, 50000, 0, 42):
            with self.subTest(metres=metres), self.assertRaises(InvalidPolicy):
                PublicationPolicy(version="v", ordinary_resolution_metres=metres).validate()

    def test_an_undrawable_map_cell_resolution_is_rejected(self):
        with self.assertRaises(InvalidPolicy):
            PublicationPolicy(version="v", map_cell_resolution_metres=2000).validate()

    def test_sensitive_floors_can_never_be_finer_than_ordinary(self):
        cases = (
            {"default_sensitive_metres": 100},
            {"row_sensitive_resolution_metres": 100},
            {"sensitive_resolution_metres": {"2028": 100}},
            {"sensitive_record_type_metres": {"nest": 100}},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(InvalidPolicy):
                PublicationPolicy(
                    version="v",
                    ordinary_resolution_metres=1000,
                    public_id_salt="x" * 32,
                    **values,
                ).validate()

    def test_an_undrawable_sensitive_resolution_is_rejected(self):
        with self.assertRaises(InvalidPolicy):
            PublicationPolicy(version="v", default_sensitive_metres=50000).validate()

    def test_an_undrawable_row_sensitive_resolution_is_rejected(self):
        with self.assertRaises(InvalidPolicy):
            PublicationPolicy(
                version="v",
                row_sensitive_resolution_metres=2000,
                public_id_salt="x" * 32,
            ).validate()

    def test_an_undrawable_per_species_override_is_rejected(self):
        with self.assertRaises(InvalidPolicy) as ctx:
            PublicationPolicy(version="v", sensitive_resolution_metres={"2028": 2000}).validate()
        self.assertIn("2028", str(ctx.exception))

    def test_an_undrawable_record_type_resolution_is_rejected(self):
        with self.assertRaises(InvalidPolicy) as ctx:
            PublicationPolicy(
                version="v", sensitive_record_type_metres={"bat roost": 100000}
            ).validate()
        self.assertIn("bat roost", str(ctx.exception))

    def test_a_zero_suppression_threshold_is_rejected(self):
        with self.assertRaises(InvalidPolicy):
            PublicationPolicy(version="v", min_records_per_cell=0).validate()

    def test_suppression_mode_and_threshold_must_agree(self):
        cases = (
            {"suppression_mode": "none", "min_records_per_cell": 2},
            {"suppression_mode": "minimum-count", "min_records_per_cell": 1},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(InvalidPolicy):
                PublicationPolicy(version="v", public_id_salt="x" * 32, **values).validate()

    def test_licensing_mode_and_allow_list_must_agree(self):
        cases = (
            {
                "licensing_mode": "not-applicable",
                "allowed_licence_values": frozenset({"public"}),
            },
            {
                "licensing_mode": "all-publication-allow-list",
                "allowed_licence_values": None,
            },
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(InvalidPolicy):
                PublicationPolicy(version="v", public_id_salt="x" * 32, **values).validate()

    def test_verification_mode_and_vocabulary_must_agree(self):
        with self.assertRaises(InvalidPolicy):
            PublicationPolicy(
                version="v",
                verification_publication_mode="unavailable",
                accepted_verification_values=frozenset({"accepted"}),
                public_id_salt="x" * 32,
            ).validate()
        with self.assertRaises(InvalidPolicy):
            PublicationPolicy(
                version="v",
                verification_publication_mode="publish",
                accepted_verification_values=None,
                public_id_salt="x" * 32,
            ).validate()

        PublicationPolicy(
            version="development",
            development_only=True,
            verification_publication_mode="publish",
            public_id_salt="x" * 32,
        ).validate()

    def test_record_type_rules_require_a_complete_bound_vocabulary(self):
        cases = (
            {
                "record_type_safety_mode": "rules",
                "sensitive_record_type_metres": {"nest": 10000},
            },
            {
                "record_type_safety_mode": "rules",
                "sensitive_record_type_metres": {"nest": 10000},
                "record_type_vocabulary": frozenset({"field record"}),
            },
            {
                "record_type_safety_mode": "not-used",
                "sensitive_record_type_metres": {"nest": 10000},
                "record_type_vocabulary": frozenset({"nest"}),
            },
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(InvalidPolicy):
                PublicationPolicy(version="v", public_id_salt="x" * 32, **values).validate()

    def test_row_mode_and_boolean_must_agree(self):
        cases = (
            {
                "row_level_records_mode": "aggregates-only",
                "publish_individual_records": True,
            },
            {"row_level_records_mode": "publish", "publish_individual_records": False},
            {
                "row_level_records_mode": "aggregates-only",
                "publish_place_names": True,
            },
            {
                "row_level_records_mode": "aggregates-only",
                "publish_original_record_ids": True,
            },
            {
                "row_level_records_mode": "aggregates-only",
                "publish_abundance": True,
            },
            {
                "row_level_records_mode": "aggregates-only",
                "publish_record_type": True,
            },
            {
                "row_level_records_mode": "aggregates-only",
                "publish_record_verification": True,
                "verification_publication_mode": "publish",
            },
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(InvalidPolicy):
                PublicationPolicy(version="v", public_id_salt="x" * 32, **values).validate()

    def test_there_is_no_ordinary_option_for_unknown_species(self):
        with self.assertRaises(InvalidPolicy) as ctx:
            PublicationPolicy(version="v", unknown_species_action="ordinary").validate()
        self.assertIn("withhold", str(ctx.exception))

    def test_the_development_policy_is_valid(self):
        DEVELOPMENT_POLICY.validate()

    def test_the_null_policy_refuses_to_run_at_all(self):
        # Not "publishes nothing" - refuses. Choosing what the public sees must
        # be an act, not an omission.
        with self.assertRaises(InvalidPolicy):
            UNAPPROVED_POLICY.validate()

    def test_a_policy_that_can_neither_derive_nor_publish_an_id_is_rejected(self):
        # Checked up front rather than at the first row: a policy that raises
        # halfway through a run leaves a half-built payload and reads as a data
        # fault rather than a missing setting.
        with self.assertRaises(InvalidPolicy) as ctx:
            PublicationPolicy(version="v").validate()
        self.assertIn("public_id_salt", str(ctx.exception))

    def test_either_a_salt_or_a_deliberate_choice_satisfies_it(self):
        PublicationPolicy(version="v", public_id_salt="x" * 32).validate()
        PublicationPolicy(version="v", publish_original_record_ids=True).validate()

    def test_a_short_hmac_secret_is_rejected(self):
        with self.assertRaises(InvalidPolicy) as ctx:
            PublicationPolicy(version="v", public_id_salt="guessable").validate()
        self.assertIn("32", str(ctx.exception))

    def test_row_fields_cannot_be_enabled_when_individual_rows_are_off(self):
        for field_name in (
            "publish_abundance",
            "publish_record_type",
            "publish_record_verification",
        ):
            with self.subTest(field=field_name), self.assertRaises(InvalidPolicy):
                PublicationPolicy(
                    version="v",
                    public_id_salt="x" * 32,
                    **{field_name: True},
                ).validate()

    def test_yaml_like_values_cannot_turn_disclosure_controls_on(self):
        fields = (
            "development_only",
            "publish_place_names",
            "publish_original_record_ids",
            "publish_individual_records",
            "publish_abundance",
            "publish_record_type",
            "publish_record_verification",
            "coarsen_unpublishable_resolutions",
        )
        for field_name in fields:
            for value in ("false", "true", 0, 1, None):
                with self.subTest(field=field_name, value=value), self.assertRaises(InvalidPolicy):
                    PublicationPolicy(
                        version="v",
                        public_id_salt="x" * 32,
                        **{field_name: value},
                    ).validate()

    def test_record_verification_requires_both_aggregate_verification_and_rows(self):
        invalid = (
            {
                "row_level_records_mode": "publish",
                "publish_individual_records": True,
                "verification_publication_mode": "unavailable",
                "publish_record_verification": True,
            },
            {
                "row_level_records_mode": "aggregates-only",
                "publish_individual_records": False,
                "verification_publication_mode": "publish",
                "publish_record_verification": True,
            },
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(InvalidPolicy):
                PublicationPolicy(
                    version="v",
                    development_only=True,
                    public_id_salt="x" * 32,
                    **values,
                ).validate()

        PublicationPolicy(
            version="v",
            development_only=True,
            row_level_records_mode="publish",
            publish_individual_records=True,
            verification_publication_mode="publish",
            publish_record_verification=True,
            public_id_salt="x" * 32,
        ).validate()

    def test_integer_controls_reject_booleans_strings_and_floats(self):
        for field_name in (
            "ordinary_resolution_metres",
            "default_sensitive_metres",
            "row_sensitive_resolution_metres",
            "min_records_per_cell",
        ):
            for value in (True, False, "1000", 1000.0):
                with self.subTest(field=field_name, value=value), self.assertRaises(InvalidPolicy):
                    PublicationPolicy(
                        version="v",
                        public_id_salt="x" * 32,
                        **{field_name: value},
                    ).validate()

        for field_name in (
            "sensitive_resolution_metres",
            "sensitive_record_type_metres",
        ):
            for value in (True, "1000", 1000.0):
                with self.subTest(field=field_name, value=value), self.assertRaises(InvalidPolicy):
                    PublicationPolicy(
                        version="v",
                        public_id_salt="x" * 32,
                        **{field_name: {"test": value}},
                    ).validate()


class TestResolutionDecisions(unittest.TestCase):
    POLICY = PublicationPolicy(
        version="v",
        ordinary_resolution_metres=100,
        default_sensitive_metres=10000,
        sensitive_resolution_metres={"2028": 1000},
        sensitive_record_type_metres={"bat roost": 10000},
    )

    def test_ordinary_species(self):
        self.assertEqual(self.POLICY.resolution_for("999999", sensitive=False, known=True), 100)

    def test_sensitive_species_without_an_override(self):
        self.assertEqual(self.POLICY.resolution_for("2169", sensitive=True, known=True), 10000)

    def test_a_per_species_override_wins(self):
        self.assertEqual(self.POLICY.resolution_for("2028", sensitive=True, known=True), 1000)

    def test_a_per_species_rule_cannot_be_disabled_by_a_false_flag(self):
        self.assertTrue(self.POLICY.has_sensitive_species_rule(" 2028 "))
        self.assertEqual(self.POLICY.resolution_for("2028", sensitive=False, known=True), 1000)

    def test_an_unknown_species_is_withheld(self):
        self.assertIsNone(self.POLICY.resolution_for("999999", sensitive=False, known=False))
        self.assertIsNone(self.POLICY.resolution_for(None, sensitive=False, known=True))

    def test_record_type_lookup_is_normalised(self):
        self.assertEqual(self.POLICY.resolution_for_record_type("BAT ROOST"), 10000)
        self.assertEqual(self.POLICY.resolution_for_record_type(" bat roost "), 10000)
        self.assertIsNone(self.POLICY.resolution_for_record_type("field record"))
        self.assertIsNone(self.POLICY.resolution_for_record_type(None))
        self.assertIsNone(self.POLICY.resolution_for_record_type("   "))


class TestLicenceGate(unittest.TestCase):
    def test_an_undecided_licence_policy_fails_closed(self):
        policy = PublicationPolicy(version="v", licensing_mode="undecided")
        for value in ("CC-BY", "", None, "anything"):
            self.assertFalse(policy.licence_permits_publication(value))

    def test_not_applicable_is_an_explicit_publish_decision(self):
        policy = PublicationPolicy(version="v", licensing_mode="not-applicable")
        for value in ("CC-BY", "", None, "anything"):
            self.assertTrue(policy.licence_permits_publication(value))

    def test_an_enforced_licence_gate_fails_closed(self):
        policy = PublicationPolicy(
            version="v",
            licensing_mode="all-publication-allow-list",
            allowed_licence_values=frozenset({"cc-by", "ogl"}),
        )
        self.assertTrue(policy.licence_permits_publication("CC-BY"))
        self.assertTrue(policy.licence_permits_publication("  ogl  "))
        self.assertFalse(policy.licence_permits_publication("cc-by-nc"))
        self.assertFalse(policy.licence_permits_publication(None))
        self.assertFalse(policy.licence_permits_publication(""))


class TestRowSensitivityVocabulary(unittest.TestCase):
    def test_only_explicit_non_sensitive_values_take_the_ordinary_path(self):
        policy = PublicationPolicy(
            version="view-test",
            public_id_salt="test" * 8,
            non_sensitive_values=frozenset({" No ", "N"}),
        )
        for value in ("no", "NO", "  n  "):
            with self.subTest(value=value):
                self.assertFalse(policy.is_row_sensitive(value))

        for value in ("yes", "unknown", "0", None, "", "   "):
            with self.subTest(value=value):
                self.assertTrue(policy.is_row_sensitive(value))

    def test_an_empty_vocabulary_is_fail_closed(self):
        policy = PublicationPolicy(version="view-test", public_id_salt="test" * 8)
        for value in ("no", "yes", None, ""):
            with self.subTest(value=value):
                self.assertTrue(policy.is_row_sensitive(value))

    def test_blank_can_never_be_configured_as_not_sensitive(self):
        for value in ("", "   "):
            with self.subTest(value=value), self.assertRaises(InvalidPolicy):
                PublicationPolicy(
                    version="bad",
                    public_id_salt="test" * 8,
                    non_sensitive_values=frozenset({value}),
                )


class TestPolicyVocabulariesAreCanonicalAndImmutable(unittest.TestCase):
    def test_species_and_record_type_keys_are_normalised_before_lookup(self):
        policy = PublicationPolicy(
            version="v",
            public_id_salt="test" * 8,
            ordinary_resolution_metres=100,
            default_sensitive_metres=1000,
            sensitive_resolution_metres={" 6973a ": 10000},
            sensitive_record_type_metres={"  Bat Roost  ": 10000},
        )
        self.assertEqual(policy.resolution_for("6973A", sensitive=True, known=True), 10000)
        self.assertEqual(policy.resolution_for_record_type("bat roost"), 10000)
        self.assertEqual(policy.resolution_for_record_type("  BAT ROOST "), 10000)

    def test_caller_owned_mappings_cannot_change_an_approved_policy(self):
        today = date.today()
        species_rules = {"6973a": 10000}
        record_type_rules = {"Bat Roost": 10000}
        policy = PublicationPolicy(
            version="v",
            precision_mode="approved",
            suppression_mode="none",
            licensing_mode="not-applicable",
            record_type_safety_mode="rules",
            row_level_records_mode="aggregates-only",
            verification_publication_mode="unavailable",
            sensitive_snapshot_version=SENSITIVE_SNAPSHOT_VERSION,
            sensitive_snapshot_sha256=SENSITIVE_SNAPSHOT_SHA256,
            public_id_salt="test" * 8,
            sensitive_resolution_metres=species_rules,
            sensitive_record_type_metres=record_type_rules,
            record_type_vocabulary=frozenset({"field record", "bat roost"}),
        )
        policy = approve(
            policy,
            approved_on=today.isoformat(),
            review_due=(today + timedelta(days=365)).isoformat(),
        )

        species_rules["6973a"] = 100
        record_type_rules["Bat Roost"] = 100
        self.assertEqual(policy.sensitive_resolution_metres["6973A"], 10000)
        self.assertEqual(policy.sensitive_record_type_metres["bat roost"], 10000)
        with self.assertRaises(TypeError):
            policy.sensitive_resolution_metres["NEW"] = 100  # type: ignore[index]
        with self.assertRaises(TypeError):
            policy.sensitive_record_type_metres["new"] = 100  # type: ignore[index]

    def test_duplicate_or_blank_keys_after_normalisation_are_rejected(self):
        cases = (
            {"6973a": 1000, " 6973A ": 10000},
            {"": 1000},
        )
        for rules in cases:
            with self.subTest(rules=rules), self.assertRaises(InvalidPolicy):
                PublicationPolicy(
                    version="v",
                    public_id_salt="test" * 8,
                    sensitive_resolution_metres=rules,
                )

        with self.assertRaises(InvalidPolicy):
            PublicationPolicy(
                version="v",
                public_id_salt="test" * 8,
                sensitive_record_type_metres={"   ": 1000},
            )

    def test_numeric_species_rule_keys_are_rejected_instead_of_missing_the_source_id(self):
        for key in (1234, 1234.0):
            with self.subTest(key=key), self.assertRaises(InvalidPolicy):
                PublicationPolicy(
                    version="v",
                    public_id_salt="test" * 8,
                    sensitive_resolution_metres={key: 10000},  # type: ignore[dict-item]
                )

    def test_licence_and_verification_vocabularies_are_normalised_and_frozen(self):
        licences = {" CC-BY "}
        verdicts = {" Accepted - Correct "}
        policy = PublicationPolicy(
            version="v",
            public_id_salt="test" * 8,
            allowed_licence_values=licences,  # type: ignore[arg-type]
            accepted_verification_values=verdicts,  # type: ignore[arg-type]
        )
        licences.add("private")
        verdicts.add("rejected")
        self.assertEqual(policy.allowed_licence_values, frozenset({"cc-by"}))
        self.assertEqual(
            policy.accepted_verification_values,
            frozenset({"accepted - correct"}),
        )

    def test_vocabulary_scalars_lists_and_non_strings_are_rejected(self):
        fields = (
            "non_sensitive_values",
            "allowed_licence_values",
            "accepted_verification_values",
        )
        for field_name in fields:
            for value in ("yes", ["yes"], frozenset({1}), frozenset({"yes", " YES "})):
                with self.subTest(field=field_name, value=value), self.assertRaises(InvalidPolicy):
                    PublicationPolicy(
                        version="v",
                        public_id_salt="x" * 32,
                        **{field_name: value},
                    )


class TestPublicRecordIds(unittest.TestCase):
    POLICY = PublicationPolicy(version="v", public_id_salt="a-secret-" * 4)

    def test_the_public_id_is_not_the_original(self):
        self.assertNotEqual(self.POLICY.public_record_id("5610349"), "5610349")

    def test_it_is_deterministic(self):
        self.assertEqual(
            self.POLICY.public_record_id("5610349"), self.POLICY.public_record_id("5610349")
        )

    def test_different_records_get_different_ids(self):
        ids = {self.POLICY.public_record_id(str(i)) for i in range(1000)}
        self.assertEqual(len(ids), 1000)

    def test_a_different_salt_gives_a_different_id(self):
        other = PublicationPolicy(version="v", public_id_salt="a-different-secret-" * 2)
        self.assertNotEqual(
            self.POLICY.public_record_id("5610349"), other.public_record_id("5610349")
        )

    def test_the_original_id_does_not_appear_in_the_public_one(self):
        self.assertNotIn("5610349", self.POLICY.public_record_id("5610349"))

    def test_publishing_originals_must_be_deliberate(self):
        policy = PublicationPolicy(version="v", publish_original_record_ids=True)
        self.assertEqual(policy.public_record_id("5610349"), "5610349")

    def test_no_salt_and_no_deliberate_choice_raises(self):
        policy = PublicationPolicy(version="v")
        with self.assertRaises(PolicyNotApproved):
            policy.public_record_id("5610349")


class TestDescribe(unittest.TestCase):
    def test_the_summary_reports_the_real_approval_state(self):
        described = DEVELOPMENT_POLICY.describe()
        self.assertFalse(described["approved"])
        self.assertTrue(described["developmentOnly"])

    def test_the_summary_carries_no_secret(self):
        secret = "unique-secret-material-never-log-" * 2
        policy = PublicationPolicy(version="v", public_id_salt=secret)
        for rendered in (repr(policy), str(policy), str(policy.describe())):
            self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main(verbosity=1)
