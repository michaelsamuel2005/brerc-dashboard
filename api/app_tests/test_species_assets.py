"""The approved species-assets registry — fail-loud on anything a human did not sign off.

Showing an image the dashboard is not licensed to show is a legal problem for
BRERC (and Bristol City Council), not a cosmetic bug, and it is the kind of
mistake that looks fine on screen.  These tests hold the serving side to the
rule: nothing loads unless the file is explicitly approved and every entry is
complete — licence on the allow-list, https-only URLs, attribution, approval
reference, alt text.  A malformed file must abort, not partially serve.

No database and no network: this is pure file validation.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app import species_assets
from app.species_assets import SpeciesAssetsError, load_registry


def valid_image(**overrides) -> dict:
    image = {
        "url": "https://example.org/robin.jpg",
        "attributionText": "(c) Jane Doe",
        "licence": "CC BY 4.0",
        "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
        "sourceUrl": "https://example.org/photos/robin",
        "approvalReference": "BRERC-IMG-001 approved 2026-08-17 TT",
        "alt": "A robin perched on a branch",
    }
    image.update(overrides)
    return image


def valid_entry(**overrides) -> dict:
    entry = {
        "scientificName": "Erithacus rubecula",
        "image": valid_image(),
        "description": "A small insectivorous passerine bird.",
        "descriptionSource": {
            "label": "Wikipedia",
            "sourceUrl": "https://en.wikipedia.org/wiki/European_robin",
            "licence": "CC BY-SA 4.0",
            "licenceUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
            "approvalReference": "BRERC-DESC-001 approved 2026-08-17 TT",
        },
    }
    entry.update(overrides)
    return entry


class RegistryFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def write(self, payload: dict) -> str:
        path = Path(self._dir.name) / "assets.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def load(self, payload: dict):
        return load_registry(self.write(payload))

    # -- the ordinary states --------------------------------------------------

    def test_unset_path_is_the_inactive_registry(self) -> None:
        for path in (None, "", "   "):
            registry = load_registry(path)
            self.assertFalse(registry.active)
            self.assertIsNone(registry.for_name("Erithacus rubecula"))

    def test_missing_file_is_the_inactive_registry(self) -> None:
        registry = load_registry(str(Path(self._dir.name) / "no-such-file.json"))
        self.assertFalse(registry.active)

    def test_a_valid_approved_file_loads_and_answers_case_insensitively(self) -> None:
        registry = self.load({"approved": True, "species": [valid_entry()]})
        self.assertTrue(registry.active)
        assets = registry.for_name("  erithacus   RUBECULA ")
        self.assertIsNotNone(assets)
        self.assertEqual(assets.image.licence, "CC BY 4.0")
        self.assertTrue(registry.has_image("Erithacus rubecula"))
        self.assertFalse(registry.has_image("Anguis fragilis"))

    def test_curator_notes_are_tolerated_and_ignored(self) -> None:
        entry = valid_entry(curatorNotes=["alt text is generated"])
        registry = self.load({"approved": True, "species": [entry]})
        self.assertTrue(registry.has_image("Erithacus rubecula"))

    # -- the human step cannot be skipped -------------------------------------

    def test_a_candidates_file_is_refused_outright(self) -> None:
        with self.assertRaisesRegex(SpeciesAssetsError, "approved"):
            self.load({"approved": False, "species": [valid_entry()]})

    def test_missing_approval_reference_on_the_image_is_refused(self) -> None:
        entry = valid_entry(image=valid_image(approvalReference="  "))
        with self.assertRaisesRegex(SpeciesAssetsError, "approvalReference"):
            self.load({"approved": True, "species": [entry]})

    # -- the licence gate holds at serving time too ----------------------------

    def test_a_licence_off_the_allow_list_is_refused_even_if_approved(self) -> None:
        entry = valid_entry(image=valid_image(licence="CC BY-SA 4.0"))
        with self.assertRaisesRegex(SpeciesAssetsError, "allowed list"):
            self.load({"approved": True, "species": [entry]})

    def test_an_unrecognised_licence_label_is_refused(self) -> None:
        entry = valid_entry(image=valid_image(licence="All rights reserved"))
        with self.assertRaisesRegex(SpeciesAssetsError, "not a recognised label"):
            self.load({"approved": True, "species": [entry]})

    def test_http_urls_are_refused_everywhere(self) -> None:
        for field in ("url", "licenceUrl", "sourceUrl"):
            entry = valid_entry(image=valid_image(**{field: "http://example.org/x"}))
            with self.assertRaisesRegex(SpeciesAssetsError, field):
                self.load({"approved": True, "species": [entry]})

    def test_missing_attribution_or_alt_is_refused(self) -> None:
        for field in ("attributionText", "alt"):
            entry = valid_entry(image=valid_image(**{field: ""}))
            with self.assertRaisesRegex(SpeciesAssetsError, field):
                self.load({"approved": True, "species": [entry]})

    # -- the description contract ----------------------------------------------

    def test_description_and_source_must_travel_together(self) -> None:
        lone_description = valid_entry()
        del lone_description["descriptionSource"]
        with self.assertRaisesRegex(SpeciesAssetsError, "together"):
            self.load({"approved": True, "species": [lone_description]})
        lone_source = valid_entry()
        del lone_source["description"]
        with self.assertRaisesRegex(SpeciesAssetsError, "together"):
            self.load({"approved": True, "species": [lone_source]})

    def test_description_licence_url_requires_licence_text(self) -> None:
        entry = valid_entry()
        del entry["descriptionSource"]["licence"]
        with self.assertRaisesRegex(SpeciesAssetsError, "licence"):
            self.load({"approved": True, "species": [entry]})

    # -- structural refusals ----------------------------------------------------

    def test_unknown_fields_are_refused_not_ignored(self) -> None:
        entry = valid_entry(surprise="field")
        with self.assertRaisesRegex(SpeciesAssetsError, "unknown field"):
            self.load({"approved": True, "species": [entry]})
        entry = valid_entry(image=valid_image(caption="pretty bird"))
        with self.assertRaisesRegex(SpeciesAssetsError, "unknown image field"):
            self.load({"approved": True, "species": [entry]})

    def test_duplicate_species_are_refused(self) -> None:
        with self.assertRaisesRegex(SpeciesAssetsError, "duplicate"):
            self.load({"approved": True, "species": [valid_entry(), valid_entry()]})

    def test_an_entry_with_no_media_at_all_is_refused(self) -> None:
        with self.assertRaisesRegex(SpeciesAssetsError, "neither"):
            self.load({"approved": True, "species": [{"scientificName": "Erithacus rubecula"}]})

    def test_unparseable_json_is_refused_loudly(self) -> None:
        path = Path(self._dir.name) / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(SpeciesAssetsError, "cannot read"):
            load_registry(str(path))


class ProcessRegistryTests(unittest.TestCase):
    """The process-wide singleton honours config and can be reset by tests."""

    def tearDown(self) -> None:
        species_assets.reset_registry()

    def test_registry_defaults_to_inactive_when_unconfigured(self) -> None:
        species_assets.reset_registry()
        from app import config

        original = config.SPECIES_ASSETS_FILE
        config.SPECIES_ASSETS_FILE = ""
        try:
            self.assertFalse(species_assets.registry().active)
        finally:
            config.SPECIES_ASSETS_FILE = original


if __name__ == "__main__":
    unittest.main()


class PipelineRoundTripTests(unittest.TestCase):
    """The whole pipeline in one test: CLI candidates -> refused -> review -> served.

    Uses the real CLI with a stubbed fetch (no network), then holds the output
    to the serving rules: a candidates file must be refused as written, and the
    SAME file after a simulated human review must load.  This is the test that
    keeps the two halves of the pipeline speaking the same format.
    """

    def test_candidates_are_refused_until_reviewed_then_served(self) -> None:
        import curation.__main__ as cli
        from curation.species_media import CandidateImage, CandidateInfo, Curator

        candidate = CandidateInfo(
            image=CandidateImage(
                url="https://example.org/robin.jpg",
                attributionText="(c) Jane Doe",
                licence="CC BY 2.0",
                licenceUrl="https://creativecommons.org/licenses/by/2.0/",
                sourceUrl="https://example.org/photos/robin",
                alt="Photograph of Erithacus rubecula",
                licence_url_assumed=False,
            ),
            description="A small insectivorous passerine bird.",
            description_source={
                "label": "Wikipedia",
                "sourceUrl": "https://en.wikipedia.org/wiki/European_robin",
                "licence": "CC BY-SA 4.0",
                "licenceUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
                "approvalReference": "",
            },
            notes=["alt text is generated — replace with a real description"],
        )
        original_fetch = Curator.fetch
        Curator.fetch = lambda self, name: candidate  # type: ignore[method-assign]
        try:
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory) / "candidates.json"
                exit_code = cli.main(
                    ["Erithacus rubecula", "--contact", "x@example.org", "--out", str(out)]
                )
                self.assertEqual(exit_code, 0)

                # As written by the CLI: explicitly unapproved, and refused.
                with self.assertRaisesRegex(SpeciesAssetsError, "approved"):
                    load_registry(str(out))

                # Simulate the human review: fill every approvalReference and
                # flip the flag — nothing else should need changing.
                payload = json.loads(out.read_text(encoding="utf-8"))
                payload["approved"] = True
                for entry in payload["species"]:
                    if "image" in entry:
                        entry["image"]["approvalReference"] = "BRERC-IMG-9 2026-08-17 TT"
                    if "descriptionSource" in entry:
                        entry["descriptionSource"]["approvalReference"] = (
                            "BRERC-DESC-9 2026-08-17 TT"
                        )
                out.write_text(json.dumps(payload), encoding="utf-8")

                registry = load_registry(str(out))
                self.assertTrue(registry.has_image("Erithacus rubecula"))
                assets = registry.for_name("Erithacus rubecula")
                self.assertEqual(assets.image.licence, "CC BY 2.0")
                self.assertEqual(assets.descriptionSource.label, "Wikipedia")
        finally:
            Curator.fetch = original_fetch  # type: ignore[method-assign]

    def test_the_cli_refuses_to_run_with_no_names(self) -> None:
        import curation.__main__ as cli

        with tempfile.TemporaryDirectory() as directory:
            exit_code = cli.main(
                ["--contact", "x@example.org", "--out", str(Path(directory) / "c.json")]
            )
        self.assertEqual(exit_code, 2)
