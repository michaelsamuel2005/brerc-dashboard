"""Live contract checks against an active publication-store release.

Run with ``BRERC_API_INTEGRATION=1`` and the reviewed API connection variables
set to the ``brerc_api`` read-only role. The default skip keeps ordinary unit CI
independent of a database while retaining a production-shaped acceptance test.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BRERC_API_INTEGRATION") != "1",
    reason="requires the publication database and read-only API role",
)

PROVENANCE_KEYS = {
    "releaseId",
    "datasetVersion",
    "lastUpdated",
    "recordTotal",
    "sources",
    "coverageCaveats",
    "sensitivityPolicy",
    "attributions",
}
RELEASE_IDENTITY_KEYS = {"releaseId", "datasetVersion"}
SPECIES_PAGE_KEYS = {"items", "page", "pageSize", "total", "facets"} | RELEASE_IDENTITY_KEYS
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
} | RELEASE_IDENTITY_KEYS
SUMMARY_KEYS = {
    "totalRecords",
    "totalSpecies",
    "yearRange",
    "recordsByYear",
    "topGroups",
    "coverageCaveat",
} | RELEASE_IDENTITY_KEYS
RECORD_PAGE_KEYS = {
    "publication",
    "items",
    "page",
    "pageSize",
    "total",
} | RELEASE_IDENTITY_KEYS
CELL_KEYS = {"cellId", "precisionMetres", "recordCount"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REPOSITORY = Path(__file__).resolve().parents[2]
RELEASE_EVIDENCE_QUERY = REPOSITORY / "deploy/validation/release_evidence_query.sql"
FAILED_EVIDENCE_QUERY = REPOSITORY / "deploy/validation/failed_attempt_evidence_query.sql"


def _load_validation_script(name: str):
    path = REPOSITORY / "deploy" / "validation" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - repository invariant
        raise RuntimeError(f"unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_monitor_psql(query: Path, variables: dict[str, str]) -> subprocess.CompletedProcess[str]:
    docker = shutil.which("docker")
    container = os.environ.get("BRERC_POSTGIS_TEST_CONTAINER")
    password = os.environ.get("BRERC_MONITOR_TEST_PASSWORD")
    if docker is None or not container or not password:
        raise RuntimeError("synthetic operator-query environment is incomplete")
    command = [
        docker,
        "exec",
        "--interactive",
        "--env",
        "PGPASSWORD",
        "--env",
        "PGSSLMODE=require",
        container,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "--host=localhost",
        "--username=brerc_monitor_test",
        "--dbname=brerc_ui_integration",
        "--tuples-only",
        "--no-align",
    ]
    for name, value in sorted(variables.items()):
        command.append(f"--set={name}={value}")
    command.append("--file=-")
    environment = {**os.environ, "PGPASSWORD": password}
    return subprocess.run(  # noqa: S603
        command,
        input=query.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def listed_species(client) -> dict:
    response = client.get("/api/species", params={"pageSize": 100})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items, "the acceptance release must contain at least one species"
    return items[0]


def test_health_is_database_independent_and_exact(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "version"}
    assert response.json()["status"] == "ok"


def test_provenance_describes_the_active_release_exactly(client) -> None:
    response = client.get("/api/meta/provenance")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == PROVENANCE_KEYS
    assert body["recordTotal"] >= 0
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        body["releaseId"],
    )
    assert body["datasetVersion"]
    assert body["coverageCaveats"]
    policy = body["sensitivityPolicy"]
    assert set(policy) == {
        "protectedRecordsMode",
        "publishedLocationTiersMetres",
        "note",
    }
    assert policy["protectedRecordsMode"] in {"generalised", "withheld"}
    tiers = policy["publishedLocationTiersMetres"]
    assert tiers == sorted(set(tiers))
    assert all(tier in {100, 1000, 10000} for tier in tiers)
    assert body["lastUpdated"]
    assert " " not in body["lastUpdated"]
    datetime.fromisoformat(body["lastUpdated"])

    from app.db import serving_connection

    with serving_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(SUM(record_count), 0) AS total FROM serve.public_species_year"
        )
        observed_total = int(cursor.fetchone()["total"])
        cursor.execute(
            "SELECT DISTINCT precision_metres FROM serve.public_distribution_cell "
            "UNION SELECT DISTINCT precision_metres FROM serve.public_record "
            "ORDER BY precision_metres"
        )
        observed_tiers = [int(row["precision_metres"]) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT release_id, dataset_version, sensitive_record_action FROM serve.public_release"
        )
        active_release = cursor.fetchone()
    assert body["recordTotal"] == observed_total
    assert tiers == observed_tiers
    assert body["releaseId"] == str(active_release["release_id"])
    assert body["datasetVersion"] == active_release["dataset_version"]
    assert (
        policy["protectedRecordsMode"]
        == {
            "generalise": "generalised",
            "withhold": "withheld",
        }[active_release["sensitive_record_action"]]
    )
    if active_release["sensitive_record_action"] == "withhold":
        assert "generalis" not in policy["note"].casefold()


@pytest.mark.skipif(
    not os.environ.get("BRERC_MONITOR_TEST_DATABASE_URL"),
    reason="requires the synthetic monitor-role database URL",
)
def test_monitor_release_evidence_matches_both_live_api_identities(client) -> None:
    import psycopg
    from psycopg.rows import dict_row

    monitor_url = os.environ["BRERC_MONITOR_TEST_DATABASE_URL"]
    with psycopg.connect(monitor_url, row_factory=dict_row) as connection:
        identity = connection.execute(
            "SELECT environment_id, database_name FROM serve.etl_monitor_identity"
        ).fetchone()
        rows = connection.execute(
            """
            SELECT run_id, release_id, active_release_id, dataset_version,
                   source_data_as_of, candidate_sha256, base_release_id,
                   reused_active_release, source_rows, public_records,
                   distribution_cells, load_mode, status, started_at, finished_at
            FROM serve.etl_release_evidence
            """
        ).fetchall()
    assert len(rows) == 1
    evidence = rows[0]
    environment_id = str(identity["environment_id"])
    expected_database = str(identity["database_name"])
    expected_role = "brerc_monitor_test"
    summary = client.get("/api/summary")
    provenance = client.get("/api/meta/provenance")
    assert summary.status_code == 200
    assert provenance.status_code == 200
    summary_body = summary.json()
    provenance_body = provenance.json()
    release_id = str(evidence["release_id"])
    assert str(evidence["active_release_id"]) == release_id
    assert summary_body["releaseId"] == release_id
    assert provenance_body["releaseId"] == release_id
    assert summary_body["datasetVersion"] == evidence["dataset_version"]
    assert provenance_body["datasetVersion"] == evidence["dataset_version"]
    assert provenance_body["lastUpdated"] == evidence["source_data_as_of"].isoformat()
    assert evidence["load_mode"] == "refresh"
    assert evidence["status"] == "succeeded"
    assert re.fullmatch(r"[0-9a-f]{64}", evidence["candidate_sha256"])
    assert evidence["base_release_id"] is not None
    assert evidence["source_rows"] >= 1
    assert evidence["public_records"] >= 0
    assert evidence["distribution_cells"] >= 1

    if not (
        os.environ.get("BRERC_POSTGIS_TEST_CONTAINER")
        and os.environ.get("BRERC_MONITOR_TEST_PASSWORD")
    ):
        pytest.skip("requires the synthetic PostGIS container for exact psql execution")
    operator_result = _run_monitor_psql(
        RELEASE_EVIDENCE_QUERY,
        {
            "run_id": str(evidence["run_id"]),
            "expected_environment_id": environment_id,
            "expected_database": expected_database,
            "expected_role": expected_role,
        },
    )
    assert operator_result.returncode == 0, operator_result.stderr
    malformed_run = _run_monitor_psql(
        RELEASE_EVIDENCE_QUERY,
        {
            "run_id": "not-a-uuid",
            "expected_environment_id": environment_id,
            "expected_database": expected_database,
            "expected_role": expected_role,
        },
    )
    assert malformed_run.returncode != 0
    database_body = json.loads(operator_result.stdout)
    assert database_body["runId"] == str(evidence["run_id"])

    invocation_id = "0123456789abcdef0123456789abcdef"
    loader_result = {
        "status": "ok",
        "mode": "refresh",
        "state": "succeeded",
        "runId": database_body["runId"],
        "releaseId": database_body["releaseId"],
        "candidateSha256": database_body["candidateSha256"],
        "activated": True,
        "reusedActiveRelease": database_body["reusedActiveRelease"],
        "sourceRows": database_body["sourceRows"],
        "publicRecords": database_body["publicRecords"],
        "distributionCells": database_body["distributionCells"],
    }
    verifier = _load_validation_script("verify_release_evidence")
    with tempfile.TemporaryDirectory(prefix="brerc-operator-evidence-") as temporary:
        directory = Path(temporary)
        unit = directory / "unit.properties"
        journal = directory / "journal.json"
        database = directory / "database.json"
        window = directory / "database-window.json"
        api_summary = directory / "api-summary.json"
        api_provenance = directory / "api-provenance.json"
        window_start = evidence["started_at"] - timedelta(seconds=1)
        window_end = evidence["finished_at"] + timedelta(seconds=1)
        unit.write_text(
            "\n".join(
                (
                    f"InvocationID={invocation_id}",
                    "Result=success",
                    "ExecMainCode=exited",
                    "ExecMainStatus=0",
                    "ActiveState=inactive",
                    "SubState=dead",
                    f"InactiveExitTimestamp=@{window_start.timestamp():.6f}",
                    f"StateChangeTimestamp=@{window_end.timestamp():.6f}",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        journal.write_text(
            json.dumps(
                {
                    "_SYSTEMD_INVOCATION_ID": invocation_id,
                    "__REALTIME_TIMESTAMP": str(
                        int(evidence["finished_at"].timestamp() * 1_000_000)
                    ),
                    "MESSAGE": json.dumps(loader_result, separators=(",", ":")),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        window.write_text(
            json.dumps(
                {
                    "invocationId": invocation_id,
                    "mode": "refresh",
                    "windowStart": window_start.isoformat(),
                    "windowEnd": window_end.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        database.write_text(operator_result.stdout, encoding="utf-8")
        api_summary.write_text(json.dumps(summary_body), encoding="utf-8")
        api_provenance.write_text(json.dumps(provenance_body), encoding="utf-8")
        verified = verifier.verify(
            invocation_id=invocation_id,
            expected_mode="refresh",
            expected_environment_id=environment_id,
            expected_database=expected_database,
            expected_role=expected_role,
            unit_properties_path=unit,
            journal_path=journal,
            window_path=window,
            database_path=database,
            summary_path=api_summary,
            provenance_path=api_provenance,
        )
    assert verified["status"] == "verified"
    assert verified["releaseId"] == release_id


@pytest.mark.skipif(
    not os.environ.get("BRERC_ADMIN_TEST_DATABASE_URL")
    or not os.environ.get("BRERC_POSTGIS_TEST_CONTAINER")
    or not os.environ.get("BRERC_MONITOR_TEST_PASSWORD"),
    reason="requires the synthetic admin and monitor operator-query boundary",
)
def test_failed_attempt_operator_query_and_verifier_fail_closed() -> None:
    import psycopg

    verifier = _load_validation_script("verify_failed_attempt_evidence")
    window_start = "2099-01-01T00:00:00+00:00"
    window_end = "2099-01-01T00:03:00+00:00"
    manager_start = int(datetime.fromisoformat(window_start).timestamp())
    manager_end = int(datetime.fromisoformat(window_end).timestamp())
    first_job = uuid4()
    second_job = uuid4()
    invocation_id = "0123456789abcdef0123456789abcdef"
    admin_url = os.environ["BRERC_ADMIN_TEST_DATABASE_URL"]

    with psycopg.connect(admin_url, autocommit=True) as connection:
        environment_id = str(
            connection.execute(
                "SELECT environment_id FROM loader_control.deployment_identity WHERE singleton"
            ).fetchone()[0]
        )

        def run_query(**changes: str) -> subprocess.CompletedProcess[str]:
            variables = {
                "window_start": window_start,
                "window_end": window_end,
                "load_mode": "initial",
                "expected_environment_id": environment_id,
                "expected_database": "brerc_ui_integration",
                "expected_role": "brerc_monitor_test",
                **changes,
            }
            return _run_monitor_psql(FAILED_EVIDENCE_QUERY, variables)

        def verify(path: Path):
            unit = path.parent / "unit.properties"
            journal = path.parent / "journal.json"
            window = path.parent / "database-window.json"
            unit.write_text(
                "\n".join(
                    (
                        f"InvocationID={invocation_id}",
                        "Result=exit-code",
                        "ExecMainCode=1",
                        "ExecMainStatus=1",
                        "ActiveState=failed",
                        "SubState=failed",
                        f"InactiveExitTimestamp=@{manager_start}",
                        f"StateChangeTimestamp=@{manager_end}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            journal.write_text(
                json.dumps(
                    {
                        "_SYSTEMD_INVOCATION_ID": invocation_id,
                        "__REALTIME_TIMESTAMP": str(
                            int(
                                datetime.fromisoformat("2099-01-01T00:01:30+00:00").timestamp()
                                * 1_000_000
                            )
                        ),
                        "MESSAGE": "synthetic loader failure",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            window.write_text(
                json.dumps(
                    {
                        "invocationId": invocation_id,
                        "mode": "initial",
                        "windowStart": window_start,
                        "windowEnd": window_end,
                    }
                ),
                encoding="utf-8",
            )
            return verifier.verify(
                path,
                invocation_id=invocation_id,
                expected_mode="initial",
                expected_window_start=window_start,
                expected_window_end=window_end,
                expected_environment_id=environment_id,
                expected_database="brerc_ui_integration",
                expected_role="brerc_monitor_test",
                unit_properties_path=unit,
                journal_path=journal,
                window_path=window,
            )

        try:
            empty = run_query()
            assert empty.returncode == 0, empty.stderr
            with tempfile.TemporaryDirectory(prefix="brerc-failure-evidence-") as temporary:
                evidence_path = Path(temporary) / "empty.json"
                evidence_path.write_text(empty.stdout, encoding="utf-8")
                assert verify(evidence_path)["databaseState"] == "no-matching-job"

            insert = """
                INSERT INTO loader_control.etl_job (
                    job_id, source_id, load_mode, status, started_at,
                    heartbeat_at, finished_at, failure_code,
                    source_rows_seen, candidate_rows, rows_withheld, created_at
                ) VALUES (
                    %s, 'dashboard.main_data_dash', 'initial', 'failed', %s,
                    %s, %s, 'LOADER_EXECUTION_FAILED', 0, 0, 0, %s
                )
            """
            first_started = "2099-01-01T00:01:00+00:00"
            first_finished = "2099-01-01T00:01:01+00:00"
            connection.execute(
                insert,
                (first_job, first_started, first_started, first_finished, first_started),
            )
            one = run_query()
            assert one.returncode == 0, one.stderr
            with tempfile.TemporaryDirectory(prefix="brerc-failure-evidence-") as temporary:
                evidence_path = Path(temporary) / "one.json"
                evidence_path.write_text(one.stdout, encoding="utf-8")
                verified = verify(evidence_path)
            assert verified["jobCount"] == 1
            assert verified["runId"] == str(first_job)

            second_started = "2099-01-01T00:02:00+00:00"
            second_finished = "2099-01-01T00:02:01+00:00"
            connection.execute(
                insert,
                (second_job, second_started, second_started, second_finished, second_started),
            )
            two = run_query()
            assert two.returncode == 0, two.stderr
            with tempfile.TemporaryDirectory(prefix="brerc-failure-evidence-") as temporary:
                evidence_path = Path(temporary) / "two.json"
                evidence_path.write_text(two.stdout, encoding="utf-8")
                with pytest.raises(verifier.FailedAttemptEvidenceInvalid):
                    verify(evidence_path)

            for invalid in (
                {"load_mode": "refesh"},
                {"load_mode": "incremental"},
                {"window_start": "not-a-timestamp"},
                {
                    "window_start": "2099-01-01T00:03:00+00:00",
                    "window_end": "2099-01-01T00:00:00+00:00",
                },
                {"window_end": "2099-01-01T04:00:01+00:00"},
                {"expected_environment_id": str(uuid4())},
                {"expected_database": "wrong_database"},
                {"expected_role": "wrong_role"},
            ):
                result = run_query(**invalid)
                assert result.returncode != 0
        finally:
            connection.execute(
                "DELETE FROM loader_control.etl_job WHERE job_id = ANY(%s)",
                ([first_job, second_job],),
            )


def test_every_public_data_response_carries_the_active_release_identity(
    client, listed_species: dict
) -> None:
    provenance = client.get("/api/meta/provenance").json()
    expected = {
        "releaseId": provenance["releaseId"],
        "datasetVersion": provenance["datasetVersion"],
    }
    responses = [
        client.get("/api/summary"),
        client.get("/api/species"),
        client.get(f"/api/species/{listed_species['speciesId']}"),
        client.get("/api/distribution/cells", params={"species": listed_species["speciesId"]}),
        client.get("/api/records", params={"species": listed_species["speciesId"]}),
    ]
    for response in responses:
        assert response.status_code == 200
        body = response.json()
        assert {key: body[key] for key in RELEASE_IDENTITY_KEYS} == expected


def test_species_listing_and_detail_match_the_strict_browser_contract(
    client, listed_species: dict
) -> None:
    listing = client.get("/api/species", params={"pageSize": 100}).json()
    assert set(listing) == SPECIES_PAGE_KEYS
    assert set(listing["facets"]) == {"groups"}
    assert len(listing["items"]) <= listing["pageSize"]
    assert len(listing["items"]) <= listing["total"]
    assert len({item["speciesId"] for item in listing["items"]}) == len(listing["items"])
    assert len({item["slug"] for item in listing["items"]}) == len(listing["items"])
    for item in listing["items"]:
        assert set(item) == SPECIES_ITEM_KEYS
        assert SLUG_PATTERN.fullmatch(item["slug"])
        assert item["recordCount"] > 0
        assert item["firstYear"] <= item["lastYear"]

    response = client.get(f"/api/species/{listed_species['speciesId']}")
    assert response.status_code == 200
    detail = response.json()
    assert set(detail) == SPECIES_DETAIL_KEYS
    assert detail["speciesId"] == listed_species["speciesId"]
    assert detail["slug"] == listed_species["slug"]
    assert detail["imagePublication"] == "fallback-only"
    assert "image" not in detail
    assert set(detail["stats"]) == {
        "recordCount",
        "yearRange",
        "verificationAvailable",
        "verifiedCount",
    }
    assert detail["stats"]["recordCount"] == listed_species["recordCount"]
    assert detail["stats"]["verificationAvailable"] == (
        detail["stats"]["verifiedCount"] is not None
    )
    assert detail["releaseId"] == listing["releaseId"]
    assert detail["datasetVersion"] == listing["datasetVersion"]


def test_species_search_escapes_wildcards_and_sort_is_allow_listed(client) -> None:
    for pattern in ("%", "_", "%%", "\\"):
        response = client.get("/api/species", params={"q": pattern})
        assert response.status_code == 200
        assert response.json()["total"] == 0

    for order in (
        "name-asc",
        "scientific-name-asc",
        "records-desc",
        "latest-record-desc",
    ):
        assert client.get("/api/species", params={"sort": order}).status_code == 200
    assert (
        client.get(
            "/api/species",
            params={"sort": "total_records; DROP TABLE publication.public_species"},
        ).status_code
        == 422
    )


def test_summary_supports_real_species_scope_and_404s_unknown(client, listed_species: dict) -> None:
    global_response = client.get("/api/summary")
    assert global_response.status_code == 200
    global_body = global_response.json()
    assert set(global_body) == SUMMARY_KEYS
    assert sum(row["count"] for row in global_body["recordsByYear"]) == global_body["totalRecords"]
    assert global_body["topGroups"] == []

    scoped_response = client.get("/api/summary", params={"species": listed_species["speciesId"]})
    assert scoped_response.status_code == 200
    scoped = scoped_response.json()
    assert set(scoped) == SUMMARY_KEYS
    assert scoped["totalSpecies"] == 1
    assert scoped["totalRecords"] == listed_species["recordCount"]
    assert sum(row["count"] for row in scoped["recordsByYear"]) == scoped["totalRecords"]
    assert client.get("/api/summary", params={"species": "NO-SUCH-SPECIES"}).status_code == 404


def test_distribution_is_empty_unscoped_and_safe_when_scoped(client, listed_species: dict) -> None:
    unscoped = client.get("/api/distribution/cells")
    assert unscoped.status_code == 200
    assert unscoped.json()["cells"] == []
    assert (
        client.get("/api/distribution/cells", params={"species": "NO-SUCH-SPECIES"}).json()["cells"]
        == []
    )

    response = client.get(
        "/api/distribution/cells", params={"species": listed_species["speciesId"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"verificationAvailable", "cells"} | RELEASE_IDENTITY_KEYS
    assert body["cells"], "a listed species must have aggregate distribution cells"
    forbidden = {
        "geom",
        "geometry",
        "coordinates",
        "polygon",
        "latitude",
        "longitude",
        "easting",
        "northing",
    }
    for cell in body["cells"]:
        assert set(cell) - {"verifiedCount"} == CELL_KEYS
        assert not (set(cell) & forbidden)
        assert cell["precisionMetres"] in {100, 1000, 10000}
        assert cell["recordCount"] > 0
        assert ("verifiedCount" in cell) == body["verificationAvailable"]


def test_records_are_empty_unscoped_and_honour_the_year_filter(
    client, listed_species: dict
) -> None:
    unscoped = client.get("/api/records")
    assert unscoped.status_code == 200
    body = unscoped.json()
    assert set(body) == RECORD_PAGE_KEYS
    assert body["items"] == []
    assert body["total"] == 0

    scoped = client.get(
        "/api/records", params={"species": listed_species["speciesId"], "pageSize": 100}
    ).json()
    assert set(scoped) == RECORD_PAGE_KEYS
    assert set(scoped["publication"]) == {"mode", "fields"}
    assert set(scoped["publication"]["fields"]) == {
        "abundance",
        "place",
        "recordType",
        "verification",
    }
    if scoped["publication"]["mode"] == "aggregates-only":
        assert scoped["items"] == []
        assert scoped["total"] == 0
        return

    assert scoped["items"], "individual-record mode must expose scoped records"
    selected_year = scoped["items"][0]["year"]
    by_year = client.get(
        "/api/records",
        params={
            "species": listed_species["speciesId"],
            "year": selected_year,
            "pageSize": 100,
        },
    )
    assert by_year.status_code == 200
    assert by_year.json()["items"]
    assert {row["year"] for row in by_year.json()["items"]} == {selected_year}
    assert client.get("/api/records", params={"species": "NO-SUCH-SPECIES"}).json()["items"] == []


def test_api_role_cannot_write_and_guard_rejects_base_tables() -> None:
    import psycopg

    from app.db import ServingRelationError, assert_serving_relation, serving_connection

    with (
        serving_connection() as connection,
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
    ):
        cursor.execute("CREATE TEMP TABLE api_should_not_write (id integer)")

    for relation in (
        "publication.public_record",
        "loader_control.source_disposition",
        "serve.etl_job_status",
    ):
        with pytest.raises(ServingRelationError):
            assert_serving_relation(relation)


@pytest.mark.skipif(
    not os.environ.get("BRERC_LOADER_TEST_DATABASE_URL"),
    reason="requires the synthetic loader-role database URL",
)
def test_loader_credentials_are_rejected_before_the_api_yields_a_session() -> None:
    from app import db

    loader_url = os.environ["BRERC_LOADER_TEST_DATABASE_URL"]
    with (
        patch.object(db, "get_database_url", return_value=loader_url),
        pytest.raises(RuntimeError, match="dedicated read-only API role"),
        db.serving_connection(),
    ):
        raise AssertionError("the API yielded a session authenticated with loader credentials")
