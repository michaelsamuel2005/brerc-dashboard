import pandas as pd
import pytest
from unittest.mock import MagicMock

from etl.reconciliation.load import (
    upsert_species,
    insert_records,
    update_records,
    delete_records,
)


# --- upsert_species tests ---

def test_upsert_species_returns_without_writing_when_dataframe_empty():
    # Confirms an empty species DataFrame performs no database work.
    # Expects no commit, else fails.
    connection = MagicMock()

    df = pd.DataFrame()

    upsert_species(df, connection)

    connection.commit.assert_not_called()


def test_upsert_species_commits_after_successful_write():
    # Confirms valid species records are written and committed.
    # Expects one commit, else fails.
    connection = MagicMock()

    df = pd.DataFrame({
        "species_id": [1],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "species_group": ["Bird"],
        "record_count": [10],
        "first_year": [2020],
        "last_year": [2024],
        "has_image": [True],
    })

    upsert_species(df, connection)

    connection.cursor.return_value.__enter__.return_value.executemany.assert_called_once()
    connection.commit.assert_called_once()


# --- insert_records tests ---

def test_insert_records_returns_without_writing_when_dataframe_empty():
    # Confirms an empty DataFrame performs no database writes.
    # Expects no commit, else fails.
    connection = MagicMock()

    df = pd.DataFrame()

    insert_records(df, connection)

    connection.commit.assert_not_called()


def test_insert_records_raises_keyerror_when_required_columns_missing():
    # Confirms missing required columns raise KeyError rather than
    # attempting an invalid database write.
    connection = MagicMock()

    df = pd.DataFrame({
        "record_id": [1],
    })

    with pytest.raises(KeyError):
        insert_records(df, connection)


def test_insert_records_commits_after_successful_write():
    # Confirms valid records are written and committed.
    # Expects executemany() and commit() to be called once.
    connection = MagicMock()

    df = pd.DataFrame({
        "record_id": [1],
        "species_id": [5],
        "record_year": [2024],
        "grid_ref": ["ST56"],
        "locality": ["Bristol"],
        "precision_metres": [1000],
        "verified": [True],
        "content_hash": ["abc123"],
    })

    insert_records(df, connection)

    connection.cursor.return_value.__enter__.return_value.executemany.assert_called_once()
    connection.commit.assert_called_once()


# --- update_records tests ---

def test_update_records_commits_after_successful_write():
    # Confirms updates use the same upsert logic and commit.
    # Expects executemany() and commit() to be called once.
    connection = MagicMock()

    df = pd.DataFrame({
        "record_id": [1],
        "species_id": [5],
        "record_year": [2024],
        "grid_ref": ["ST56"],
        "locality": ["Bristol"],
        "precision_metres": [1000],
        "verified": [True],
        "content_hash": ["updated_hash"],
    })

    update_records(df, connection)

    connection.cursor.return_value.__enter__.return_value.executemany.assert_called_once()
    connection.commit.assert_called_once()


# --- delete_records tests ---

def test_delete_records_returns_without_database_call_when_set_empty():
    # Confirms no SQL is executed when there are no records to delete.
    # Expects no commit, else fails.
    connection = MagicMock()

    delete_records(set(), connection)

    connection.commit.assert_not_called()


def test_delete_records_executes_delete_statement():
    # Confirms record IDs are passed to the DELETE statement.
    # Expects execute() and commit() to be called once.
    connection = MagicMock()

    delete_records({1, 2, 3}, connection)

    connection.cursor.return_value.__enter__.return_value.execute.assert_called_once()
    connection.commit.assert_called_once()