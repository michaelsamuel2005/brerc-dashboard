import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from etl.reconciliation.reconcile import ( # Update with your actual module path if different
    make_safe_for_publishing,
    reconcile,
)

# --- make_safe_for_publishing tests ---

def test_make_safe_for_publishing_returns_empty_schema_when_input_empty():
    # Confirms an empty input dataframe bypasses the safety pipeline entirely.
    # Expects an empty dataframe with the exact occurrence_public schema, else fails.
    df = pd.DataFrame()
    dictionary_df = pd.DataFrame()
    connection = MagicMock()

    result = make_safe_for_publishing(df, dictionary_df, connection)

    assert result.empty
    assert list(result.columns) == [
        "record_id", "species_id", "record_year", "grid_ref",
        "locality", "precision_metres", "verified", "content_hash",
    ]


@patch("etl.reconciliation.reconcile.filter_accepted_records")
@patch("etl.reconciliation.reconcile.resolve_species_numbers")
@patch("etl.reconciliation.reconcile.classify_chunk")
@patch("etl.reconciliation.reconcile.generalise_locations")
@patch("etl.reconciliation.reconcile.add_coarse_locality")
@patch("etl.reconciliation.reconcile.prepare_public_output")
@patch("etl.reconciliation.reconcile.map_to_occurrence_public")
def test_make_safe_for_publishing_executes_pipeline(
    mock_map, mock_prepare, mock_add_locality, mock_generalise, 
    mock_classify, mock_resolve, mock_filter
):
    # Confirms records successfully pass through all safety gate functions in order.
    # Expects the final mapped dataframe to be returned after hash mapping, else fails.
    df = pd.DataFrame({"id": [1]})
    dictionary_df = pd.DataFrame()
    connection = MagicMock()

    # Setup the mock return values representing the data at each stage of the pipeline
    mock_filter.return_value = pd.DataFrame({"id": [1]})
    mock_resolve.return_value = pd.DataFrame({"id": [1], "species_no": ["A123"]})
    mock_classify.return_value = pd.DataFrame({"id": [1]})
    mock_generalise.return_value = pd.DataFrame({"id": [1]})
    
    # Needs unique_no and content_hash for the hash_lookup mapping step
    mock_add_locality.return_value = pd.DataFrame({
        "unique_no": [100], 
        "content_hash": ["abc_hash"]
    })
    
    # Needs unique_no for the safe_df["unique_no"].map step
    mock_prepare.return_value = pd.DataFrame({"unique_no": [100]})
    
    # Final schema output
    mock_map.return_value = pd.DataFrame({"record_id": [100], "content_hash": ["abc_hash"]})

    result = make_safe_for_publishing(df, dictionary_df, connection)

    mock_filter.assert_called_once()
    mock_resolve.assert_called_once()
    mock_classify.assert_called_once()
    mock_generalise.assert_called_once()
    mock_add_locality.assert_called_once()
    mock_prepare.assert_called_once()
    mock_map.assert_called_once()

    assert result["record_id"].tolist() == [100]
    assert result["content_hash"].tolist() == ["abc_hash"]


@patch("etl.reconciliation.reconcile.filter_accepted_records")
@patch("etl.reconciliation.reconcile.resolve_species_numbers")
@patch("etl.reconciliation.reconcile.classify_chunk")
def test_make_safe_for_publishing_drops_unresolved_species(
    mock_classify, mock_resolve, mock_filter, capsys
):
    # Confirms records lacking a resolved species_no are excluded from the public database.
    # Expects the unresolved records to be dropped and a warning printed, else fails.
    df = pd.DataFrame({"id": [1, 2]})
    connection = MagicMock()

    mock_filter.return_value = df
    # One record resolves successfully, the other has NaN for species_no
    mock_resolve.return_value = pd.DataFrame({
        "id": [1, 2], 
        "species_no": ["A123", None]
    })
    mock_classify.return_value = pd.DataFrame({"id": [1], "species_no": ["A123"]})

    # We only need it to survive up to classify_chunk to prove the dropna worked
    # so we'll let the rest of the mocked functions crash or mock them with create=True
    with patch("etl.reconciliation.reconcile.generalise_locations", create=True), \
         patch("etl.reconciliation.reconcile.add_coarse_locality", return_value=pd.DataFrame({"unique_no": [], "content_hash": []}), create=True), \
         patch("etl.reconciliation.reconcile.prepare_public_output", return_value=pd.DataFrame({"unique_no": []}), create=True), \
         patch("etl.reconciliation.reconcile.map_to_occurrence_public", return_value=pd.DataFrame(), create=True):
        
        make_safe_for_publishing(df, pd.DataFrame(), connection)

    captured = capsys.readouterr()
    assert "1 records excluded from public load" in captured.out
    
    # Check that classify_chunk only received the 1 valid record
    passed_to_classify = mock_classify.call_args[0][0]
    assert len(passed_to_classify) == 1
    assert passed_to_classify["species_no"].tolist() == ["A123"]


