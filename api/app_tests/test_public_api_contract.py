"""The API's real HTTP responses, checked against the front end's Zod contract.

``web/src/lib/api/schemas.ts`` is ``.strict()`` throughout: an extra key is a
rejected response, not a tolerated one, and several schemas carry cross-field
invariants that a shape check alone would miss.  These tests therefore assert
exact key sets and the invariants themselves, against a real publication
database rather than a mock, because the properties being tested are produced by
the ``serve.*`` views and not by this code.

Enabled with ``BRERC_API_INTEGRATION=1`` and a ``DATABASE_URL`` for the
read-only API role.  Skipped otherwise, like the other integration suites.
"""

from __future__ import annotations

import os
import unittest

ENABLED = os.environ.get("BRERC_API_INTEGRATION") == "1"

#: Exact key sets from schemas.ts.  Listed rather than derived so that a change
#: on either side shows up here as a deliberate edit.
PROVENANCE_KEYS = {
    "lastUpdated",
    "recordTotal",
    "sources",
    "coverageCaveats",
    "sensitivityPolicy",
    "attributions",
}
SENSITIVITY_POLICY_KEYS = {"generalisationTiersMetres", "appliesToProtectedTaxa", "note"}
RECORD_PAGE_KEYS = {"publication", "items", "page", "pageSize", "total"}
PUBLICATION_FIELD_KEYS = {"abundance", "place", "recordType", "verification"}
RECORD_REQUIRED_KEYS = {
    "id",
    "scientificName",
    "commonName",
    "gridRef",
    "precisionMetres",
    "place",
    "year",
    "source",
}
RECORD_OPTIONAL_KEYS = {"abundance", "recordType", "verified"}
CELL_DISTRIBUTION_KEYS = {"verificationAvailable", "cells"}
CELL_REQUIRED_KEYS = {"cellId", "precisionMetres", "recordCount"}
SPECIES_PAGE_KEYS = {"items", "page", "pageSize", "total", "facets"}
SPECIES_ITEM_KEYS = {
    "speciesId",
    "slug",
    "scientificName",
    "commonName",
    "group",
    "recordCount",
    "firstYear",
    "lastYear",
    "hasImage",
}
SPECIES_DETAIL_KEYS = {
    "speciesId",
    "slug",
    "scientificName",
    "commonName",
    "group",
    "imagePublication",
    "stats",
}
#: Media keys are .optional() in schemas.ts — absent unless the approved-assets
#: registry covers the species.  Optional means the KEY may be missing; when
#: present the value must be complete, and null is never a substitute for
#: absence (Zod .optional() does not accept null).
SPECIES_DETAIL_OPTIONAL_KEYS = {"description", "descriptionSource", "image"}
SPECIES_IMAGE_KEYS = {
    "url",
    "attributionText",
    "licence",
    "licenceUrl",
    "sourceUrl",
    "approvalReference",
    "alt",
}
DESCRIPTION_SOURCE_REQUIRED_KEYS = {"label", "approvalReference"}
DESCRIPTION_SOURCE_OPTIONAL_KEYS = {"sourceUrl", "licence", "licenceUrl"}
SPECIES_STATS_KEYS = {"recordCount", "yearRange", "verificationAvailable", "verifiedCount"}
SUMMARY_KEYS = {
    "totalRecords",
    "totalSpecies",
    "yearRange",
    "recordsByYear",
    "topGroups",
    "coverageCaveat",
}

#: Mirrors gridRefPrecisionMetres in schemas.ts: two letters then 2, 4 or 6
#: digits, resolving to 10 km, 1 km or 100 m.  Duplicated here on purpose — if
#: the two ever disagree, that is exactly the bug worth catching.
_PRECISION_BY_DIGITS = {2: 10_000, 4: 1_000, 6: 100}


def grid_ref_precision_metres(cell_id: str) -> int | None:
    if len(cell_id) < 3 or not cell_id[:2].isalpha():
        return None
    digits = cell_id[2:]
    if not digits.isdigit():
        return None
    return _PRECISION_BY_DIGITS.get(len(digits))


