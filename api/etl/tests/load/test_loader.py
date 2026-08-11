import pandas as pd
import pytest
from unittest.mock import MagicMock, patch, call, mock_open

from etl.load.loader import (
    load_safety_config,
    initial_load,
    incremental_load,
    DEFAULT_CONFIG_PATH,
)

# --- load_safety_config tests ---

@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_uses_default_path(mock_file, mock_yaml):
    # Confirms the default path is used when no explicit path is provided.
    # Expects the file mock to be called with DEFAULT_CONFIG_PATH, else fails.
    
    mock_yaml.return_value = {"suppression_threshold": 5}
    
    result = load_safety_config()
    
    mock_file.assert_called_once_with(DEFAULT_CONFIG_PATH, "r")
    assert result == {"suppression_threshold": 5}


@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_uses_custom_path(mock_file, mock_yaml):
    # Confirms a custom path overrides the default.
    # Expects the file mock to be opened with the exact provided path, else fails.
    
    custom_path = "/custom/path/to/config.yaml"
    load_safety_config(path=custom_path)
    
    mock_file.assert_called_once_with(custom_path, "r")


# --- initial_load tests ---

def test_initial_load_truncates_and_copies_data():
    # Confirms initial_load wipes the table and uses psycopg's COPY to insert rows.
    # Expects TRUNCATE, COPY, write_row, and commit to be called in order, else fails.
    
    df = pd.DataFrame({
        "id": [1, 2],
        "species_name": ["Robin", "Blackbird"]
    })
    
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
    mock_copy = mock_cursor.copy.return_value.__enter__.return_value

    result = initial_load(df, connection=mock_connection, table_name="test_table")

    # 1. Check TRUNCATE was executed
    mock_cursor.execute.assert_called_once_with("TRUNCATE TABLE test_table;")
    
    # 2. Check COPY statement was formatted correctly
    mock_cursor.copy.assert_called_once_with("COPY test_table (id, species_name) FROM STDIN")
    
    # 3. Check exact rows were written to the copy context
    expected_rows = [
        call((1, "Robin")),
        call((2, "Blackbird"))
    ]
    mock_copy.write_row.assert_has_calls(expected_rows, any_order=False)
    
    # 4. Check the transaction was committed
    mock_connection.commit.assert_called_once()
    
    # 5. Check row count returned
    assert result == 2


def test_initial_load_handles_empty_dataframe():
    # Confirms initial_load safely executes TRUNCATE and COPY even if dataframe is empty.
    # Expects 0 to be returned and no write_row calls to be made, else fails.
    
    df = pd.DataFrame(columns=["id", "name"])
    
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
    mock_copy = mock_cursor.copy.return_value.__enter__.return_value

    result = initial_load(df, mock_connection, "empty_table")

    mock_cursor.execute.assert_called_once_with("TRUNCATE TABLE empty_table;")
    mock_cursor.copy.assert_called_once()
    mock_copy.write_row.assert_not_called()
    assert result == 0


# --- incremental_load tests ---

def test_incremental_load_executes_upsert():
    # Confirms incremental_load generates a valid INSERT ... ON CONFLICT DO UPDATE query.
    # Expects executemany to be called with the correct SQL and tuples, else fails.
    
    df = pd.DataFrame({
        "unique_id": [101, 102],
        "status": ["Verified", "Unconfirmed"],
        "count": [5, 1]
    })
    
    ui_map = {"primary_key": "unique_id"}
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value

    result = incremental_load(df, mock_connection, ui_map, "upsert_table")

    # Construct the exact SQL we expect the function to build
    expected_sql = (
        "INSERT INTO upsert_table (unique_id, status, count) VALUES (%s, %s, %s) "
        "ON CONFLICT (unique_id) DO UPDATE SET status = EXCLUDED.status, count = EXCLUDED.count"
    )
    
    expected_rows = [
        (101, "Verified", 5),
        (102, "Unconfirmed", 1)
    ]

    mock_cursor.executemany.assert_called_once_with(expected_sql, expected_rows)
    mock_connection.commit.assert_called_once()
    assert result == 2

def test_incremental_load_handles_single_column_table():
    # Confirms incremental_load doesn't break if the table only has a primary key.
    # With no non-primary-key columns to update, the upsert uses DO NOTHING.

    df = pd.DataFrame({
        "unique_id": [1, 2]
    })

    ui_map = {"primary_key": "unique_id"}
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value

    result = incremental_load(
        df,
        mock_connection,
        ui_map,
        "id_only_table",
    )

    expected_sql = (
        "INSERT INTO id_only_table (unique_id) VALUES (%s) "
        "ON CONFLICT (unique_id) DO NOTHING"
    )

    mock_cursor.executemany.assert_called_once_with(
        expected_sql,
        [(1,), (2,)],
    )
    assert result == 2