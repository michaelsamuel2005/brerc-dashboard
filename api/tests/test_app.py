"""App wiring tests that don't need a database (lifespan is not started)."""

from __future__ import annotations

from app.main import create_app


def test_app_builds_and_registers_routes():
    app = create_app()
    paths = set(app.openapi()["paths"].keys())
    assert "/health" in paths
    assert "/species/search" in paths
    assert "/species/filters" in paths
    assert "/occurrences/summary" in paths
    assert "/occurrences/cells" in paths
    assert "/species-info" in paths


def test_only_get_methods_are_exposed():
    app = create_app()
    for path, operations in app.openapi()["paths"].items():
        verbs = {method.upper() for method in operations} - {"HEAD", "OPTIONS", "PARAMETERS"}
        assert verbs <= {"GET"}, f"{path} exposes non-GET methods: {verbs}"
