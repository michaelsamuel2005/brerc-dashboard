import pandas as pd

from etl.reconciliation.diff import (
    build_id_hash_map,
    diff_id_hash_maps,
    get_reconciliation_records,
)


def test_build_id_hash_map():
    df = pd.DataFrame({
        "unique_no": [1, 2, 3],
        "content_hash": ["hash_a", "hash_b", "hash_c"],
    })

    result = build_id_hash_map(df)

    assert result == {
        1: "hash_a",
        2: "hash_b",
        3: "hash_c",
    }


def test_diff_id_hash_maps_identifies_inserts_updates_deletes_and_unchanged():
    source_map = {
        1: "hash_a",       # unchanged
        2: "new_hash_b",   # updated
        3: "hash_c",       # inserted
    }

    ui_map = {
        1: "hash_a",       # unchanged
        2: "old_hash_b",   # updated
        4: "hash_d",       # deleted
    }

    result = diff_id_hash_maps(source_map, ui_map)

    assert result == {
        "inserts": {3},
        "updates": {2},
        "deletes": {4},
        "unchanged": {1},
    }


def test_get_reconciliation_records_selects_insert_and_update_rows():
    source_df = pd.DataFrame({
        "unique_no": [1, 2, 3],
        "scientific_name": [
            "Species unchanged",
            "Species updated",
            "Species inserted",
        ],
        "content_hash": [
            "hash_a",
            "new_hash_b",
            "hash_c",
        ],
    })

    changes = {
        "inserts": {3},
        "updates": {2},
        "deletes": {4},
        "unchanged": {1},
    }

    result = get_reconciliation_records(
        source_df,
        changes,
    )

    assert set(result["inserts"]["unique_no"]) == {3}

    assert set(result["updates"]["unique_no"]) == {2}

    assert result["deletes"] == {4}

    assert result["unchanged"] == {1}