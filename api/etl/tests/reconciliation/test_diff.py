import pandas as pd
import pytest

from etl.reconciliation.diff import (  # Update with your actual module path if different
    build_id_hash_map,
    build_id_hash_map_from_chunks,
    diff_id_hash_maps,
)


# --- build_id_hash_map tests ---


def test_build_id_hash_map_returns_dictionary():
    # Confirms each unique_no is successfully mapped to its content hash.
    # Expects IDs to be stored as strings because database keys are TEXT, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1, 2],
            "content_hash": ["abc", "def"],
        }
    )

    result = build_id_hash_map(df)

    assert result == {
        "1": "abc",
        "2": "def",
    }


def test_build_id_hash_map_returns_empty_dictionary_for_empty_dataframe():
    # Confirms an empty dataframe produces an empty dictionary without errors.
    # Expects an empty dictionary {} to be returned, else fails.
    df = pd.DataFrame(
        columns=[
            "unique_no",
            "content_hash",
        ]
    )

    result = build_id_hash_map(df)

    assert result == {}


def test_build_id_hash_map_raises_keyerror_missing_columns():
    # Confirms the function enforces the presence of necessary data columns.
    # Expects a KeyError to be raised if unique_no or content_hash are missing, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1, 2],
            # Missing content_hash
        }
    )

    with pytest.raises(KeyError) as exc_info:
        build_id_hash_map(df)

    assert "Missing required columns" in str(exc_info.value)
    assert "content_hash" in str(exc_info.value)


# --- build_id_hash_map_from_chunks tests ---


def test_build_id_hash_map_from_chunks_merges_dictionaries():
    # Confirms the function correctly iterates over chunks and merges their hash maps.
    # Expects a single combined dictionary of all unique_no to content_hash mappings, else fails.
    chunk1 = pd.DataFrame({"unique_no": [1, 2], "content_hash": ["abc", "def"]})
    chunk2 = pd.DataFrame({"unique_no": [3, 4], "content_hash": ["ghi", "jkl"]})

    result = build_id_hash_map_from_chunks([chunk1, chunk2])

    assert result == {"1": "abc", "2": "def", "3": "ghi", "4": "jkl"}


# --- diff_id_hash_maps tests ---


def test_diff_id_hash_maps_detects_insert():
    # Confirms IDs only present in the source are marked as inserts.
    # Expects '2' to be categorized in the inserts set, else fails.
    source = {
        "1": "a",
        "2": "b",
    }

    ui = {
        "1": "a",
    }

    result = diff_id_hash_maps(
        source,
        ui,
    )

    assert result["inserts"] == {"2"}
    assert result["updates"] == set()
    assert result["deletes"] == set()
    assert result["unchanged"] == {"1"}


def test_diff_id_hash_maps_detects_delete():
    # Confirms IDs only present in the UI are marked as deletes.
    # Expects '2' to be categorized in the deletes set, else fails.
    source = {
        "1": "a",
    }

    ui = {
        "1": "a",
        "2": "b",
    }

    result = diff_id_hash_maps(
        source,
        ui,
    )

    assert result["deletes"] == {"2"}
    assert result["inserts"] == set()
    assert result["updates"] == set()
    assert result["unchanged"] == {"1"}


def test_diff_id_hash_maps_detects_update():
    # Confirms matching IDs with different hashes are marked as updates.
    # Expects '1' to be placed in the updates set due to the hash change, else fails.
    source = {
        "1": "new_hash",
    }

    ui = {
        "1": "old_hash",
    }

    result = diff_id_hash_maps(
        source,
        ui,
    )

    assert result["updates"] == {"1"}
    assert result["unchanged"] == set()


def test_diff_id_hash_maps_detects_unchanged_record():
    # Confirms matching IDs with identical hashes remain unchanged.
    # Expects '1' to be placed in the unchanged set, else fails.
    source = {
        "1": "same_hash",
    }

    ui = {
        "1": "same_hash",
    }

    result = diff_id_hash_maps(
        source,
        ui,
    )

    assert result["unchanged"] == {"1"}
    assert result["updates"] == set()


def test_diff_id_hash_maps_detects_all_change_types():
    # Confirms inserts, updates, deletes and unchanged records are identified together.
    # Expects each dictionary item to be sorted into the correct set based on logic, else fails.
    source = {
        "1": "same",
        "2": "changed",
        "3": "new",
    }

    ui = {
        "1": "same",
        "2": "old",
        "4": "removed",
    }

    result = diff_id_hash_maps(
        source,
        ui,
    )

    assert result["inserts"] == {"3"}
    assert result["updates"] == {"2"}
    assert result["deletes"] == {"4"}
    assert result["unchanged"] == {"1"}
