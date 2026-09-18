"""
B8 tests — the species image/description proxy and its licence gate.

WHY THESE MATTER MORE THAN MOST
Showing an image we are not licensed to show is a legal problem for BRERC (and
Bristol City Council), not a cosmetic bug, and it is the kind of mistake that
looks fine on screen. So the rule is asserted directly here: unless a permitted
licence AND an attribution are both confirmed, there must be no image.

NO NETWORK. Every test swaps in a fake HTTP transport, so the suite is fast,
offline, deterministic, and never sends traffic to iNaturalist, GBIF or
Wikipedia. `_new_client` is the single seam that makes that possible.
"""

import httpx
import pytest

from fastapi.testclient import TestClient

from app import config, species_info
from app.main import app
from tests.conftest import needs_b6_schema

client = TestClient(app)

NAME = "Erithacus rubecula"


# =============================================================================
# Fake upstream APIs
# =============================================================================

INAT = "api.inaturalist.org/v1/taxa"
GBIF_MATCH = "api.gbif.org/v1/species/match"
GBIF_SEARCH = "api.gbif.org/v1/occurrence/search"
WIKI_SUMMARY = "en.wikipedia.org/api/rest_v1/page/summary/"
COMMONS = "en.wikipedia.org/w/api.php"


def inat_photo(licence, attribution="(c) Jane Doe, some rights reserved", name=NAME):
    return {
        "results": [
            {
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
                "media": [
                    {
                        "type": "StillImage",
                        "identifier": "https://images.gbif.org/occurrence/1.jpg",
                        "license": licence,
                        "rightsHolder": rights_holder,
                    }
                ]
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


@pytest.fixture
def proxy(monkeypatch, tmp_path):
    """
    Switch the proxy on, point its cache at a throwaway file, and hand back a
    small helper for wiring up fake upstream responses.

    Usage:
        proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})
        info = species_info.get_species_info(NAME)
        assert proxy.called(GBIF_MATCH) is False
    """
    monkeypatch.setattr(config, "SPECIES_INFO_ENABLED", True)
    monkeypatch.setattr(config, "SPECIES_INFO_CONTACT", "dashboard@example.org")
    monkeypatch.setattr(config, "SPECIES_INFO_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(config, "SPECIES_INFO_CACHE_PATH", str(tmp_path / "cache.sqlite3"))
    species_info.reset_cache()

    class Proxy:
        def __init__(self):
            self.requests: list[str] = []

        def serve(self, routes: dict, raises: Exception | None = None):
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
            monkeypatch.setattr(
                species_info,
                "_new_client",
                lambda: httpx.Client(transport=transport),
            )

        def called(self, prefix: str) -> bool:
            return any(target.startswith(prefix) for target in self.requests)

    helper = Proxy()
    yield helper
    species_info.reset_cache()


# =============================================================================
# 1. The licence normaliser — one canonical answer from three different wordings
# =============================================================================

@pytest.mark.parametrize(
    "raw, expected",
    [
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
        # Wikimedia Commons sends human-readable labels.
        ("CC BY-SA 4.0", "cc-by-sa"),
        ("CC0", "cc0"),
        ("Public domain", "pd"),
        # Anything we cannot positively identify must come back as None, which is
        # always refused. We never assume a photo is open.
        ("All rights reserved", None),
        ("UNSPECIFIED", None),
        ("http://rs.tdwg.org/dwc/terms/UnknownLicense", None),
        ("", None),
        (None, None),
    ],
)
def test_licence_normaliser(raw, expected):
    assert species_info.normalise_licence(raw) == expected


def test_nc_licence_is_not_mistaken_for_plain_cc_by():
    """
    The subtle one: "cc-by-nc" starts with "cc-by". If the check were a simple
    prefix or substring test, every NonCommercial photo would be waved through.
    """
    assert species_info.normalise_licence("cc-by-nc") == "cc-by-nc"
    assert species_info.licence_is_allowed("cc-by") is True
    assert species_info.licence_is_allowed("cc-by-nc") is False


def test_a_hostname_containing_by_is_not_read_as_a_licence():
    assert species_info.normalise_licence("https://photos.birdsby.org/robin.jpg") is None


# =============================================================================
# 2. The gate itself — all three conditions are required
# =============================================================================

GOOD_URL = "https://example.org/robin.jpg"


def test_vet_image_accepts_a_properly_licensed_credited_photo():
    image = species_info.vet_image(GOOD_URL, "cc-by", "(c) Jane Doe")
    assert image is not None
    assert image.url == GOOD_URL
    assert image.licence == "CC BY"          # display-ready label, not a raw code
    assert image.attribution == "(c) Jane Doe"


@pytest.mark.parametrize(
    "url, licence, attribution, why",
    [
        (GOOD_URL, "cc-by-nc", "(c) Jane Doe", "NonCommercial is not on the allow-list"),
        (GOOD_URL, "cc-by-sa", "(c) Jane Doe", "ShareAlike is not allowed by default"),
        (GOOD_URL, None, "(c) Jane Doe", "no licence stated = all rights reserved"),
        (GOOD_URL, "", "(c) Jane Doe", "empty licence"),
        (GOOD_URL, "All rights reserved", "(c) Jane Doe", "explicitly not reusable"),
        (GOOD_URL, "cc-by", None, "CC BY requires a credit and we have none"),
        (GOOD_URL, "cc-by", "   ", "whitespace is not a credit"),
        (GOOD_URL, "cc-by", "<em> </em>", "empty once the html is stripped"),
        ("http://example.org/robin.jpg", "cc0", "(c) JD", "plain http = mixed content"),
        ("/relative/robin.jpg", "cc0", "(c) JD", "not an absolute url"),
        (None, "cc0", "(c) JD", "no url at all"),
    ],
)
def test_vet_image_fails_closed(url, licence, attribution, why):
    assert species_info.vet_image(url, licence, attribution) is None, f"should refuse: {why}"


def test_allow_list_is_configurable_for_share_alike(monkeypatch):
    """BRERC can widen the rule in one place if their legal position allows it."""
    assert species_info.vet_image(GOOD_URL, "CC BY-SA 4.0", "(c) JD") is None
    monkeypatch.setattr(
        config, "SPECIES_IMAGE_ALLOWED_LICENCES", {"cc0", "pd", "cc-by", "cc-by-sa"}
    )
    image = species_info.vet_image(GOOD_URL, "CC BY-SA 4.0", "(c) JD")
    assert image is not None and image.licence == "CC BY-SA"


# =============================================================================
# 3. Switched off unless deliberately configured
# =============================================================================

def test_proxy_is_off_by_default(monkeypatch):
    """
    A fresh checkout must not call third parties until someone opts in.

    This asserts the DEFAULT, not whatever happens to be in the developer's
    api/.env — otherwise the suite would turn red on the machine of anyone who
    switched the feature on locally, which is the one machine where it matters.
    """
    monkeypatch.delenv("SPECIES_INFO_ENABLED", raising=False)
    assert config._env_flag("SPECIES_INFO_ENABLED", False) is False

    monkeypatch.setattr(config, "SPECIES_INFO_ENABLED", False)
    assert species_info.inactive_reason() is not None
    assert species_info.get_species_info(NAME) == species_info.EMPTY


def test_enabled_without_a_contact_address_stays_off(monkeypatch):
    """These APIs require a real User-Agent, so half-configured means off."""
    monkeypatch.setattr(config, "SPECIES_INFO_ENABLED", True)
    monkeypatch.setattr(config, "SPECIES_INFO_CONTACT", "")
    assert "SPECIES_INFO_CONTACT" in species_info.inactive_reason()


def test_off_proxy_makes_no_http_calls(proxy, monkeypatch):
    proxy.serve({INAT: inat_photo("cc0"), WIKI_SUMMARY: WIKI_PAGE})
    monkeypatch.setattr(config, "SPECIES_INFO_ENABLED", False)

    assert species_info.get_species_info(NAME) == species_info.EMPTY
    assert proxy.requests == [], "the proxy is off but it still called out"


# =============================================================================
# 4. The cascade: iNaturalist -> GBIF -> Wikipedia
# =============================================================================

def test_inaturalist_is_used_first_and_stops_the_cascade(proxy):
    proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})

    info = species_info.get_species_info(NAME)

    assert info.image is not None
    assert "inaturalist" in info.image.url
    assert info.image.licence == "CC BY"
    assert not proxy.called(GBIF_MATCH), "GBIF was called even though iNaturalist answered"


def test_unlicensed_inaturalist_photo_falls_through_to_gbif(proxy):
    """
    The important cascade case: iNaturalist HAS a photo, but it is NonCommercial.
    We must skip it rather than display it, and try the next source.
    """
    proxy.serve(
        {
            INAT: inat_photo("cc-by-nc"),
            GBIF_MATCH: {"matchType": "EXACT", "usageKey": 2492348},
            GBIF_SEARCH: gbif_media("http://creativecommons.org/publicdomain/zero/1.0/"),
            WIKI_SUMMARY: WIKI_PAGE,
        }
    )

    info = species_info.get_species_info(NAME)

    assert info.image is not None
    assert "gbif" in info.image.url, "should have skipped the NC photo and used GBIF"
    assert info.image.licence == "CC0"


def test_photo_of_the_wrong_taxon_is_ignored(proxy):
    """
    A search endpoint returns near-misses. A correctly-licensed photo of the wrong
    bird is still wrong, and the licence check would not catch it.
    """
    proxy.serve(
        {
            INAT: inat_photo("cc0", name="Erithacus akahige"),  # a different species
            GBIF_MATCH: NO_GBIF_MATCH,
            WIKI_SUMMARY: WIKI_PAGE,
            COMMONS: commons_file("CC BY-SA 4.0"),
        }
    )

    assert species_info.get_species_info(NAME).image is None


def test_gbif_is_not_trusted_without_an_exact_name_match(proxy):
    proxy.serve({INAT: EMPTY_RESULTS, GBIF_MATCH: NO_GBIF_MATCH, WIKI_SUMMARY: WIKI_PAGE})

    species_info.get_species_info(NAME)

    assert not proxy.called(GBIF_SEARCH), "fuzzy match should stop before fetching media"


def test_wikipedia_lead_image_licence_is_resolved_on_commons(proxy, monkeypatch):
    """
    A Wikipedia article is CC BY-SA but its lead photo has its own, separate
    licence — so we must look the FILE up on Commons rather than assume.
    Here the file is CC BY-SA, which the default allow-list refuses.
    """
    proxy.serve(
        {
            INAT: EMPTY_RESULTS,
            GBIF_MATCH: NO_GBIF_MATCH,
            WIKI_SUMMARY: WIKI_PAGE,
            COMMONS: commons_file("CC BY-SA 4.0"),
        }
    )

    assert species_info.get_species_info(NAME).image is None
    assert proxy.called(COMMONS), "the file's own licence was never checked"

    # Widen the allow-list and the same file becomes usable.
    monkeypatch.setattr(
        config, "SPECIES_IMAGE_ALLOWED_LICENCES", {"cc0", "pd", "cc-by", "cc-by-sa"}
    )
    species_info.reset_cache()
    image = species_info.get_species_info(NAME).image
    assert image is not None
    assert "320px" in image.url, "should serve the thumbnail, not the full-size file"
    assert image.attribution == "Jane Doe", "html should be stripped from the credit"


# =============================================================================
# 5. Description — CC BY-SA, so it must carry its credit and link back
# =============================================================================

def test_description_credits_wikipedia_and_links_back(proxy):
    proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})

    description = species_info.get_species_info(NAME).description

    assert description is not None
    assert description.startswith("The European robin")
    assert "CC BY-SA" in description
    assert "https://en.wikipedia.org/wiki/European_robin" in description


