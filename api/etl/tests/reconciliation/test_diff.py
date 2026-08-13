"""
Unit tests for reconciliation diffing and mapping utilities, 
verifying correct identification of inserts, updates, deletes, and unchanged records 
using date_mdb_modified timestamps.
"""

import pandas as pd
import pytest

from etl.reconciliation.diff import (
    build_id_hash_map,
    build_id_hash_map_from_chunks,
    build_id_modified_map,
    build_id_modified_map_from_chunks,
    diff_id_modified_maps,
)


# --- build_id_hash_map tests (Audit storage only) ---


def test_build_id_hash_map_returns_dictionary():
    # Confirms each unique_no is successfully mapped to its content hash.
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


def test_build_id_hash_map_from_chunks_merges_dictionaries():
    # Confirms chunked audit hash maps are correctly merged.
    chunk1 = pd.DataFrame({"unique_no": [1, 2], "content_hash": ["abc", "def"]})
    chunk2 = pd.DataFrame({"unique_no": [3, 4], "content_hash": ["ghi", "jkl"]})

    result = build_id_hash_map_from_chunks([chunk1, chunk2])

    assert result == {"1": "abc", "2": "def", "3": "ghi", "4": "jkl"}


# --- build_id_modified_map tests ---


def test_build_id_modified_map_returns_dictionary():
    # Confirms each unique_no is successfully mapped to its date_mdb_modified timestamp.
    df = pd.DataFrame(
        {
            "unique_no": [1, 2],
            "date_mdb_modified": ["2026-01-01", "2026-01-02"],
        }
    )

    result = build_id_modified_map(df)

    assert result == {
        "1": "2026-01-01",
        "2": "2026-01-02",
    }


def test_build_id_modified_map_raises_keyerror_missing_columns():
    # Confirms the function enforces the presence of necessary data columns.
    df = pd.DataFrame(
        {
            "unique_no": [1, 2],
            # Missing date_mdb_modified
        }
    )

    with pytest.raises(KeyError) as exc_info:
        build_id_modified_map(df)

    assert "Missing required columns" in str(exc_info.value)


# --- diff_id_modified_maps tests ---


def test_diff_id_modified_maps_detects_insert():
    # Confirms IDs only present in the source are marked as inserts.
    source = {
        "1": "2026-01-01",
        "2": "2026-01-02",
    }

    ui = {
        "1": "2026-01-01",
    }

    result = diff_id_modified_maps(
        source,
        ui,
    )

    assert result["inserts"] == {"2"}
    assert result["updates"] == set()
    assert result["deletes"] == set()
    assert result["unchanged"] == {"1"}


def test_diff_id_modified_maps_detects_delete():
    # Confirms IDs only present in the UI are marked as deletes.
    source = {
        "1": "2026-01-01",
    }

    ui = {
        "1": "2026-01-01",
        "2": "2026-01-02",
    }

    result = diff_id_modified_maps(
        source,
        ui,
    )

    assert result["deletes"] == {"2"}
    assert result["inserts"] == set()
    assert result["updates"] == set()
    assert result["unchanged"] == {"1"}


def test_diff_id_modified_maps_detects_update():
    # Confirms matching IDs with a newer source modification date are marked as updates.
    source = {
        "1": "2026-01-03",
    }

    ui = {
        "1": "2026-01-01",
    }

    result = diff_id_modified_maps(
        source,
        ui,
    )

    assert result["updates"] == {"1"}
    assert result["unchanged"] == set()


def test_diff_id_modified_maps_detects_unchanged_record():
    # Confirms matching IDs with identical modification dates remain unchanged.
    source = {
        "1": "2026-01-01",
    }

    ui = {
        "1": "2026-01-01",
    }

    result = diff_id_modified_maps(
        source,
        ui,
    )

    assert result["unchanged"] == {"1"}
    assert result["updates"] == set()


def test_diff_id_modified_maps_detects_all_change_types():
    # Confirms inserts, updates, deletes and unchanged records are identified together.
    source = {
        "1": "2026-01-01",  # unchanged
        "2": "2026-01-05",  # updated (newer date)
        "3": "2026-01-03",  # new insert
    }

    ui = {
        "1": "2026-01-01",
        "2": "2026-01-02",
        "4": "2026-01-01",  # removed (delete)
    }

    result = diff_id_modified_maps(
        source,
        ui,
    )

    assert result["inserts"] == {"3"}
    assert result["updates"] == {"2"}
    assert result["deletes"] == {"4"}
    assert result["unchanged"] == {"1"}