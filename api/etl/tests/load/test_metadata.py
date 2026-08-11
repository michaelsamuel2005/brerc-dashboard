from datetime import datetime
import pandas as pd
import pytest
from unittest.mock import MagicMock

from etl.load.metadata import (  # Update with your actual module path if different
    add_load_metadata,
    get_last_load_date,
)

# --- add_load_metadata tests ---


def test_add_load_metadata_adds_columns():
    # Confirms ETL load metadata is attached to every row with the correct schema names.
    # Expects "Load" and "Load_date" columns to be populated correctly, else fails.
    df = pd.DataFrame(
        {
            "id": [1, 2],
        }
    )

    load_mode = "incremental"
    load_timestamp = datetime(2026, 8, 4, 12, 30, 0)

    result = add_load_metadata(
        df,
        load_mode,
        load_timestamp,
    )

    assert "Load" in result.columns
    assert "Load_date" in result.columns

    assert result["Load"].tolist() == [
        "incremental",
        "incremental",
    ]

    assert result["Load_date"].tolist() == [
        load_timestamp,
        load_timestamp,
    ]


def test_add_load_metadata_does_not_modify_original_dataframe():
    # Confirms the input dataframe is left unchanged (mutation check).
    # Expects the original dataframe to lack the metadata columns, else fails.
    df = pd.DataFrame(
        {
            "id": [1],
        }
    )

    add_load_metadata(
        df,
        "initial",
        datetime.now(),
    )

    assert "Load" not in df.columns
    assert "Load_date" not in df.columns


def test_add_load_metadata_preserves_existing_data():
    # Confirms existing columns and rows remain unchanged during metadata appending.
    # Expects original id and species data to remain perfectly intact, else fails.
    df = pd.DataFrame(
        {
            "id": [1],
            "species": ["Robin"],
        }
    )

    timestamp = datetime(2026, 8, 4)

    result = add_load_metadata(
        df,
        "initial",
        timestamp,
    )

    assert result["id"].tolist() == [1]
    assert result["species"].tolist() == ["Robin"]


# --- get_last_load_date tests ---


def test_get_last_load_date_returns_date_when_exists():
    # Confirms the function correctly retrieves the most recent watermark date.
    # Expects the exact datetime fetched from the database cursor to be returned, else fails.
    expected_date = datetime(2026, 8, 9, 10, 0, 0)

    # Setup mock connection and cursor returning a dictionary (like psycopg's DictRow)
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = {"last_load_date": expected_date}

    result = get_last_load_date(mock_connection)

    mock_cursor.execute.assert_called_once()
    assert (
        'SELECT MAX("Load_date") AS last_load_date'
        in mock_cursor.execute.call_args[0][0]
    )
    assert result == expected_date


def test_get_last_load_date_returns_none_when_empty():
    # Confirms the function returns None when the table is empty (no previous load).
    # Expects None to be returned, triggering a full initial load downstream, else fails.

    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = {"last_load_date": None}

    result = get_last_load_date(mock_connection)

    mock_cursor.execute.assert_called_once()
    assert result is None