def test_description_is_dropped_when_there_is_no_link_to_credit(proxy):
    """No link back means we cannot meet CC BY-SA, so we publish nothing."""
    proxy.serve(
        {
            INAT: inat_photo("cc-by"),
            WIKI_SUMMARY: {"type": "standard", "extract": "Some text.", "content_urls": {}},
        }
    )
    assert species_info.get_species_info(NAME).description is None


def test_disambiguation_pages_are_not_used_as_descriptions(proxy):
    proxy.serve(
        {
            INAT: inat_photo("cc-by"),
            WIKI_SUMMARY: {"type": "disambiguation", "extract": "May refer to..."},
        }
    )
    assert species_info.get_species_info(NAME).description is None


def test_long_description_is_truncated(proxy, monkeypatch):
    monkeypatch.setattr(config, "SPECIES_INFO_DESCRIPTION_MAX_CHARS", 40)
    proxy.serve({INAT: EMPTY_RESULTS, GBIF_MATCH: NO_GBIF_MATCH, WIKI_SUMMARY: WIKI_PAGE})

    description = species_info.get_species_info(NAME).description

    # The credit is appended after truncation, so only the article text is cut.
    article_text = description.split(" (Wikipedia,")[0]
    assert len(article_text) <= 41


# =============================================================================
# 6. Caching — the rule is "never hot-call a third party per page view"
# =============================================================================

