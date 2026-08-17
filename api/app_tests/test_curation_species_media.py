"""The curation licence gate — ported from ``main``'s B8 proxy tests.

WHY THESE MATTER MORE THAN MOST
Showing an image we are not licensed to show is a legal problem for BRERC (and
Bristol City Council), not a cosmetic bug, and it is the kind of mistake that
looks fine on screen.  So the rule is asserted directly here: unless a
permitted licence AND an attribution are both confirmed, there is no candidate
image at all.  The assertions and fixtures follow the original suite; what
changed is the output shape — candidates now carry the serving contract's
licenceUrl / sourceUrl / alt, and descriptions carry a STRUCTURED source
instead of an inline credit — so those additions are tested here too.

NO NETWORK.  Every test swaps a fake HTTP transport in through the
``Curator._new_client`` seam, exactly as the original did, so the suite is
fast, offline, deterministic, and never sends traffic to iNaturalist, GBIF or
Wikipedia.
"""

from __future__ import annotations

import typing
import unittest

import httpx

from curation.species_media import (
    Curator,
    licence_is_allowed,
    licence_label_and_url,
    normalise_licence,
    truncate,
    vet_image,
)

NAME = "Erithacus rubecula"
ALLOWED = frozenset({"cc0", "pd", "cc-by"})

INAT = "api.inaturalist.org/v1/taxa"
GBIF_MATCH = "api.gbif.org/v1/species/match"
GBIF_SEARCH = "api.gbif.org/v1/occurrence/search"
WIKI_SUMMARY = "en.wikipedia.org/api/rest_v1/page/summary/"
COMMONS = "en.wikipedia.org/w/api.php"


def inat_photo(licence, attribution="(c) Jane Doe, some rights reserved", name=NAME):
    return {
        "results": [
            {
                "id": 13094,
                "name": name,
                "default_photo": {
                    "medium_url": "https://inaturalist-open-data.s3.amazonaws.com/p/1/medium.jpg",
                    "license_code": licence,
                    "attribution": attribution,
                },
            }
        ]
    }


def gbif_media(licence, rights_holder="Bristol Recorder"):
    return {
        "results": [
            {
                "key": 987654321,
                "media": [
                    {
                        "type": "StillImage",
                        "identifier": "https://images.gbif.org/occurrence/1.jpg",
                        "license": licence,
                        "rightsHolder": rights_holder,
                    }
                ],
            }
        ]
    }


WIKI_PAGE = {
    "type": "standard",
    "extract": "The European robin is a small insectivorous passerine bird "
    "found across Europe. It is strongly territorial.",
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/European_robin"}},
    "originalimage": {
        "source": "https://upload.wikimedia.org/wikipedia/commons/a/a5/Erithacus_rubecula.jpg"
    },
    "thumbnail": {
        "source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/"
        "Erithacus_rubecula.jpg/320px-Erithacus_rubecula.jpg"
    },
}


def commons_file(licence, artist="<a href='/wiki/User:JD'>Jane Doe</a>"):
    return {
        "query": {
            "pages": [
                {
                    "imageinfo": [
                        {
                            "extmetadata": {
                                "LicenseShortName": {"value": licence},
                                "Artist": {"value": artist},
                            }
                        }
                    ]
                }
            ]
        }
    }


EMPTY_RESULTS = {"results": []}
NO_GBIF_MATCH = {"matchType": "NONE"}
GBIF_EXACT = {"matchType": "EXACT", "usageKey": 2492462}


class FakeUpstream:
    """Wire fake upstream responses through the ``_new_client`` seam."""

    def __init__(self, curator: Curator):
        self.curator = curator
        self.requests: list[str] = []

    def serve(self, routes: dict, raises: Exception | None = None) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            target = f"{request.url.host}{request.url.path}"
            self.requests.append(target)
            if raises is not None:
                raise raises
            for prefix, payload in routes.items():
                if target.startswith(prefix):
                    return httpx.Response(200, json=payload)
            return httpx.Response(404, json={})

        transport = httpx.MockTransport(handler)
        self.curator._new_client = lambda: httpx.Client(transport=transport)  # type: ignore[method-assign]

    def called(self, prefix: str) -> bool:
        return any(target.startswith(prefix) for target in self.requests)


