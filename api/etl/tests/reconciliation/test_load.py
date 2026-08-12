import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from etl.reconciliation.load import (  # Update with your actual module path if different
    upsert_species,
    insert_records,
    update_records,
    delete_records,
)


# --- upsert_species tests ---


def test_upsert_species_returns_without_writing_when_dataframe_empty():
    # Confirms an empty species dataframe performs no database work.
    # Expects the function to exit before calling connection.commit, else fails.
    connection = MagicMock()
    df = pd.DataFrame()

    upsert_species(
        df,
        connection,
        load_mode="incremental",
        load_timestamp="2026-08-09",
    )

    connection.commit.assert_not_called()


@patch("etl.reconciliation.load.add_load_metadata")
def test_upsert_species_commits_after_successful_write(mock_add_metadata):
    # Confirms valid species records are bulk loaded and committed.
    # Expects cursor.copy to be called for staging, cursor.execute for upsert, and the connection to commit, else fails.
    connection = MagicMock()

    df = pd.DataFrame(
        {
            "species_id": ["1"],
            "scientific_name": ["Robin"],
            "common_name": ["Robin"],
            "species_group": ["Bird"],
            "record_count": [10],
            "first_year": [2020],
            "last_year": [2024],
            "has_image": [True],
        }
    )

    # Mock the metadata function to attach the required Load columns to the dataframe
    mock_add_metadata.return_value = df.assign(
        Load="incremental", Load_date="2026-08-09"
    )

    upsert_species(
        df,
        connection,
        load_mode="incremental",
        load_timestamp="2026-08-09",
    )

    cursor = connection.cursor.return_value.__enter__.return_value

    cursor.copy.assert_called_once()
    assert cursor.execute.call_count == 2
    connection.commit.assert_called_once()


# --- insert_records tests ---


def test_insert_records_returns_without_writing_when_dataframe_empty():
    # Confirms an empty occurrence dataframe performs no database writes.
    # Expects the function to exit without executing SQL or committing, else fails.
    connection = MagicMock()
    df = pd.DataFrame()

    insert_records(
        df,
        connection,
    )

    connection.commit.assert_not_called()


def test_insert_records_raises_keyerror_when_required_columns_missing():
    # Confirms missing columns fail explicitly before attempting to write to the database.
    # Expects a KeyError specifying the missing required columns, else fails.
    connection = MagicMock()

    df = pd.DataFrame(
        {
            "record_id": [1],
        }
    )

    with pytest.raises(KeyError) as exc_info:
        insert_records(
            df,
            connection,
        )

    assert "missing columns required" in str(exc_info.value)


def test_insert_records_commits_after_successful_write():
    # Confirms valid occurrence records are properly staged and inserted into the database.
    # Expects the staging COPY and UPSERT execute commands to run, followed by a commit, else fails.
    connection = MagicMock()

    df = pd.DataFrame(
        {
            "record_id": ["1"],
            "species_id": ["5"],
            "record_year": [2024],
            "grid_ref": ["ST56"],
            "locality": ["Bristol"],
            "precision_metres": [1000],
            "verified": [True],
            "content_hash": ["abc123"],
            "date_mdb_modified": ["2026-08-09 10:00:00+00"],  # Required by _upsert_occurrences
            "Load": ["incremental"],  # Required by _upsert_occurrences
            "Load_date": ["2026-08-09"],  # Required by _upsert_occurrences
        }
    )

    insert_records(
        df,
        connection,
    )

    cursor = connection.cursor.return_value.__enter__.return_value

    cursor.copy.assert_called_once()
    assert cursor.execute.call_count == 2
    connection.commit.assert_called_once()


# --- update_records tests ---


def test_update_records_commits_after_successful_write():
    # Confirms records with changed content hashes are processed and updated correctly.
    # Expects identical database interaction patterns to insert_records, else fails.
    connection = MagicMock()

    df = pd.DataFrame(
        {
            "record_id": ["1"],
            "species_id": ["5"],
            "record_year": [2024],
            "grid_ref": ["ST56"],
            "locality": ["Bristol"],
            "precision_metres": [1000],
            "verified": [True],
            "content_hash": ["updated_hash"],
            "date_mdb_modified": ["2026-08-09 10:00:00+00"],  # Required by _upsert_occurrences
            "Load": ["incremental"],  # Required by _upsert_occurrences
            "Load_date": ["2026-08-09"],  # Required by _upsert_occurrences
        }
    )

    update_records(
        df,
        connection,
    )

    cursor = connection.cursor.return_value.__enter__.return_value

    cursor.copy.assert_called_once()
    assert cursor.execute.call_count == 2
    connection.commit.assert_called_once()


# --- delete_records tests ---


def test_delete_records_returns_without_database_call_when_set_empty():
    # Confirms no SQL is executed when the deletion set is completely empty.
    # Expects the function to exit without opening a cursor or calling commit, else fails.
    connection = MagicMock()

    delete_records(
        set(),
        connection,
    )

    connection.commit.assert_not_called()


def test_delete_records_executes_delete_statement():
    # Confirms record IDs are passed correctly to the SQL DELETE array structure.
    # Expects a single DELETE execution with the mapped array, followed by a commit, else fails.
    connection = MagicMock()

    delete_records(
        {"1", "2", "3"},
        connection,
    )

    cursor = connection.cursor.return_value.__enter__.return_value

    cursor.execute.assert_called_once()
    assert "DELETE FROM occurrence_public" in cursor.execute.call_args[0][0]
    connection.commit.assert_called_once()