def test_second_lookup_is_served_from_cache(proxy):
    proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})

    first = species_info.get_species_info(NAME)
    calls_after_first = len(proxy.requests)
    second = species_info.get_species_info(NAME)

    assert calls_after_first > 0
    assert len(proxy.requests) == calls_after_first, "the second call went out again"
    assert second.image == first.image
    assert second.description == first.description


def test_cache_survives_a_restart(proxy):
    """
    The cache is a small SQLite file, not just memory, so a redeploy does not
    re-fetch every species. Clearing the in-memory layer simulates a restart.
    """
    proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})
    species_info.get_species_info(NAME)
    calls = len(proxy.requests)

    species_info._memory.clear()          # a fresh worker process
    info = species_info.get_species_info(NAME)

    assert info.image is not None, "answer was lost when the process restarted"
    assert len(proxy.requests) == calls, "cache file was not read back"


def test_cache_lookup_never_calls_out(proxy):
    proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})

    assert species_info.get_cached_species_info(NAME) is None  # cold, no fetch
    assert proxy.requests == []

    species_info.get_species_info(NAME)
    assert species_info.get_cached_species_info(NAME).image is not None


def test_names_with_cached_image_is_batched_and_cache_only(proxy):
    """Backs `hasImage` on the species LIST without any outbound traffic."""
    proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})
    species_info.get_species_info(NAME)
    calls = len(proxy.requests)

    found = species_info.names_with_cached_image([NAME, "Bufo bufo", "Lutra lutra"])

    assert found == {NAME}
    assert len(proxy.requests) == calls, "the list lookup made network calls"