def make_curator() -> tuple[Curator, FakeUpstream]:
    curator = Curator(
        contact="dashboard@example.org",
        allowed_licences=ALLOWED,
        min_interval_seconds=0.0,
    )
    return curator, FakeUpstream(curator)


# =============================================================================
# 1. The licence normaliser — one canonical answer from three different wordings
# =============================================================================


class LicenceNormaliserTests(unittest.TestCase):
    CASES: typing.ClassVar[list[tuple[str | None, str | None]]] = [
        # iNaturalist sends short codes.
        ("cc0", "cc0"),
        ("cc-by", "cc-by"),
        ("cc-by-nc", "cc-by-nc"),
        ("cc-by-sa", "cc-by-sa"),
        ("cc-by-nc-nd", "cc-by-nc-nd"),
        # GBIF sends licence URLs.
        ("http://creativecommons.org/licenses/by/4.0/", "cc-by"),
        ("http://creativecommons.org/licenses/by-nc/4.0/", "cc-by-nc"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "cc0"),
        ("http://creativecommons.org/publicdomain/mark/1.0/", "pd"),
        # Wikimedia Commons sends human labels.
        ("CC BY-SA 4.0", "cc-by-sa"),
        ("CC0", "cc0"),
        ("Public domain", "pd"),
        # Anything we cannot positively identify must come back None, which is
        # always refused.  We never assume a photo is open.
        ("All rights reserved", None),
        ("UNSPECIFIED", None),
        ("http://rs.tdwg.org/dwc/terms/UnknownLicense", None),
        ("", None),
        (None, None),
    ]

    def test_licence_normaliser(self) -> None:
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(normalise_licence(raw), expected)

    def test_nc_licence_is_not_mistaken_for_plain_cc_by(self) -> None:
        """The subtle one: "cc-by-nc" starts with "cc-by".  A prefix test would
        wave every NonCommercial photo through."""
        self.assertEqual(normalise_licence("cc-by-nc"), "cc-by-nc")
        self.assertTrue(licence_is_allowed("cc-by", ALLOWED))
        self.assertFalse(licence_is_allowed("cc-by-nc", ALLOWED))

    def test_a_hostname_containing_by_is_not_a_licence(self) -> None:
        self.assertIsNone(normalise_licence("birdsby-org"))

    def test_deed_url_uses_the_stated_version_or_flags_the_assumption(self) -> None:
        label, url, assumed = licence_label_and_url("http://creativecommons.org/licenses/by/2.0/")
        self.assertEqual((label, assumed), ("CC BY 2.0", False))
        self.assertEqual(url, "https://creativecommons.org/licenses/by/2.0/")
        label, url, assumed = licence_label_and_url("cc-by")
        self.assertEqual((label, assumed), ("CC BY", True))
        self.assertEqual(url, "https://creativecommons.org/licenses/by/4.0/")
        label, url, assumed = licence_label_and_url("CC0")
        self.assertEqual(
            (label, url, assumed),
            ("CC0", "https://creativecommons.org/publicdomain/zero/1.0/", False),
        )


# =============================================================================
# 2. The gate itself — every refusal is a legal requirement, not a preference
# =============================================================================


