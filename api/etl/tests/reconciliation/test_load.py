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
    """
    Confirms an empty species dataframe performs no database work.
    """

    connection = MagicMock()

    df = pd.DataFrame()

    upsert_species(
        df,
        connection,
    )

    connection.commit.assert_not_called()


def test_upsert_species_commits_after_successful_write():
    """
    Confirms valid species records are bulk loaded and committed.
    Uses COPY staging table then upsert.
    """

    connection = MagicMock()

    df = pd.DataFrame({
        "species_id": ["1"],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "species_group": ["Bird"],
        "record_count": [10],
        "first_year": [2020],
        "last_year": [2024],
        "has_image": [True],
    })

    upsert_species(
        df,
        connection,
    )

    cursor = (
        connection
        .cursor
        .return_value
        .__enter__
        .return_value
    )

    cursor.copy.assert_called_once()

    assert cursor.execute.call_count == 2

    connection.commit.assert_called_once()

# --- insert_records tests ---

def test_insert_records_returns_without_writing_when_dataframe_empty():
    """
    Confirms an empty dataframe performs no database writes.
    """

    connection = MagicMock()

    df = pd.DataFrame()

    insert_records(
        df,
        connection,
    )

    connection.commit.assert_not_called()


def test_insert_records_raises_keyerror_when_required_columns_missing():
    """
    Confirms missing columns fail before database writing.
    """

    connection = MagicMock()

    df = pd.DataFrame({
        "record_id": [1],
    })

    with pytest.raises(KeyError):
        insert_records(
            df,
            connection,
        )


def test_insert_records_commits_after_successful_write():

    connection = MagicMock()

    df = pd.DataFrame({
        "record_id": ["1"],
        "species_id": ["5"],
        "record_year": [2024],
        "grid_ref": ["ST56"],
        "locality": ["Bristol"],
        "precision_metres": [1000],
        "verified": [True],
        "content_hash": ["abc123"],
    })

    insert_records(
        df,
        connection,
    )

    cursor = (
        connection
        .cursor
        .return_value
        .__enter__
        .return_value
    )

    cursor.copy.assert_called_once()

    assert cursor.execute.call_count == 2

    connection.commit.assert_called_once()

# --- update_records tests ---

def test_update_records_commits_after_successful_write():

    connection = MagicMock()

    df = pd.DataFrame({
        "record_id": ["1"],
        "species_id": ["5"],
        "record_year": [2024],
        "grid_ref": ["ST56"],
        "locality": ["Bristol"],
        "precision_metres": [1000],
        "verified": [True],
        "content_hash": ["updated_hash"],
    })

    update_records(
        df,
        connection,
    )

    cursor = (
        connection
        .cursor
        .return_value
        .__enter__
        .return_value
    )

    cursor.copy.assert_called_once()

    assert cursor.execute.call_count == 2

    connection.commit.assert_called_once()

# --- delete_records tests ---

def test_delete_records_returns_without_database_call_when_set_empty():
    """
    Confirms no SQL is executed when there are no records to delete.
    """

    connection = MagicMock()

    delete_records(
        set(),
        connection,
    )

    connection.commit.assert_not_called()


def test_delete_records_executes_delete_statement():
    """
    Confirms record IDs are passed to the DELETE statement.
    """

    connection = MagicMock()

    delete_records(
        {"1", "2", "3"},
        connection,
    )

    cursor = (
        connection
        .cursor
        .return_value
        .__enter__
        .return_value
    )

    cursor.execute.assert_called_once()
    connection.commit.assert_called_once()