# --- reconcile tests ---

@patch("etl.reconciliation.reconcile.build_source_hash_map")
@patch("etl.reconciliation.reconcile.diff_id_hash_maps")
@patch("etl.reconciliation.reconcile.iter_source_chunks")
@patch("etl.reconciliation.reconcile.make_safe_for_publishing")
@patch("etl.reconciliation.reconcile.add_load_metadata")
@patch("etl.reconciliation.reconcile.insert_records")
@patch("etl.reconciliation.reconcile.update_records")
@patch("etl.reconciliation.reconcile.delete_records")
def test_reconcile_processes_inserts_updates_deletes(
    mock_delete, mock_update, mock_insert, mock_add_metadata, mock_make_safe, 
    mock_iter_chunks, mock_diff, mock_build_hash, capsys
):
    # Confirms the reconciliation engine correctly delegates chunked records based on their diff status.
    # Expects inserts, updates, and deletes to be correctly routed to their respective load functions, else fails.
    
    # 1 Insert (ID 1), 1 Update (ID 2), 1 Delete (ID 3)
    mock_build_hash.return_value = {"1": "hash_1", "2": "hash_2", "3": "hash_3"}
    mock_diff.return_value = {
        "inserts": {"1"},
        "updates": {"2"},
        "deletes": {"3"},
        "unchanged": set()
    }
    
    # Simulate a single chunk coming from the source streaming
    mock_iter_chunks.return_value = [
        pd.DataFrame({"unique_no": [1, 2]})
    ]
    
    # Fake safety pipeline output
    mock_make_safe.return_value = pd.DataFrame({"safe_data": [True]})
    mock_add_metadata.return_value = pd.DataFrame({"safe_data": [True], "Load": ["test"]})

    connection = MagicMock()

    result = reconcile(
        records_df=None,  # Not actually used in pass 2 since it streams
        dictionary_df=pd.DataFrame(),
        ui_map={"old": "map"},
        connection=connection,
        load_mode="incremental",
        load_timestamp="2026-08-09",
    )

    # Asserts printed output counts match
    captured = capsys.readouterr()
    assert "INSERTS: 1" in captured.out
    assert "UPDATES: 1" in captured.out
    assert "DELETES: 1" in captured.out

    # Asserts the correct chunk functions were called
    assert mock_make_safe.call_count == 2  # Once for inserts, once for updates
    assert mock_insert.call_count == 1
    assert mock_update.call_count == 1
    
    # Asserts deletes were executed
    mock_delete.assert_called_once_with({"3"}, connection)
    assert result == mock_diff.return_value


@patch("etl.reconciliation.reconcile.build_source_hash_map")
@patch("etl.reconciliation.reconcile.diff_id_hash_maps")
@patch("etl.reconciliation.reconcile.iter_source_chunks")
@patch("etl.reconciliation.reconcile.make_safe_for_publishing")
@patch("etl.reconciliation.reconcile.insert_records")
def test_reconcile_skips_writes_for_empty_safe_chunks(
    mock_insert, mock_make_safe, mock_iter_chunks, mock_diff, mock_build_hash
):
    # Confirms the engine skips writing if the safety gate filters out all records in an insert chunk.
    # Expects insert_records to NOT be called if make_safe_for_publishing returns an empty dataframe, else fails.
    
    mock_build_hash.return_value = {"1": "hash_1"}
    mock_diff.return_value = {
        "inserts": {"1"},
        "updates": set(),
        "deletes": set(),
        "unchanged": set()
    }
    
    mock_iter_chunks.return_value = [
        pd.DataFrame({"unique_no": [1]})
    ]
    
    # Simulate the safety pipeline dropping all rows (e.g. they weren't verified)
    mock_make_safe.return_value = pd.DataFrame()

    connection = MagicMock()

    reconcile(None, pd.DataFrame(), {}, connection, "incremental", "2026-08-09")

    # Because safe_insert was empty, insert_records should have been skipped
    mock_insert.assert_not_called()