class VetImageTests(unittest.TestCase):
    def vet(self, **overrides):
        arguments = {
            "url": "https://example.org/photo.jpg",
            "raw_licence": "cc-by",
            "attribution": "(c) Jane Doe",
            "source_url": "https://example.org/photos/1",
            "species_name": NAME,
            "allowed": ALLOWED,
        }
        arguments.update(overrides)
        return vet_image(
            arguments.pop("url"),
            arguments.pop("raw_licence"),
            arguments.pop("attribution"),
            **arguments,
        )

    def test_a_fully_licensed_credited_https_image_passes(self) -> None:
        image = self.vet()
        self.assertIsNotNone(image)
        self.assertEqual(image.licence, "CC BY")
        self.assertEqual(image.alt, f"Photograph of {NAME}")
        self.assertTrue(image.licence_url_assumed)

    def test_disallowed_or_unknown_licences_are_refused(self) -> None:
        for licence in ("cc-by-nc", "cc-by-nd", "All rights reserved", None, ""):
            with self.subTest(licence=licence):
                self.assertIsNone(self.vet(raw_licence=licence))

    def test_missing_attribution_is_refused_even_with_a_good_licence(self) -> None:
        for attribution in (None, "", "   ", "<i></i>"):
            with self.subTest(attribution=attribution):
                self.assertIsNone(self.vet(attribution=attribution))

    def test_non_https_urls_are_refused(self) -> None:
        self.assertIsNone(self.vet(url="http://example.org/photo.jpg"))
        self.assertIsNone(self.vet(url="ftp://example.org/photo.jpg"))
        self.assertIsNone(self.vet(url=None))
        self.assertIsNone(self.vet(source_url="http://example.org/photos/1"))
        self.assertIsNone(self.vet(source_url=None))

    def test_html_is_stripped_from_the_attribution(self) -> None:
        image = self.vet(attribution="<a href='/wiki/User:JD'>Jane&nbsp;Doe</a>")
        self.assertNotIn("<", image.attributionText)


# =============================================================================
# 3. The sources — each one funnels through the gate and cannot bypass it
# =============================================================================


