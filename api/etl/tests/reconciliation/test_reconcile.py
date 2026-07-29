import pandas as pd
from unittest.mock import MagicMock, patch

from etl.reconciliation.reconcile import reconcile


# --- reconcile tests ---

@patch("etl.reconciliation.reconcile.delete_records")
@patch("etl.reconciliation.reconcile.update_records")
@patch("etl.reconciliation.reconcile.insert_records")
@patch("etl.reconciliation.reconcile.upsert_species")
@patch("etl.reconciliation.reconcile.build_species_index")
@patch("etl.reconciliation.reconcile.resolve_species_numbers")
@patch("etl.reconciliation.reconcile.filter_accepted_records")
@patch("etl.reconciliation.reconcile.make_safe_for_publishing")
@patch("etl.reconciliation.reconcile.get_reconciliation_records")
@patch("etl.reconciliation.reconcile.diff_id_hash_maps")
@patch("etl.reconciliation.reconcile.build_id_hash_map")
@patch("etl.reconciliation.reconcile.add_content_hash")
def test_reconcile_returns_changes(
    mock_add_hash,
    mock_build_map,
    mock_diff,
    mock_get_records,
    mock_safe,
    mock_filter,
    mock_resolve,
    mock_species_index,
    mock_upsert,
    mock_insert,
    mock_update,
    mock_delete,
):
    # Confirms reconcile returns the reconciliation summary.
    # Expects the same dictionary returned by diff_id_hash_maps.

    source_df = pd.DataFrame({"unique_no": [1]})
    dictionary_df = pd.DataFrame()
    ui_map = {}
    connection = MagicMock()

    mock_add_hash.return_value = source_df
    mock_build_map.return_value = {}
    changes = {
        "inserts": set(),
        "updates": set(),
        "deletes": set(),
        "unchanged": set(),
    }
    mock_diff.return_value = changes
    mock_get_records.return_value = {
        "inserts": pd.DataFrame(),
        "updates": pd.DataFrame(),
        "deletes": set(),
        "unchanged": set(),
    }

    result = reconcile(
        source_df,
        dictionary_df,
        ui_map,
        connection,
    )

    assert result == changes


@patch("etl.reconciliation.reconcile.insert_records")
@patch("etl.reconciliation.reconcile.update_records")
@patch("etl.reconciliation.reconcile.delete_records")
@patch("etl.reconciliation.reconcile.make_safe_for_publishing")
@patch("etl.reconciliation.reconcile.get_reconciliation_records")
@patch("etl.reconciliation.reconcile.diff_id_hash_maps")
@patch("etl.reconciliation.reconcile.build_id_hash_map")
@patch("etl.reconciliation.reconcile.add_content_hash")
def test_reconcile_passes_safe_data_to_database(
    mock_add_hash,
    mock_build_map,
    mock_diff,
    mock_get_records,
    mock_safe,
    mock_delete,
    mock_update,
    mock_insert,
):
    # Confirms only safety-processed records are written.
    # Expects insert_records and update_records to receive
    # make_safe_for_publishing output.

    source_df = pd.DataFrame({"unique_no": [1]})
    connection = MagicMock()

    safe_df = pd.DataFrame({"record_id": [1]})

    mock_add_hash.return_value = source_df
    mock_build_map.return_value = {}
    mock_diff.return_value = {
        "inserts": {1},
        "updates": set(),
        "deletes": set(),
        "unchanged": set(),
    }

    mock_get_records.return_value = {
        "inserts": source_df,
        "updates": pd.DataFrame(),
        "deletes": set(),
        "unchanged": set(),
    }

    mock_safe.return_value = safe_df

    with patch("etl.reconciliation.reconcile.filter_accepted_records"), \
         patch("etl.reconciliation.reconcile.resolve_species_numbers"), \
         patch("etl.reconciliation.reconcile.build_species_index"), \
         patch("etl.reconciliation.reconcile.upsert_species"):

        reconcile(
            source_df,
            pd.DataFrame(),
            {},
            connection,
        )

    mock_insert.assert_called_once_with(safe_df, connection)


@patch("etl.reconciliation.reconcile.upsert_species")
@patch("etl.reconciliation.reconcile.build_species_index")
@patch("etl.reconciliation.reconcile.resolve_species_numbers")
@patch("etl.reconciliation.reconcile.filter_accepted_records")
@patch("etl.reconciliation.reconcile.make_safe_for_publishing")
@patch("etl.reconciliation.reconcile.get_reconciliation_records")
@patch("etl.reconciliation.reconcile.diff_id_hash_maps")
@patch("etl.reconciliation.reconcile.build_id_hash_map")
@patch("etl.reconciliation.reconcile.add_content_hash")
@patch("etl.reconciliation.reconcile.insert_records")
@patch("etl.reconciliation.reconcile.update_records")
@patch("etl.reconciliation.reconcile.delete_records")
def test_reconcile_skips_species_upsert_when_no_records(
    mock_delete,
    mock_update,
    mock_insert,
    mock_add_hash,
    mock_build_map,
    mock_diff,
    mock_get_records,
    mock_safe,
    mock_filter,
    mock_resolve,
    mock_species_index,
    mock_upsert,
):
    # Confirms species upsert is skipped when there are no
    # insert or update records.

    source_df = pd.DataFrame({"unique_no": []})

    mock_add_hash.return_value = source_df
    mock_build_map.return_value = {}
    mock_diff.return_value = {
        "inserts": set(),
        "updates": set(),
        "deletes": set(),
        "unchanged": set(),
    }

    mock_get_records.return_value = {
        "inserts": pd.DataFrame(),
        "updates": pd.DataFrame(),
        "deletes": set(),
        "unchanged": set(),
    }

    reconcile(
        source_df,
        pd.DataFrame(),
        {},
        MagicMock(),
    )

    mock_upsert.assert_not_called()