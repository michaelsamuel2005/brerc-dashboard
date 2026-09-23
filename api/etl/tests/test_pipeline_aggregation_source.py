"""The map cells and species index are REPLACED every run, so they must be
built from every source record, even on an incremental run that reconciles
only the records changed since the last load.

Found testing against the mock BRERC database (23 Sep): a second incremental
run with no changes built the map from 0 records, and persist_aggregation_outputs
truncated distribution_cell, leaving the public map empty.

No database needed.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from etl import nightly_pipeline as pipeline
from etl.job import nightly_job


def _passthrough_resolve(df, *args, **kwargs):
    # Stands in for resolve_species_numbers(): returns the records unchanged
    return df


def test_incremental_run_builds_map_from_every_record():
    # Nothing changed since the last load, but the full source has 3 records.
    # The map must be built from all 3; reconciliation sees only the 0 changes.
    changed_only = pd.DataFrame({"unique_no": []})
    every_record = pd.DataFrame({"unique_no": [1, 2, 3]})

    with (
        patch.object(pipeline, "load_sensitive_species"),
        patch.object(pipeline, "clean_data", side_effect=lambda df: df),
        patch.object(pipeline, "resolve_species_numbers", side_effect=_passthrough_resolve),
        patch.object(pipeline, "build_public_aggregation") as aggregate,
        patch.object(pipeline, "persist_aggregation_outputs"),
        patch.object(pipeline, "upsert_provenance"),
        patch.object(pipeline, "reconcile") as reconcile,
    ):
        pipeline.run_pipeline(
            source_df=changed_only,
            dictionary_df=pd.DataFrame(),
            ui_map={},
            connection=None,
            load_mode="incremental",
            aggregation_source_df=every_record,
        )

    assert len(aggregate.call_args[0][0]) == 3
    assert len(reconcile.call_args[0][0]) == 0


def test_without_aggregation_source_the_source_is_used_for_both():
    # A full load passes no separate aggregation source: source_df is complete
    every_record = pd.DataFrame({"unique_no": [1, 2, 3]})

    with (
        patch.object(pipeline, "load_sensitive_species"),
        patch.object(pipeline, "clean_data", side_effect=lambda df: df),
        patch.object(pipeline, "resolve_species_numbers", side_effect=_passthrough_resolve),
        patch.object(pipeline, "build_public_aggregation") as aggregate,
        patch.object(pipeline, "persist_aggregation_outputs"),
        patch.object(pipeline, "upsert_provenance"),
        patch.object(pipeline, "reconcile") as reconcile,
    ):
        pipeline.run_pipeline(
            source_df=every_record,
            dictionary_df=pd.DataFrame(),
            ui_map={},
            connection=None,
            load_mode="initial",
        )

    assert len(aggregate.call_args[0][0]) == 3
    assert len(reconcile.call_args[0][0]) == 3


@patch("etl.job.load_sensitive_species")
@patch("etl.job.mark_run_successful")
@patch("etl.job.start_run", return_value=1)
@patch("etl.job.check_table_exists", return_value=True)
@patch("etl.job.check_table_has_rows", return_value=True)
@patch("etl.job.should_run_initial_load", return_value=False)
@patch("etl.job.get_last_load_date", return_value="2026-01-01")
@patch("etl.job.load_species_dictionary", return_value=pd.DataFrame())
@patch("etl.job.get_current_ui_map", return_value={})
@patch("etl.job.run_pipeline")
@patch("etl.job.get_source_connection")
@patch("etl.job.get_destination_connection")
def test_incremental_database_run_also_loads_the_full_source(
    mock_get_conn,
    mock_get_source_conn,
    mock_run_pipeline,
    *_,
):
    # On an incremental database run the job reads the source twice: once
    # since the watermark (for reconciliation) and once in full (for the map).
    changed_only = pd.DataFrame({"unique_no": []})
    every_record = pd.DataFrame({"unique_no": [1, 2, 3]})

    def fake_load(connection, watermark_date=None):
        return every_record if watermark_date is None else changed_only

    mock_get_conn.return_value.__enter__.return_value = MagicMock()
    mock_get_source_conn.return_value.__enter__.return_value = MagicMock()

    with (
        patch("etl.job.load_source_data", side_effect=fake_load),
        patch(
            "etl.job.get_config",
            return_value={
                "source": {"mode": "database"},
                "destination": {"table": "occurrence_public"},
                "load": {"incremental_check": True},
            },
        ),
    ):
        nightly_job()

    call = mock_run_pipeline.call_args
    assert len(call[0][0]) == 0  # source_df: changes only
    assert len(call.kwargs["aggregation_source_df"]) == 3  # every record
