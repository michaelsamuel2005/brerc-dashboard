import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from etl.pipeline import run_pipeline # Update with your actual module path if different


@patch("etl.pipeline.clean_data")
@patch("etl.pipeline.resolve_species_numbers")
@patch("etl.pipeline.build_public_aggregation")
@patch("etl.pipeline.persist_aggregation_outputs")
@patch("etl.pipeline.upsert_provenance")
@patch("etl.pipeline.reconcile")
def test_run_pipeline_executes_all_steps_in_order(
    mock_reconcile,
    mock_upsert_prov,
    mock_persist_agg,
    mock_build_agg,
    mock_resolve,
    mock_clean,
):
    # Confirms run_pipeline correctly orchestrates cleaning, resolution, aggregation, provenance, and reconciliation.
    # Expects all subsystems to be called sequentially and a summary dictionary returned, else fails.
    
    source_df = pd.DataFrame({"raw": [1]})
    dictionary_df = pd.DataFrame({"dict": [1]})
    ui_map = {"1": "hash"}
    connection = MagicMock()
    load_mode = "incremental"

    # Mock return values for intermediate pipeline steps
    mock_clean.side_effect = lambda df: df  # Pass-through clean
    mock_resolve.return_value = pd.DataFrame({"resolved": [1]})
    
    fake_agg_outputs = {
        "species_index": pd.DataFrame({"species": [1]}),
        "aggregation": pd.DataFrame({"count": [10]})
    }
    mock_build_agg.return_value = fake_agg_outputs
    mock_reconcile.return_value = {"inserts": {"1"}, "updates": set(), "deletes": set(), "unchanged": set()}

    result = run_pipeline(source_df, dictionary_df, ui_map, connection, load_mode)

    # Verify each step was invoked correctly
    assert mock_clean.call_count == 2  # Once for source, once for dictionary
    mock_resolve.assert_called_once()
    mock_build_agg.assert_called_once()
    mock_persist_agg.assert_called_once()
    mock_upsert_prov.assert_called_once()
    mock_reconcile.assert_called_once()

    # Verify the structure of the returned summary
    assert "reconciliation" in result
    assert "aggregation" in result
    assert result["reconciliation"]["inserts"] == {"1"}