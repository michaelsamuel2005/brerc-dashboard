import pandas as pd

from etl.reconciliation.diff import (
    build_id_hash_map,
    diff_id_hash_maps,
)


# --- build_id_hash_map tests ---

def test_build_id_hash_map_returns_dictionary():
    """
    Confirms each unique_no is mapped to its content hash.
    IDs are stored as strings because database keys are TEXT.
    """

    df = pd.DataFrame({
        "unique_no": [1, 2],
        "content_hash": ["abc", "def"],
    })

    result = build_id_hash_map(df)

    assert result == {
        "1": "abc",
        "2": "def",
    }


def test_build_id_hash_map_returns_empty_dictionary_for_empty_dataframe():
    """
    Confirms an empty dataframe produces an empty dictionary.
    """

    df = pd.DataFrame(
        columns=[
            "unique_no",
            "content_hash",
        ]
    )

    result = build_id_hash_map(df)

    assert result == {}


# --- diff_id_hash_maps tests ---

def test_diff_id_hash_maps_detects_insert():
    """
    Confirms IDs only present in the source
    are marked as inserts.
    """

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
    """
    Confirms IDs only present in the UI
    are marked as deletes.
    """

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
    """
    Confirms matching IDs with different hashes
    are marked as updates.
    """

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
    """
    Confirms matching IDs with identical hashes
    remain unchanged.
    """

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
    """
    Confirms inserts, updates, deletes and unchanged
    records are identified together.
    """

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