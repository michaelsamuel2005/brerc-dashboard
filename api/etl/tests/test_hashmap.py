from etl.reconciliation.hashing import diff_id_hash_maps

def test_diff_id_hash_maps():
    source_map = {
        "A": "hash_a",       # new
        "B": "hash_new",     # changed
        "C": "hash_same",    # unchanged
    }

    ui_map = {
        "B": "hash_old",
        "C": "hash_same",
        "D": "hash_d",       # deleted from source
    }

    result = diff_id_hash_maps(source_map, ui_map)

    assert result["inserts"] == {"A"}
    assert result["updates"] == {"B"}
    assert result["deletes"] == {"D"}
    assert result["unchanged"] == {"C"}