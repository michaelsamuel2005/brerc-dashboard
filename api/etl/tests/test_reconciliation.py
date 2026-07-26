import pandas as pd

from etl.reconciliation.hashing import (
    get_reconciliation_records,
)


def test_get_reconciliation_records():

    source_df = pd.DataFrame({
        "unique_no": ["A", "B", "C"],
        "scientific_name": [
            "Species A",
            "Species B",
            "Species C",
        ],
        "content_hash": [
            "hash_a",
            "hash_new",
            "hash_same",
        ],
    })

    changes = {
        "inserts": {"A"},
        "updates": {"B"},
        "deletes": {"D"},
        "unchanged": {"C"},
    }

    result = get_reconciliation_records(
        source_df,
        changes,
    )

    assert result["inserts"]["unique_no"].tolist() == ["A"]

    assert result["updates"]["unique_no"].tolist() == ["B"]

    assert result["deletes"] == {"D"}

    assert result["unchanged"] == {"C"}