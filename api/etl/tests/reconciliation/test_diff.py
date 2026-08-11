import pandas as pd

from etl.reconciliation.diff import (
    build_id_hash_map,
    diff_id_hash_maps,
    get_reconciliation_records,
)


# --- build_id_hash_map tests ---

def test_build_id_hash_map_returns_dictionary():
    # Confirms each unique_no is mapped to its content hash.
    # Expects a dictionary of ID -> hash, else fails.
    df = pd.DataFrame({
        "unique_no": [1, 2],
        "content_hash": ["abc", "def"],
    })

    result = build_id_hash_map(df)

    assert result == {
        1: "abc",
        2: "def",
    }


def test_build_id_hash_map_returns_empty_dictionary_for_empty_dataframe():
    # Confirms an empty DataFrame produces an empty dictionary.
    # Expects {}, else fails.
    df = pd.DataFrame(columns=["unique_no", "content_hash"])

    result = build_id_hash_map(df)

    assert result == {}


# --- diff_id_hash_maps tests ---

def test_diff_id_hash_maps_detects_insert():
    # Confirms IDs present only in the source are marked as inserts.
    # Expects ID 2 in inserts, else fails.
    source = {
        1: "a",
        2: "b",
    }

    ui = {
        1: "a",
    }

    result = diff_id_hash_maps(source, ui)

    assert result["inserts"] == {2}
    assert result["updates"] == set()
    assert result["deletes"] == set()
    assert result["unchanged"] == {1}


def test_diff_id_hash_maps_detects_delete():
    # Confirms IDs present only in the UI are marked as deletes.
    # Expects ID 2 in deletes, else fails.
    source = {
        1: "a",
    }

    ui = {
        1: "a",
        2: "b",
    }

    result = diff_id_hash_maps(source, ui)

    assert result["deletes"] == {2}
    assert result["inserts"] == set()
    assert result["updates"] == set()
    assert result["unchanged"] == {1}


def test_diff_id_hash_maps_detects_update():
    # Confirms matching IDs with different hashes are marked as updates.
    # Expects ID 1 in updates, else fails.
    source = {
        1: "new_hash",
    }

    ui = {
        1: "old_hash",
    }

    result = diff_id_hash_maps(source, ui)

    assert result["updates"] == {1}
    assert result["unchanged"] == set()


def test_diff_id_hash_maps_detects_unchanged_record():
    # Confirms matching IDs with identical hashes remain unchanged.
    # Expects ID 1 in unchanged, else fails.
    source = {
        1: "same_hash",
    }

    ui = {
        1: "same_hash",
    }

    result = diff_id_hash_maps(source, ui)

    assert result["unchanged"] == {1}
    assert result["updates"] == set()


def test_diff_id_hash_maps_detects_all_change_types():
    # Confirms inserts, updates, deletes and unchanged records
    # are all identified in one comparison.
    source = {
        1: "same",
        2: "changed",
        3: "new",
    }

    ui = {
        1: "same",
        2: "old",
        4: "removed",
    }

    result = diff_id_hash_maps(source, ui)

    assert result["inserts"] == {3}
    assert result["updates"] == {2}
    assert result["deletes"] == {4}
    assert result["unchanged"] == {1}


# --- get_reconciliation_records tests ---

def test_get_reconciliation_records_returns_insert_rows():
    # Confirms rows marked for insertion are returned.
    # Expects only the inserted row, else fails.
    df = pd.DataFrame({
        "unique_no": [1, 2],
        "content_hash": ["a", "b"],
    })

    changes = {
        "inserts": {2},
        "updates": set(),
        "deletes": set(),
        "unchanged": {1},
    }

    result = get_reconciliation_records(df, changes)

    assert list(result["inserts"]["unique_no"]) == [2]


def test_get_reconciliation_records_returns_update_rows():
    # Confirms rows marked for update are returned.
    # Expects only the updated row, else fails.
    df = pd.DataFrame({
        "unique_no": [1, 2],
        "content_hash": ["a", "b"],
    })

    changes = {
        "inserts": set(),
        "updates": {1},
        "deletes": set(),
        "unchanged": {2},
    }

    result = get_reconciliation_records(df, changes)

    assert list(result["updates"]["unique_no"]) == [1]


def test_get_reconciliation_records_preserves_delete_ids():
    # Confirms delete IDs are passed through unchanged.
    # Expects the same delete set, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "content_hash": ["a"],
    })

    changes = {
        "inserts": set(),
        "updates": set(),
        "deletes": {5},
        "unchanged": set(),
    }

    result = get_reconciliation_records(df, changes)

    assert result["deletes"] == {5}


def test_get_reconciliation_records_preserves_unchanged_ids():
    # Confirms unchanged IDs are passed through unchanged.
    # Expects the same unchanged set, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "content_hash": ["a"],
    })

    changes = {
        "inserts": set(),
        "updates": set(),
        "deletes": set(),
        "unchanged": {1},
    }

    result = get_reconciliation_records(df, changes)

    assert result["unchanged"] == {1}


def test_get_reconciliation_records_returns_empty_dataframes_when_no_changes():
    # Confirms no insert/update rows are returned when there are
    # no reconciliation changes.
    # Expects empty insert and update DataFrames, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "content_hash": ["a"],
    })

    changes = {
        "inserts": set(),
        "updates": set(),
        "deletes": set(),
        "unchanged": {1},
    }

    result = get_reconciliation_records(df, changes)

    assert result["inserts"].empty
    assert result["updates"].empty