# =============================================================================
# 7. An upstream problem must never break the page
# =============================================================================

def test_upstream_failure_returns_no_image_not_an_error(proxy):
    proxy.serve({}, raises=httpx.ConnectError("upstream down"))

    info = species_info.get_species_info(NAME)  # must not raise

    assert info.image is None and info.description is None


def test_upstream_failure_is_not_retried_on_every_request(proxy):
    proxy.serve({}, raises=httpx.ConnectError("upstream down"))
    species_info.get_species_info(NAME)
    calls = len(proxy.requests)

    species_info.get_species_info(NAME)

    assert len(proxy.requests) == calls, "an outage is hammering the upstream API"


def test_nonsense_payload_is_handled(proxy):
    proxy.serve({INAT: {"results": "not-a-list"}, WIKI_SUMMARY: WIKI_PAGE})
    assert species_info.get_species_info(NAME).image is None


# =============================================================================
# 8. Through the actual endpoints
# =============================================================================

@needs_b6_schema
def test_species_detail_returns_200_with_no_image_when_proxy_is_off(monkeypatch):
    """The default deployment must still serve a complete, valid detail page."""
    # Forced off explicitly, so this holds whatever the local api/.env says.
    monkeypatch.setattr(config, "SPECIES_INFO_ENABLED", False)

    listing = client.get("/api/species").json()
    species_id = listing["items"][0]["speciesId"]

    response = client.get(f"/api/species/{species_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["image"] is None
    assert body["description"] is None
    assert body["recordCount"] > 0, "stats must be real even with no picture"


@needs_b6_schema
def test_species_detail_serves_a_licensed_image_when_enabled(proxy):
    proxy.serve({INAT: inat_photo("cc0", attribution="Jane Doe"), WIKI_SUMMARY: WIKI_PAGE})

    listing = client.get("/api/species").json()
    scientific_name = listing["items"][0]["scientificName"]
    species_id = listing["items"][0]["speciesId"]

    body = client.get(f"/api/species/{species_id}").json()

    assert body["scientificName"] == scientific_name
    assert body["image"] is not None
    # Licence and attribution travel WITH the url — the front end needs both to
    # display the required credit.
    assert set(body["image"]) == {"url", "licence", "attribution"}
    assert body["image"]["licence"] == "CC0"
    assert body["image"]["attribution"] == "Jane Doe"


@needs_b6_schema
def test_species_list_reports_has_image_once_the_image_is_cached(proxy):
    """
    `hasImage` on the list must agree with what the detail endpoint will actually
    serve, or the front end hides a picture it has.
    """
    listing = client.get("/api/species").json()
    first = listing["items"][0]
    assert first["hasImage"] is False, "sample data has no curated images"

    proxy.serve({INAT: inat_photo("cc-by"), WIKI_SUMMARY: WIKI_PAGE})
    species_info.get_species_info(first["scientificName"])

    refreshed = client.get("/api/species").json()["items"]
    updated = next(item for item in refreshed if item["speciesId"] == first["speciesId"])
    assert updated["hasImage"] is True