class SourceCascadeTests(unittest.TestCase):
    def test_inaturalist_image_is_used_when_licensed(self) -> None:
        curator, upstream = make_curator()
        upstream.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})
        info = curator.fetch(NAME)
        self.assertIsNotNone(info.image)
        self.assertEqual(info.image.sourceUrl, "https://www.inaturalist.org/taxa/13094")
        # Found at the first source: GBIF must not have been called at all.
        self.assertFalse(upstream.called(GBIF_MATCH))

    def test_a_wrong_species_result_is_skipped_even_with_a_perfect_licence(self) -> None:
        """A photo of the wrong animal is a data-quality bug the licence check
        would not catch."""
        curator, upstream = make_curator()
        upstream.serve(
            {
                INAT: inat_photo("cc-by", name="Turdus migratorius"),
                GBIF_MATCH: NO_GBIF_MATCH,
                WIKI_SUMMARY: {},
            }
        )
        self.assertIsNone(curator.fetch(NAME).image)

    def test_unlicensed_inat_photo_falls_through_to_gbif(self) -> None:
        curator, upstream = make_curator()
        upstream.serve(
            {
                INAT: inat_photo(None),
                GBIF_MATCH: GBIF_EXACT,
                GBIF_SEARCH: gbif_media("http://creativecommons.org/licenses/by/4.0/"),
                WIKI_SUMMARY: WIKI_PAGE,
                COMMONS: commons_file("CC BY-SA 4.0"),
            }
        )
        info = curator.fetch(NAME)
        self.assertIsNotNone(info.image)
        self.assertEqual(info.image.url, "https://images.gbif.org/occurrence/1.jpg")
        self.assertEqual(info.image.licence, "CC BY 4.0")
        self.assertFalse(info.image.licence_url_assumed)
        self.assertEqual(info.image.sourceUrl, "https://www.gbif.org/occurrence/987654321")

    def test_gbif_is_skipped_entirely_without_an_exact_name_match(self) -> None:
        curator, upstream = make_curator()
        upstream.serve(
            {
                INAT: EMPTY_RESULTS,
                GBIF_MATCH: NO_GBIF_MATCH,
                WIKI_SUMMARY: {},
            }
        )
        self.assertIsNone(curator.fetch(NAME).image)
        self.assertFalse(upstream.called(GBIF_SEARCH))

    def test_wikipedia_image_is_used_only_when_the_commons_file_licence_allows(self) -> None:
        curator, upstream = make_curator()
        upstream.serve(
            {
                INAT: EMPTY_RESULTS,
                GBIF_MATCH: NO_GBIF_MATCH,
                WIKI_SUMMARY: WIKI_PAGE,
                COMMONS: commons_file("CC BY 2.0"),
            }
        )
        info = curator.fetch(NAME)
        self.assertIsNotNone(info.image)
        # The thumbnail is served (same file, same licence, smaller), and the
        # source link goes to the article a reader can follow.
        self.assertIn("320px-", info.image.url)
        self.assertEqual(info.image.licence, "CC BY 2.0")
        self.assertEqual(info.image.licenceUrl, "https://creativecommons.org/licenses/by/2.0/")
        self.assertEqual(info.image.sourceUrl, "https://en.wikipedia.org/wiki/European_robin")

    def test_a_share_alike_commons_file_is_refused_under_the_default_policy(self) -> None:
        curator, upstream = make_curator()
        upstream.serve(
            {
                INAT: EMPTY_RESULTS,
                GBIF_MATCH: NO_GBIF_MATCH,
                WIKI_SUMMARY: WIKI_PAGE,
                COMMONS: commons_file("CC BY-SA 4.0"),
            }
        )
        info = curator.fetch(NAME)
        self.assertIsNone(info.image)
        # ...but the description still arrives: text and images are licensed
        # independently, and the text credit is structured, not inline.
        self.assertIsNotNone(info.description)

    def test_description_is_clean_text_with_a_structured_source(self) -> None:
        curator, upstream = make_curator()
        upstream.serve(
            {
                INAT: EMPTY_RESULTS,
                GBIF_MATCH: NO_GBIF_MATCH,
                WIKI_SUMMARY: WIKI_PAGE,
                COMMONS: commons_file("CC BY-SA 4.0"),
            }
        )
        info = curator.fetch(NAME)
        self.assertNotIn("(Wikipedia", info.description)
        self.assertEqual(info.description_source["label"], "Wikipedia")
        self.assertEqual(info.description_source["licence"], "CC BY-SA 4.0")
        self.assertEqual(
            info.description_source["sourceUrl"],
            "https://en.wikipedia.org/wiki/European_robin",
        )
        self.assertEqual(info.description_source["approvalReference"], "")

    def test_network_failure_yields_empty_not_an_exception(self) -> None:
        curator, upstream = make_curator()
        upstream.serve({}, raises=httpx.ConnectError("boom"))
        info = curator.fetch(NAME)
        self.assertIsNone(info.image)
        self.assertIsNone(info.description)
        self.assertTrue(any("fetch failed" in note for note in info.notes))

    def test_blank_name_fetches_nothing(self) -> None:
        curator, upstream = make_curator()
        upstream.serve({INAT: inat_photo("cc-by")})
        self.assertIsNone(curator.fetch("   ").image)
        self.assertEqual(upstream.requests, [])


# =============================================================================
# 4. Session rules
# =============================================================================


class CuratorSessionTests(unittest.TestCase):
    def test_a_contact_is_required(self) -> None:
        """The upstream APIs ask callers to identify themselves; refusing to run
        without a contact is the ported equivalent of the proxy's off-switch."""
        with self.assertRaisesRegex(ValueError, "contact"):
            Curator(contact="   ", allowed_licences=ALLOWED)

    def test_truncate_prefers_sentence_then_word_boundaries(self) -> None:
        text = "First sentence. Second sentence follows here."
        self.assertEqual(truncate(text, 20), "First sentence.")
        self.assertTrue(truncate("word " * 30, 24).endswith("…"))


if __name__ == "__main__":
    unittest.main()
