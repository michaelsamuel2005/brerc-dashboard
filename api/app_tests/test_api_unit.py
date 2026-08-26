"""Fast, database-independent tests for the public publication API.

The scripted connection records every SQL statement and parameter sequence.
That makes the security properties observable without weakening production
code with a mock adapter: only fixed ``serve.*`` statements may execute and
every request value must travel separately as a bound parameter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import db
from app.models import (
    PublicationFields,
    RecordPage,
    RecordPublication,
    RecordRow,
)
from app.release import ActiveRelease, load_active_release
from app.routers import distribution, records, species, summary
from app.slugs import SLUG_PATTERN, slugify, species_slug


class ScriptedCursor:
    def __init__(self, connection: ScriptedConnection) -> None:
        self.connection = connection
        self.response: object = None

    def __enter__(self) -> ScriptedCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, parameters: object = None) -> None:
        self.connection.transcript.append((str(query), parameters))
        if not self.connection.responses:
            raise AssertionError(f"unexpected SQL execution: {query}")
        self.response = self.connection.responses.pop(0)

    def fetchone(self) -> dict | None:
        if self.response is None:
            return None
        if isinstance(self.response, list):
            return self.response[0] if self.response else None
        assert isinstance(self.response, dict)
        return self.response

    def fetchall(self) -> list[dict]:
        if self.response is None:
            return []
        if isinstance(self.response, list):
            return self.response
        assert isinstance(self.response, dict)
        return [self.response]


class ScriptedConnection:
    def __init__(self, responses: list[object] | None = None) -> None:
        self.responses = list(responses or [])
        self.transcript: list[tuple[str, object]] = []
        self.rollback_called = False
        self.close_called = False

    def cursor(self) -> ScriptedCursor:
        return ScriptedCursor(self)

    def rollback(self) -> None:
        self.rollback_called = True

    def close(self) -> None:
        self.close_called = True


@contextmanager
def _yield_connection(connection: ScriptedConnection) -> Iterator[ScriptedConnection]:
    yield connection


def _release(**overrides: object) -> ActiveRelease:
    values: dict[str, object] = {
        "release_id": "00000000-0000-0000-0000-000000000001",
        "published_at": "2026-08-26T12:00:00+00:00",
        "source_data_as_of": "2026-08-25T00:00:00+00:00",
        "publication_policy_version": "policy-v1",
        "dataset_version": "dataset-v1",
        "source_label": "BRERC",
        "verification_available": True,
        "individual_records_available": True,
        "record_verification_available": True,
        "place_available": True,
        "abundance_available": True,
        "record_type_available": True,
    }
    values.update(overrides)
    return ActiveRelease(**values)  # type: ignore[arg-type]


def _patch_router(module, connection: ScriptedConnection, release: ActiveRelease):
    return (
        patch.object(module, "serving_connection", return_value=_yield_connection(connection)),
        patch.object(module, "load_active_release", return_value=release),
    )


class TestDatabaseBoundary:
    def test_only_public_serving_views_are_allow_listed(self) -> None:
        for relation in db.SERVING_RELATIONS:
            assert db.assert_serving_relation(relation) == relation

        for relation in (
            "publication.public_record",
            "loader_control.source_disposition",
            "serve.etl_job_status",
            "serve.public_record; SELECT 1",
        ):
            with pytest.raises(db.ServingRelationError):
                db.assert_serving_relation(relation)

    def test_serving_connection_verifies_and_closes_a_read_only_session(self) -> None:
        connection = ScriptedConnection([{"read_only": "on", "can_write_all": False}])
        with (
            patch.object(db, "get_connection", return_value=connection),
            db.serving_connection() as yielded,
        ):
            assert yielded is connection

        assert connection.rollback_called
        assert connection.close_called
        assert "transaction_read_only" in connection.transcript[0][0]

    def test_serving_connection_rejects_a_write_capable_role_before_yield(self) -> None:
        connection = ScriptedConnection([{"read_only": "on", "can_write_all": True}])
        with (
            patch.object(db, "get_connection", return_value=connection),
            pytest.raises(RuntimeError, match="not read-only"),
            db.serving_connection(),
        ):
            raise AssertionError("a writable connection was yielded")

        assert connection.rollback_called
        assert connection.close_called

    def test_credential_reader_never_falls_back_to_destination(self) -> None:
        with patch.object(
            db,
            "get_config",
            return_value={
                "destination": {"user": "etl_writer", "password": "secret"},
                "api_readonly": {"user": "reader", "password": "read-secret"},
            },
        ):
            assert db._get_api_readonly() == {
                "user": "reader",
                "password": "read-secret",
            }


class TestReleaseSelection:
    def test_exactly_one_strict_capability_row_is_required(self) -> None:
        row = {
            "release_id": "00000000-0000-0000-0000-000000000001",
            "published_at": None,
            "source_data_as_of": None,
            "publication_policy_version": "v1",
            "dataset_version": "d1",
            "public_source_label": "BRERC",
            "verification_available": True,
            "individual_records_available": False,
            "record_verification_available": False,
            "place_available": False,
            "abundance_available": False,
            "record_type_available": False,
        }
        release = load_active_release(ScriptedConnection([[row]]))
        assert release.mode == "aggregates-only"
        assert release.source_label == "BRERC"

    @pytest.mark.parametrize("rows", [[], [{"release_id": "one"}, {"release_id": "two"}]])
    def test_missing_or_ambiguous_release_is_unavailable(self, rows: list[dict]) -> None:
        with pytest.raises(HTTPException) as error:
            load_active_release(ScriptedConnection([rows]))
        assert error.value.status_code == 503

    def test_non_boolean_capability_is_unavailable(self) -> None:
        row = {
            "release_id": "release",
            "published_at": None,
            "source_data_as_of": None,
            "publication_policy_version": None,
            "dataset_version": None,
            "public_source_label": None,
            "verification_available": 1,
            "individual_records_available": False,
            "record_verification_available": False,
            "place_available": False,
            "abundance_available": False,
            "record_type_available": False,
        }
        with pytest.raises(HTTPException) as error:
            load_active_release(ScriptedConnection([[row]]))
        assert error.value.status_code == 503


class TestSummary:
    def test_species_filter_is_bound_and_changes_all_summary_queries(self) -> None:
        species_id = "S-1' OR TRUE --"
        connection = ScriptedConnection(
            [
                {"species_exists": True},
                {"total_records": 3},
                {"total_species": 1},
                [
                    {"record_year": 2020, "record_count": 1},
                    {"record_year": 2021, "record_count": 2},
                ],
            ]
        )
        release = _release()
        serving_patch, release_patch = _patch_router(summary, connection, release)
        with serving_patch, release_patch:
            result = summary.summary(species=species_id)

        assert result.totalRecords == 3
        assert result.totalSpecies == 1
        assert result.yearRange is not None
        assert (result.yearRange.min, result.yearRange.max) == (2020, 2021)
        assert len(connection.transcript) == 4
        for query, parameters in connection.transcript:
            assert species_id not in query
            assert species_id in parameters

    def test_unknown_species_is_404_before_aggregation(self) -> None:
        connection = ScriptedConnection([{"species_exists": False}])
        serving_patch, release_patch = _patch_router(summary, connection, _release())
        with serving_patch, release_patch, pytest.raises(HTTPException) as error:
            summary.summary(species="NO-SUCH-SPECIES")

        assert error.value.status_code == 404
        assert len(connection.transcript) == 1


class TestRecords:
    def test_unscoped_records_are_empty_without_querying_record_rows(self) -> None:
        connection = ScriptedConnection()
        serving_patch, release_patch = _patch_router(records, connection, _release())
        with serving_patch, release_patch:
            result = records.list_records(page=1, pageSize=20, species=None, year=None)

        assert result.items == []
        assert result.total == 0
        assert connection.transcript == []

    def test_aggregate_only_release_is_empty_even_with_a_species(self) -> None:
        connection = ScriptedConnection()
        release = _release(
            individual_records_available=False,
            record_verification_available=False,
            place_available=False,
            abundance_available=False,
            record_type_available=False,
        )
        serving_patch, release_patch = _patch_router(records, connection, release)
        with serving_patch, release_patch:
            result = records.list_records(
                page=1,
                pageSize=20,
                species="S-1",
                year=2024,
            )

        assert result.publication.mode == "aggregates-only"
        assert result.items == []
        assert result.total == 0
        assert connection.transcript == []

    def test_year_and_species_filters_are_bound_to_rows_and_count(self) -> None:
        species_id = "S-1' OR TRUE --"
        connection = ScriptedConnection(
            [
                [
                    {
                        "public_record_id": "record-1",
                        "scientific_name": "Erinaceus europaeus",
                        "common_name": "West European hedgehog",
                        "grid_ref": "ST5873",
                        "precision_metres": 1000,
                        "place": "Bristol",
                        "record_year": 2024,
                        "abundance": "1",
                        "record_type": "Field record",
                        "verified_status": "Accepted",
                        "source_label": "BRERC",
                    }
                ],
                {"total": 1},
            ]
        )
        serving_patch, release_patch = _patch_router(records, connection, _release())
        with serving_patch, release_patch:
            result = records.list_records(
                page=2,
                pageSize=10,
                species=species_id,
                year=2024,
            )

        assert result.total == 1
        assert result.items[0].year == 2024
        assert connection.transcript[0][1] == [species_id, 2024, 2024, 10, 10]
        assert connection.transcript[1][1] == [species_id, 2024, 2024]
        for query, _parameters in connection.transcript:
            assert species_id not in query


class TestDistribution:
    def test_unscoped_distribution_is_empty_without_querying_cells(self) -> None:
        connection = ScriptedConnection()
        serving_patch, release_patch = _patch_router(distribution, connection, _release())
        with serving_patch, release_patch:
            result = distribution.distribution_cells(species=None, year=None)

        assert result.cells == []
        assert connection.transcript == []

    def test_species_and_year_are_bound_and_geometry_is_not_selected(self) -> None:
        species_id = "S-2'; SELECT pg_sleep(10); --"
        connection = ScriptedConnection(
            [
                [
                    {
                        "cell_id": "ST5873",
                        "precision_metres": 1000,
                        "record_count": 4,
                        "verified_count": 3,
                    }
                ]
            ]
        )
        serving_patch, release_patch = _patch_router(distribution, connection, _release())
        with serving_patch, release_patch:
            result = distribution.distribution_cells(species=species_id, year=2022)

        query, parameters = connection.transcript[0]
        assert parameters == [species_id, 2022, 2022, distribution.config.MAX_CELLS]
        assert species_id not in query
        assert "geom" not in query.casefold()
        assert result.cells[0].verifiedCount == 3


class TestSpecies:
    def test_search_wildcards_are_escaped_and_never_interpolated(self) -> None:
        user_search = r"%_\\' OR TRUE --"
        connection = ScriptedConnection(
            [
                [
                    {
                        "species_id": "S-1",
                        "scientific_name": "Vipera berus",
                        "common_name": "Adder",
                        "taxon_group": None,
                        "total_records": 2,
                        "first_year": 2020,
                        "last_year": 2021,
                    }
                ],
                {"total": 1},
                [],
                [],
            ]
        )
        serving_patch, release_patch = _patch_router(species, connection, _release())
        with serving_patch, release_patch:
            result = species.list_species(
                page=1,
                pageSize=20,
                sort="name-asc",
                q=user_search,
                group=None,
                sort_by=None,
            )

        assert result.total == 1
        expected_pattern = r"%\%\_\\\\' OR TRUE --%"
        assert connection.transcript[0][1] == [
            None,
            None,
            expected_pattern,
            expected_pattern,
            expected_pattern,
            20,
            0,
        ]
        for query, _parameters in connection.transcript:
            assert user_search not in query

    def test_all_reviewed_sorts_are_fixed_sql_constants(self) -> None:
        assert set(species._LIST_SQL_BY_SORT) == {
            "name-asc",
            "scientific-name-asc",
            "records-desc",
            "latest-record-desc",
        }
        for query in species._LIST_SQL_BY_SORT.values():
            assert "serve.public_species" in query


class TestStrictModelsAndSurface:
    def test_extra_record_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RecordRow(
                id="record",
                scientificName="Vipera berus",
                commonName="Adder",
                gridRef="ST5873",
                precisionMetres=1000,
                place=None,
                year=2024,
                source="BRERC",
                easting=358000,  # type: ignore[call-arg]
            )

    def test_aggregate_only_model_rejects_rows_even_if_the_view_misbehaves(self) -> None:
        publication = RecordPublication(
            mode="aggregates-only",
            fields=PublicationFields(
                abundance=False,
                place=False,
                recordType=False,
                verification=False,
            ),
        )
        row = RecordRow(
            id="record",
            scientificName="Vipera berus",
            commonName="Adder",
            gridRef="ST5873",
            precisionMetres=1000,
            place=None,
            year=2024,
            source="BRERC",
        )
        with pytest.raises(ValidationError, match="aggregate-only"):
            RecordPage(
                publication=publication,
                items=[row],
                page=1,
                pageSize=20,
                total=1,
            )

    def test_species_slugs_are_stable_url_safe_and_collision_aware(self) -> None:
        assert slugify("  Adder / Vipera berus  ") == "adder-vipera-berus"
        assert species_slug("Vipera berus", "S-1", ambiguous=False) == "vipera-berus"
        collided = species_slug("Vipera berus", "S-1", ambiguous=True)
        assert collided == "vipera-berus-s-1"
        assert SLUG_PATTERN.fullmatch(collided)

    def test_public_app_does_not_import_the_outbound_species_proxy(self) -> None:
        main_source = Path(__file__).parents[1].joinpath("app", "main.py").read_text()
        assert "species_info" not in main_source

    def test_registered_api_routes_are_read_only_and_offer_no_bulk_export(self) -> None:
        from app.main import app

        forbidden = ("csv", "export", "download", "dump", "bulk", "raw")
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            assert methods <= {"GET", "HEAD", "OPTIONS"}
            assert not any(token in path.casefold() for token in forbidden)