@unittest.skipUnless(ENABLED, "requires a publication database and the read-only API role")
class TestPublicApiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        cls.client = TestClient(app)

    def test_health_is_reachable_without_touching_data(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"status", "version"})
        self.assertEqual(response.json()["status"], "ok")

    def test_provenance_matches_the_contract_exactly(self) -> None:
        response = self.client.get("/api/meta/provenance")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), PROVENANCE_KEYS)

        self.assertIsInstance(body["recordTotal"], int)
        self.assertGreaterEqual(body["recordTotal"], 0)
        self.assertIsInstance(body["sources"], list)
        self.assertIsInstance(body["coverageCaveats"], list)
        self.assertTrue(all(isinstance(c, str) and c.strip() for c in body["coverageCaveats"]))

        policy = body["sensitivityPolicy"]
        self.assertEqual(set(policy), SENSITIVITY_POLICY_KEYS)
        # Zod pins this to the literal true; anything else fails the schema.
        self.assertIs(policy["appliesToProtectedTaxa"], True)
        self.assertIsInstance(policy["note"], str)
        self.assertTrue(policy["note"].strip())

        tiers = policy["generalisationTiersMetres"]
        self.assertIsInstance(tiers, list)
        self.assertTrue(all(isinstance(t, int) and t > 0 for t in tiers))
        # Measured from the released cells, so they must be sorted and unique.
        self.assertEqual(tiers, sorted(set(tiers)))

        for attribution in body["attributions"]:
            self.assertEqual(set(attribution), {"label", "url", "licence"})
            self.assertTrue(attribution["url"].startswith("https://"))

    def test_generalisation_tiers_cover_every_published_resolution(self) -> None:
        """The tiers must describe this release, not a configured aspiration.

        Both surfaces count.  Cells and records are generalised independently,
        so a release can aggregate cells to 1 km while publishing records at
        100 m; reading only the cells would advertise a tier list that omits a
        resolution the release actually used.
        """
        from app.db import serving_connection

        published = self.client.get("/api/meta/provenance").json()
        with serving_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT precision_metres FROM serve.public_distribution_cell "
                "UNION SELECT DISTINCT precision_metres FROM serve.public_record "
                "ORDER BY precision_metres"
            )
            observed = [int(row["precision_metres"]) for row in cursor.fetchall()]
        self.assertEqual(published["sensitivityPolicy"]["generalisationTiersMetres"], observed)

    def test_no_published_location_is_finer_than_an_advertised_tier(self) -> None:
        """A record must never be more precise than the policy the page states."""
        provenance = self.client.get("/api/meta/provenance").json()
        tiers = provenance["sensitivityPolicy"]["generalisationTiersMetres"]
        rows = self.client.get("/api/records", params={"pageSize": 100}).json()["items"]
        for row in rows:
            self.assertIn(
                row["precisionMetres"],
                tiers,
                "a record is published at a resolution the policy does not declare",
            )

    def test_timestamps_are_iso_8601_and_parse_as_dates(self) -> None:
        """``str()`` on a timestamp yields a space where ISO-8601 needs a "T".

        The schema accepts any string, so a malformed one passes validation and
        fails later in the browser, where ``new Date()`` on a non-ISO string is
        implementation-defined.
        """
        from datetime import datetime

        last_updated = self.client.get("/api/meta/provenance").json()["lastUpdated"]
        self.assertTrue(last_updated, "provenance must state when the data is from")
        self.assertNotIn(" ", last_updated)
        datetime.fromisoformat(last_updated)

    def test_record_total_equals_the_published_basis(self) -> None:
        from app.db import serving_connection

        published = self.client.get("/api/meta/provenance").json()
        with serving_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(record_count), 0) AS total FROM serve.public_species_year"
            )
            observed = int(cursor.fetchone()["total"])
        self.assertEqual(published["recordTotal"], observed)

    def test_records_page_matches_the_contract_and_its_invariants(self) -> None:
        response = self.client.get("/api/records", params={"page": 1, "pageSize": 20})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), RECORD_PAGE_KEYS)

        publication = body["publication"]
        self.assertEqual(set(publication), {"mode", "fields"})
        self.assertIn(publication["mode"], {"aggregates-only", "individual-records"})
        self.assertEqual(set(publication["fields"]), PUBLICATION_FIELD_KEYS)
        self.assertTrue(all(isinstance(v, bool) for v in publication["fields"].values()))

        self.assertGreater(body["page"], 0)
        self.assertGreater(body["pageSize"], 0)
        self.assertGreaterEqual(body["total"], 0)
        self.assertLessEqual(len(body["items"]), body["pageSize"])
        self.assertLessEqual(len(body["items"]), body["total"])

        if publication["mode"] == "aggregates-only":
            # The schema refuses any row at all in this mode.
            self.assertEqual(body["items"], [])
            self.assertEqual(body["total"], 0)

    def test_a_row_never_advertises_a_field_the_release_withheld(self) -> None:
        """The gate the front end relies on, asserted against real rows."""
        body = self.client.get("/api/records", params={"pageSize": 20}).json()
        fields = body["publication"]["fields"]
        capability_of = {
            "abundance": "abundance",
            "recordType": "recordType",
            "verified": "verification",
        }
        for row in body["items"]:
            self.assertEqual(set(row) - RECORD_OPTIONAL_KEYS, RECORD_REQUIRED_KEYS)
            for field, capability in capability_of.items():
                if fields[capability]:
                    self.assertIn(field, row, f"{field} required when {capability} is published")
                else:
                    self.assertNotIn(field, row, f"{field} present while {capability} is withheld")
            # verified is the raw source verdict as text; a boolean would collapse
            # "rejected" and "not yet checked" into one value.
            if "verified" in row and row["verified"] is not None:
                self.assertIsInstance(row["verified"], str)

    def test_page_size_cap_is_enforced_by_the_server(self) -> None:
        from app import config

        response = self.client.get("/api/records", params={"pageSize": config.MAX_PAGE_SIZE + 500})
        # The request validator refuses it outright rather than silently trimming.
        self.assertEqual(response.status_code, 422)

    def test_the_api_session_cannot_write(self) -> None:
        """Negative control on the read-only posture, not just its configuration."""
        import psycopg

        from app.db import serving_connection

        with (
            serving_connection() as connection,
            connection.cursor() as cursor,
            self.assertRaises(psycopg.errors.ReadOnlySqlTransaction),
        ):
            cursor.execute("CREATE TEMP TABLE api_should_not_write (id int)")

    def test_distribution_matches_the_contract_and_sends_no_geometry(self) -> None:
        """Geometry must not cross this boundary.

        The client derives each polygon from the cell id it validated, so the
        shape drawn always matches the identifier.  If the server also sent a
        polygon, a precise one could be labelled with a coarse cell id and the
        map would draw the true location of a generalised record.
        """
        response = self.client.get("/api/distribution/cells")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), CELL_DISTRIBUTION_KEYS)
        self.assertIsInstance(body["verificationAvailable"], bool)

        forbidden = {
            "geom",
            "geometry",
            "coordinates",
            "polygon",
            "lat",
            "lon",
            "latitude",
            "longitude",
            "easting",
            "northing",
        }
        for cell in body["cells"]:
            keys = set(cell)
            self.assertEqual(keys - {"verifiedCount"}, CELL_REQUIRED_KEYS)
            self.assertEqual(keys & forbidden, set(), "geometry must not be published")

            # The identifier and the stated precision must agree, or the client
            # would draw a square of the wrong size for the id it was given.
            derived = grid_ref_precision_metres(cell["cellId"])
            self.assertIsNotNone(derived, f"unparseable cell id {cell['cellId']!r}")
            self.assertEqual(derived, cell["precisionMetres"])
            self.assertGreaterEqual(cell["precisionMetres"], 100)

            if body["verificationAvailable"]:
                self.assertIn("verifiedCount", cell)
                self.assertLessEqual(cell["verifiedCount"], cell["recordCount"])
            else:
                self.assertNotIn("verifiedCount", cell)

    def test_summary_matches_the_contract_and_its_invariants(self) -> None:
        response = self.client.get("/api/summary")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), SUMMARY_KEYS)
        self.assertTrue(body["coverageCaveat"].strip())

        buckets = body["recordsByYear"]
        for bucket in buckets:
            self.assertEqual(set(bucket), {"year", "count"})
            # A zero bucket is refused by the schema; omit the year instead.
            self.assertGreater(bucket["count"], 0)
        self.assertEqual([b["year"] for b in buckets], sorted(b["year"] for b in buckets))

        year_range = body["yearRange"]
        # Null exactly when there are no records — the schema checks both ways.
        self.assertEqual(body["totalRecords"] == 0, year_range is None)
        if year_range is not None:
            self.assertEqual(set(year_range), {"min", "max"})
            self.assertLessEqual(year_range["min"], year_range["max"])
            # The range must be the years that actually carry records.
            self.assertEqual(year_range["min"], buckets[0]["year"])
            self.assertEqual(year_range["max"], buckets[-1]["year"])

        for group in body["topGroups"]:
            self.assertEqual(set(group), {"group", "count"})
            self.assertTrue(group["group"].strip())

    def test_summary_year_buckets_reconcile_with_the_record_total(self) -> None:
        """The chart and the headline number must describe the same data."""
        body = self.client.get("/api/summary").json()
        self.assertEqual(sum(b["count"] for b in body["recordsByYear"]), body["totalRecords"])

    def test_taxon_group_is_absent_rather_than_invented(self) -> None:
        """publication.public_species.taxon_group is CHECK-constrained to NULL.

        Until taxa_nb is mapped into the safe projection and approval-bound, the
        release publishes no taxonomic grouping.  Reporting an empty list is the
        honest answer; a placeholder group would put a taxonomic claim on a
        public page that no approved contract supports.
        """
        from app.db import serving_connection

        self.assertEqual(self.client.get("/api/summary").json()["topGroups"], [])
        with serving_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS n FROM serve.public_species WHERE taxon_group IS NOT NULL"
            )
            self.assertEqual(cursor.fetchone()["n"], 0)

    def test_species_page_matches_the_contract_and_its_invariants(self) -> None:
        from app.slugs import SLUG_PATTERN

        response = self.client.get("/api/species")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), SPECIES_PAGE_KEYS)
        self.assertEqual(set(body["facets"]), {"groups"})

        facet_values = set()
        for facet in body["facets"]["groups"]:
            self.assertEqual(set(facet), {"value", "label", "speciesCount"})
            facet_values.add(facet["value"])
        self.assertEqual(len(facet_values), len(body["facets"]["groups"]), "facets must be unique")

        self.assertLessEqual(len(body["items"]), body["pageSize"])
        self.assertLessEqual(len(body["items"]), body["total"])

        for item in body["items"]:
            self.assertEqual(set(item), SPECIES_ITEM_KEYS)
            self.assertRegex(item["slug"], SLUG_PATTERN)
            # A species with no records must carry no year range, and one with
            # records must carry both years — the schema checks both directions.
            has_years = item["firstYear"] is not None and item["lastYear"] is not None
            self.assertEqual(item["recordCount"] == 0, not has_years)
            if has_years:
                self.assertLessEqual(item["firstYear"], item["lastYear"])
            # A published group must appear in the authoritative facet list.
            if item["group"] is not None:
                self.assertIn(item["group"], facet_values)

        self.assertEqual(
            len({i["speciesId"] for i in body["items"]}), len(body["items"]), "ids must be unique"
        )
        self.assertEqual(
            len({i["slug"] for i in body["items"]}), len(body["items"]), "slugs must be unique"
        )

    def test_species_group_is_null_rather_than_invented(self) -> None:
        """The release publishes no grouping, and says so.

        taxa_nb is unbounded free text and public_species.taxon_group is
        CHECK-constrained to NULL until it is mapped and approval-bound.  Null
        is the honest report; a placeholder would be an unapproved taxonomic
        claim, and hiding ungrouped species would silently lose data.
        """
        items = self.client.get("/api/species").json()["items"]
        self.assertTrue(items, "the fixture must publish at least one species")
        for item in items:
            self.assertIsNone(item["group"])

    def test_species_detail_matches_the_contract(self) -> None:
        """Key set, media mode and stats invariants, in whichever mode is live.

        The media assertions follow the DEPLOYMENT'S declared capability, like
        the record assertions above follow the release's.  Without
        SPECIES_ASSETS_FILE — CI's state — every species is ``fallback-only``
        and carries no media keys at all.  With an approved registry, a covered
        species must publish the complete image contract.  Both branches are
        asserted in full so this test also holds against a deployment that
        serves approved assets.
        """
        listing = self.client.get("/api/species").json()["items"]
        species_id = listing[0]["speciesId"]
        body = self.client.get(f"/api/species/{species_id}").json()
        self.assertEqual(set(body) - SPECIES_DETAIL_OPTIONAL_KEYS, SPECIES_DETAIL_KEYS)
        self.assertEqual(body["speciesId"], species_id)
        self.assertEqual(body["slug"], listing[0]["slug"], "slugs must agree across endpoints")

        # Optional keys are omitted, never null: schemas.ts marks them
        # .optional(), and Zod's .optional() rejects an explicit null.
        for key in SPECIES_DETAIL_OPTIONAL_KEYS & set(body):
            self.assertIsNotNone(body[key], f"{key} must be omitted rather than null")

        # The two endpoints must tell the same story about this species.
        self.assertIn(body["imagePublication"], {"fallback-only", "approved-assets"})
        self.assertEqual(
            body["imagePublication"] == "approved-assets",
            listing[0]["hasImage"],
            "the listing's hasImage flag and the detail's publication mode disagree",
        )

        if body["imagePublication"] == "fallback-only":
            # fallback-only forbids an image; the front end shows its labelled
            # placeholder.  (A description may still be published.)
            self.assertNotIn("image", body)
        else:
            # approved-assets requires the whole image: url, deed link, source
            # link (all https), attribution, human approval reference, alt text.
            image = body["image"]
            self.assertEqual(set(image), SPECIES_IMAGE_KEYS)
            for field in ("url", "licenceUrl", "sourceUrl"):
                self.assertTrue(image[field].startswith("https://"), f"{field} must be https")
            for field in SPECIES_IMAGE_KEYS - {"url", "licenceUrl", "sourceUrl"}:
                self.assertTrue(image[field].strip(), f"{field} must be non-empty text")

        # description and descriptionSource travel strictly together, and the
        # source's own optional fields follow the same omitted-never-null rule.
        self.assertEqual(
            "description" in body,
            "descriptionSource" in body,
            "description and descriptionSource must be published together",
        )
        if "descriptionSource" in body:
            self.assertTrue(body["description"].strip())
            source = body["descriptionSource"]
            self.assertEqual(
                set(source) - DESCRIPTION_SOURCE_OPTIONAL_KEYS, DESCRIPTION_SOURCE_REQUIRED_KEYS
            )
            self.assertNotIn(None, source.values(), "source fields are omitted, not null")
            if "licenceUrl" in source:
                self.assertIn("licence", source, "a deed link needs licence text to label it")

        stats = body["stats"]
        self.assertEqual(set(stats), SPECIES_STATS_KEYS)
        # Null exactly when verification is unavailable: a zero would assert
        # "none verified" where the truth is "not published".
        self.assertEqual(stats["verificationAvailable"], stats["verifiedCount"] is not None)
        if stats["verifiedCount"] is not None:
            self.assertLessEqual(stats["verifiedCount"], stats["recordCount"])
        self.assertEqual(stats["recordCount"] == 0, stats["yearRange"] is None)
        if stats["yearRange"] is not None:
            self.assertEqual(len(stats["yearRange"]), 2)
            self.assertLessEqual(stats["yearRange"][0], stats["yearRange"][1])

    def test_a_missing_species_is_404_not_an_empty_body(self) -> None:
        self.assertEqual(self.client.get("/api/species/NO-SUCH-SPECIES").status_code, 404)

    def test_query_parameter_names_match_what_the_client_sends(self) -> None:
        """The browser sends ?species=, ?q= and ?group=.

        Response shapes are covered elsewhere; only a live request catches a
        parameter the server silently ignores. An unknown filter would return
        the unfiltered set, which looks like working software.

        The record assertions follow the release's DECLARED capability. An
        aggregates-only release publishes no individual records, so an empty
        page is the contract for every species — matched and missing are
        rightly identical, and no content can reveal an ignored parameter
        there. What is pinned in that mode is that the emptiness is the
        declared policy, not a filter that happened to match nothing. The
        ?species= name keeps its full matched/ignored force on
        /api/distribution/cells, which every release publishes rows for.
        (As written before, this test assumed an individual-records release —
        the environment it was authored against — and could never pass
        against the loader's approved test policy, which sets
        publish_individual_records=False.)
        """
        species_id = self.client.get("/api/species").json()["items"][0]["speciesId"]
        for path in ("/api/records", "/api/distribution/cells"):
            with self.subTest(path=path):
                matched = self.client.get(path, params={"species": species_id})
                missing = self.client.get(path, params={"species": "NO-SUCH-SPECIES"})
                self.assertEqual(matched.status_code, 200)
                self.assertEqual(missing.status_code, 200)
                key = "items" if path.endswith("records") else "cells"
                if key == "items" and matched.json()["publication"]["mode"] == "aggregates-only":
                    self.assertEqual(len(matched.json()[key]), 0, "aggregates-only leaked a row")
                    self.assertEqual(len(missing.json()[key]), 0, "aggregates-only leaked a row")
                    continue
                self.assertGreater(len(matched.json()[key]), 0, "the filter matched nothing")
                self.assertEqual(len(missing.json()[key]), 0, "the filter was ignored")

        # `group` must be accepted even while no release publishes groups.
        grouped = self.client.get("/api/species", params={"group": "beetle"})
        self.assertEqual(grouped.status_code, 200)
        self.assertEqual(grouped.json()["total"], 0)

    def test_search_wildcards_are_escaped_rather_than_executed(self) -> None:
        """A search box must not become a pattern the caller controls."""
        everything = self.client.get("/api/species").json()["total"]
        self.assertGreater(everything, 0)
        for pattern in ("%", "_", "%%", "\\"):
            with self.subTest(pattern=pattern):
                matched = self.client.get("/api/species", params={"q": pattern}).json()["total"]
                self.assertEqual(matched, 0, f"{pattern!r} was treated as a wildcard")

    def test_only_reviewed_sort_orders_are_accepted(self) -> None:
        for sort in ("name-asc", "scientific-name-asc", "records-desc", "latest-record-desc"):
            with self.subTest(sort=sort):
                self.assertEqual(
                    self.client.get("/api/species", params={"sort": sort}).status_code, 200
                )
        # An unknown value selects no clause at all rather than being interpolated.
        self.assertEqual(
            self.client.get(
                "/api/species", params={"sort": "total_records; DROP TABLE"}
            ).status_code,
            422,
        )

    def test_base_tables_are_not_reachable_through_the_query_guard(self) -> None:
        from app.db import ServingRelationError, assert_serving_relation

        for relation in (
            "loader_control.source_disposition",
            "publication.public_record",
            "loader_stage.disposition_delta",
            "serve.etl_job_status",
        ):
            with self.subTest(relation=relation), self.assertRaises(ServingRelationError):
                assert_serving_relation(relation)


if __name__ == "__main__":
    unittest.main()
