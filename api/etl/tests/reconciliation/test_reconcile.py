import pandas as pd
from unittest.mock import MagicMock, patch

from etl.reconciliation.reconcile import reconcile


def test_reconcile_returns_changes():
    """
    Confirms reconcile returns the diff summary.
    """

    changes = {
        "inserts": set(),
        "updates": set(),
        "deletes": set(),
        "unchanged": set(),
    }

    with patch(
        "etl.reconciliation.reconcile.build_source_hash_map",
        return_value={}
    ), patch(
        "etl.reconciliation.reconcile.diff_id_hash_maps",
        return_value=changes
    ), patch(
        "etl.reconciliation.reconcile.iter_source_chunks",
        return_value=[]
    ), patch(
        "etl.reconciliation.reconcile.delete_records"
    ):

        result = reconcile(
            pd.DataFrame(),
            {},
            MagicMock(),
        )

    assert result == changes


def test_reconcile_processes_insert_records():
    """
    Confirms new records:
    - are passed through make_safe_for_publishing
    - are written using insert_records
    """

    insert_df = pd.DataFrame(
        {
            "unique_no": ["1"],
            "verified": [True],
            "scientific_name": ["Test species"],
        }
    )

    safe_df = pd.DataFrame(
        {
            "record_id": ["1"]
        }
    )

    changes = {
        "inserts": {"1"},
        "updates": set(),
        "deletes": set(),
        "unchanged": set(),
    }

    connection = MagicMock()

    with patch(
        "etl.reconciliation.reconcile.build_source_hash_map",
        return_value={"1": "abc"}
    ), patch(
        "etl.reconciliation.reconcile.diff_id_hash_maps",
        return_value=changes
    ), patch(
        "etl.reconciliation.reconcile.iter_source_chunks",
        return_value=[insert_df]
    ), patch(
        "etl.reconciliation.reconcile.make_safe_for_publishing",
        return_value=safe_df
    ) as mock_safe, patch(
        "etl.reconciliation.reconcile.insert_records"
    ) as mock_insert, patch(
        "etl.reconciliation.reconcile.delete_records"
    ), patch(
        "etl.reconciliation.reconcile.filter_accepted_records",
        return_value=pd.DataFrame()
    ), patch(
        "etl.reconciliation.reconcile.resolve_species_numbers",
        return_value=pd.DataFrame()
    ), patch(
        "etl.reconciliation.reconcile.build_species_index",
        return_value=pd.DataFrame()
    ), patch(
        "etl.reconciliation.reconcile.upsert_species"
    ):

        reconcile(
            pd.DataFrame(),
            {},
            connection,
        )

    mock_safe.assert_called_once()

    mock_insert.assert_called_once_with(
        safe_df,
        connection,
    )


def test_reconcile_processes_update_records():
    """
    Confirms modified records:
    - are passed through safety processing
    - are written using update_records
    """

    update_df = pd.DataFrame(
        {
            "unique_no": ["2"],
            "verified": [True],
            "scientific_name": ["Test species"],
        }
    )

    safe_df = pd.DataFrame(
        {
            "record_id": ["2"]
        }
    )

    changes = {
        "inserts": set(),
        "updates": {"2"},
        "deletes": set(),
        "unchanged": set(),
    }

    connection = MagicMock()

    with patch(
        "etl.reconciliation.reconcile.build_source_hash_map",
        return_value={"2": "xyz"}
    ), patch(
        "etl.reconciliation.reconcile.diff_id_hash_maps",
        return_value=changes
    ), patch(
        "etl.reconciliation.reconcile.iter_source_chunks",
        return_value=[update_df]
    ), patch(
        "etl.reconciliation.reconcile.make_safe_for_publishing",
        return_value=safe_df
    ) as mock_safe, patch(
        "etl.reconciliation.reconcile.update_records"
    ) as mock_update, patch(
        "etl.reconciliation.reconcile.delete_records"
    ), patch(
        "etl.reconciliation.reconcile.filter_accepted_records",
        return_value=pd.DataFrame()
    ), patch(
        "etl.reconciliation.reconcile.resolve_species_numbers",
        return_value=pd.DataFrame()
    ), patch(
        "etl.reconciliation.reconcile.build_species_index",
        return_value=pd.DataFrame()
    ), patch(
        "etl.reconciliation.reconcile.upsert_species"
    ):

        reconcile(
            pd.DataFrame(),
            {},
            connection,
        )

    mock_update.assert_called_once_with(
        safe_df,
        connection,
    )


def test_reconcile_deletes_removed_records():
    """
    Confirms records missing from the source
    are deleted from occurrence_public.
    """

    changes = {
        "inserts": set(),
        "updates": set(),
        "deletes": {"999"},
        "unchanged": set(),
    }

    connection = MagicMock()

    with patch(
        "etl.reconciliation.reconcile.build_source_hash_map",
        return_value={}
    ), patch(
        "etl.reconciliation.reconcile.diff_id_hash_maps",
        return_value=changes
    ), patch(
        "etl.reconciliation.reconcile.iter_source_chunks",
        return_value=[]
    ), patch(
        "etl.reconciliation.reconcile.delete_records"
    ) as mock_delete:

        reconcile(
            pd.DataFrame(),
            {},
            connection,
        )

    mock_delete.assert_called_once_with(
        {"999"},
        connection,
    )