"""The sensitive-species preflight: a missing list must stop the run BEFORE
any database write, and the dashboard must say what actually happened.

Review findings on the fail-closed change (Ting Ting, 17 Aug):
  1. the original raise fired in step 6 (reconciliation), but steps 4-5 had
     already persisted aggregation outputs and provenance — the run failed
     with the bad state already landed;
  3. describe_failure() had no case for the new exception, so the run-history
     dashboard showed "an unexpected error occurred" instead of naming the
     species list.

These tests pin the fixes. No database needed: the point is precisely that
nothing database-shaped gets called.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from etl import pipeline
from etl.job import describe_failure
from etl.safety_gate import rules
from etl.safety_gate.rules import SensitiveSpeciesListUnavailable


@pytest.fixture
def missing_sensitive_list(monkeypatch):
    """Points the loader at a path that does not exist, with a clean cache."""
    rules.load_sensitive_species.cache_clear()
    monkeypatch.setattr(
        rules,
        "CONFIG",
        {"files": {"sensitive_species": {"path": "/nonexistent/sensitive.csv"}}},
    )
    yield
    rules.load_sensitive_species.cache_clear()


def test_pipeline_refuses_before_any_database_write(missing_sensitive_list):
    """A missing list must abort in step 0 — with persist, provenance and
    reconciliation provably never reached. This is the review finding: the
    old ordering wrote fresh aggregation data and a new provenance row first,
    so a failed run had already replaced public state."""
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch.object(pipeline, "persist_aggregation_outputs") as persist,
        patch.object(pipeline, "upsert_provenance") as provenance,
        patch.object(pipeline, "reconcile") as reconcile,
        patch.object(pipeline, "build_public_aggregation") as aggregate,
    ):
        with pytest.raises(SensitiveSpeciesListUnavailable):
            pipeline.run_pipeline(
                source_df=pd.DataFrame(),
                dictionary_df=pd.DataFrame(),
                ui_map={},
                connection=None,
                load_mode="incremental",
            )

        persist.assert_not_called()
        provenance.assert_not_called()
        reconcile.assert_not_called()
        aggregate.assert_not_called()


def test_describe_failure_names_the_sensitive_species_list():
    """The dashboard summary must tell staff WHICH file is the problem, not
    fall through to "an unexpected error occurred" — a loud failure nobody
    can act on is only half a fix."""
    summary = describe_failure(
        SensitiveSpeciesListUnavailable("No sensitive-species list found at ...")
    )

    assert "sensitive-species list" in summary
    assert "before changing any data" in summary
    assert "species_no" in summary and "nbn_number" in summary
    # And it must NOT be the generic fallback.
    assert summary != "An unexpected error occurred during the update."


def test_generic_failures_still_get_the_generic_summary():
    """The new branch must not swallow unrelated errors."""
    summary = describe_failure(RuntimeError("something else entirely"))
    assert summary == "An unexpected error occurred during the update."
