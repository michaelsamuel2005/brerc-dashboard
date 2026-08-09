from datetime import datetime
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch, call

from etl.aggregation.rebuild_species import (  
    rebuild_species_index,
)

# --- rebuild_species_index tests ---

@patch("etl.aggregation.rebuild_species.pd.read_sql")
@patch("etl.aggregation.rebuild_species.upsert_species")
def test_rebuild_species_index_returns_early_if_empty(mock_upsert, mock_read_sql):
    # Confirms the process safely aborts if there are no records in the public table.
    # Expects upsert_species to NOT be called, else fails.
    
    # Simulate an empty table returned from the database
    mock_read_sql.return_value = pd.DataFrame(
        columns=["species_id", "scientific_name", "record_year"]
    )
    mock_connection = MagicMock()

    rebuild_species_index(
        connection=mock_connection, 
        load_mode="initial"
    )

    mock_read_sql.assert_called_once()
    mock_upsert.assert_not_called()


@patch("etl.aggregation.rebuild_species.pd.read_sql")
@patch("etl.aggregation.rebuild_species.upsert_species")
def test_rebuild_species_index_calculates_aggregations_correctly(mock_upsert, mock_read_sql):
    # Confirms record counts, first year, and last year are calculated accurately per species.
    # Expects grouped metrics to match the simulated data limits, else fails.
    
    mock_read_sql.return_value = pd.DataFrame({
        "species_id": ["TAX1", "TAX1", "TAX1", "TAX2"],
        "scientific_name": ["Species A", "Species A", "Species A", "Species B"],
        "record_year": [2010, 2015, 2020, 2022]
    })
    mock_connection = MagicMock()

    rebuild_species_index(
        connection=mock_connection, 
        load_mode="incremental"
    )

    # Capture the dataframe that was passed into upsert_species
    args, kwargs = mock_upsert.call_args
    result_df = args[0]
    
    # TAX1 should have 3 records, min year 2010, max year 2020
    tax1_row = result_df[result_df["species_id"] == "TAX1"].iloc[0]
    assert tax1_row["record_count"] == 3
    assert tax1_row["first_year"] == 2010
    assert tax1_row["last_year"] == 2020

    # TAX2 should have 1 record, min/max year 2022
    tax2_row = result_df[result_df["species_id"] == "TAX2"].iloc[0]
    assert tax2_row["record_count"] == 1
    assert tax2_row["first_year"] == 2022
    assert tax2_row["last_year"] == 2022


@patch("etl.aggregation.rebuild_species.pd.read_sql")
@patch("etl.aggregation.rebuild_species.upsert_species")
def test_rebuild_species_index_applies_default_columns(mock_upsert, mock_read_sql):
    # Confirms fields not available in the public table are safely populated with defaults.
    # Expects common_name=None, species_group='unknown', has_image=False, else fails.
    
    mock_read_sql.return_value = pd.DataFrame({
        "species_id": ["TAX1"],
        "scientific_name": ["Species A"],
        "record_year": [2020]
    })
    mock_connection = MagicMock()

    rebuild_species_index(
        connection=mock_connection, 
        load_mode="initial"
    )

    args, kwargs = mock_upsert.call_args
    result_df = args[0]
    row = result_df.iloc[0]

    assert row["common_name"] is None
    assert row["species_group"] == "unknown"
    assert row["has_image"] == False
    
    # Also verify column ordering is exactly as expected
    expected_columns = [
        "species_id", "scientific_name", "common_name", "species_group",
        "record_count", "first_year", "last_year", "has_image"
    ]
    assert list(result_df.columns) == expected_columns


@patch("etl.aggregation.rebuild_species.pd.read_sql")
@patch("etl.aggregation.rebuild_species.upsert_species")
def test_rebuild_species_index_passes_through_timestamp_and_mode(mock_upsert, mock_read_sql):
    # Confirms custom load_timestamp and load_mode are correctly passed to the upsert function.
    # Expects upsert_species to receive the exact provided keyword arguments, else fails.
    
    mock_read_sql.return_value = pd.DataFrame({
        "species_id": ["TAX1"],
        "scientific_name": ["Species A"],
        "record_year": [2020]
    })
    mock_connection = MagicMock()
    custom_time = datetime(2026, 8, 9, 12, 0, 0)

    rebuild_species_index(
        connection=mock_connection, 
        load_mode="incremental",
        load_timestamp=custom_time
    )

    mock_upsert.assert_called_once()
    args, kwargs = mock_upsert.call_args
    
    # Confirm the kwargs are passed verbatim
    assert kwargs["load_mode"] == "incremental"
    assert kwargs["load_timestamp"] == custom_time