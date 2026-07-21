"""
Minimal smoke test (for CI, B0).

Confirms the app starts and every stub endpoint returns HTTP 200 with JSON in
the contract shape (validated by the Pydantic response_model). This is the
"does it start + do stubs respond" check — not the full C2 audit (that's B10).
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_summary():
    r = client.get("/api/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["totalSpecies"] == 14830
    assert len(body["yearRange"]) == 2


def test_species_list():
    r = client.get("/api/species")
    assert r.status_code == 200
    assert "items" in r.json()


def test_species_detail_and_404():
    assert client.get("/api/species/1").status_code == 200
    assert client.get("/api/species/9999").status_code == 404


def test_distribution_cells():
    r = client.get("/api/distribution/cells")
    assert r.status_code == 200
    assert r.json()["type"] == "FeatureCollection"


def test_records():
    r = client.get("/api/records")
    assert r.status_code == 200
    assert "items" in r.json()


def test_provenance():
    r = client.get("/api/meta/provenance")
    assert r.status_code == 200
    assert "sources" in r.json()
