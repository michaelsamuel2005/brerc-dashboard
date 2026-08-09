import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from etl.reconciliation.streaming import ( # Update with your actual module path if different
    iter_source_chunks,
    build_source_hash_map,
)

# --- iter_source_chunks tests ---

@patch("etl.reconciliation.streaming.CONFIG", {"source": {"mode": "database"}})
def test_iter_source_chunks_raises_error_for_non_csv_mode():
    # Confirms the function enforces the CSV-only mode limitation.
    # Expects a NotImplementedError to be raised if mode is not 'csv', else fails.
    with pytest.raises(NotImplementedError) as exc_info:
        # We must wrap in list() to actually execute the generator
        list(iter_source_chunks())
        
    assert "currently only supports csv mode" in str(exc_info.value)


@patch("etl.reconciliation.streaming.CONFIG", {
    "source": {"mode": "csv", "records_path": "dummy/path.csv"},
    "reconciliation": {"chunk_size": 500}
})
@patch("etl.reconciliation.streaming.pd.read_csv")
@patch("etl.reconciliation.streaming.clean_data")
def test_iter_source_chunks_yields_cleaned_chunks(mock_clean_data, mock_read_csv):
    # Confirms the function reads data in chunks and applies the cleaning step to each.
    # Expects the generator to yield the exact dataframes returned by clean_data, else fails.
    
    # Mock read_csv returning an iterator of two raw chunk dataframes
    raw_chunk_1 = pd.DataFrame({"raw": [1, 2]})
    raw_chunk_2 = pd.DataFrame({"raw": [3, 4]})
    mock_read_csv.return_value = iter([raw_chunk_1, raw_chunk_2])
    
    # Mock clean_data returning corresponding cleaned dataframes
    clean_chunk_1 = pd.DataFrame({"clean": [1, 2]})
    clean_chunk_2 = pd.DataFrame({"clean": [3, 4]})
    mock_clean_data.side_effect = [clean_chunk_1, clean_chunk_2]

    # Execute generator
    results = list(iter_source_chunks(chunk_size=100))

    # Verify read_csv was called with the correct path and overridden chunk_size
    mock_read_csv.assert_called_once_with("dummy/path.csv", chunksize=100)
    
    # Verify clean_data was called on both raw chunks
    assert mock_clean_data.call_count == 2
    
    # Verify the final yielded list contains the cleaned chunks
    assert len(results) == 2
    assert results[0].equals(clean_chunk_1)
    assert results[1].equals(clean_chunk_2)


# --- build_source_hash_map tests ---

@patch("etl.reconciliation.streaming.iter_source_chunks")
@patch("etl.reconciliation.streaming.add_content_hash")
@patch("etl.reconciliation.streaming.build_id_hash_map_from_chunks")
def test_build_source_hash_map_chains_generators_correctly(
    mock_build_map, mock_add_hash, mock_iter_chunks
):
    # Confirms the function correctly pipelines cleaned chunks through hashing and map building.
    # Expects the final dictionary map to be returned from the chained operations, else fails.
    
    # Simulate iter_source_chunks yielding two cleaned chunks
    clean_chunk_1 = pd.DataFrame({"id": [1]})
    clean_chunk_2 = pd.DataFrame({"id": [2]})
    mock_iter_chunks.return_value = iter([clean_chunk_1, clean_chunk_2])
    
    # Simulate add_content_hash adding hashes
    hashed_chunk_1 = pd.DataFrame({"id": [1], "hash": ["A"]})
    hashed_chunk_2 = pd.DataFrame({"id": [2], "hash": ["B"]})
    mock_add_hash.side_effect = [hashed_chunk_1, hashed_chunk_2]
    
    # Simulate the final dictionary generation
    expected_map = {"1": "A", "2": "B"}
    mock_build_map.return_value = expected_map

    result = build_source_hash_map(chunk_size=250)
    
    # Verify the map building function received the generator and returned the dict
    mock_build_map.assert_called_once()
    assert result == expected_map
    
    # We must inspect the argument passed to build_id_hash_map_from_chunks (the generator)
    # and exhaust it to verify the code inside _hashed_chunks was actually executed.
    generator_arg = mock_build_map.call_args[0][0]
    list(generator_arg) # Exhaust the generator HERE
    
    # NOW we can verify the chunk size parameter was passed down and hashes were added
    mock_iter_chunks.assert_called_once_with(250)
    assert mock_add_hash.call_count == 2