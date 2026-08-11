from datetime import datetime
import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock, patch, call, ANY

from etl.aggregation.persist import (
    to_python_none,
    persist_aggregation_outputs,
)

# --- to_python_none tests ---


def test_to_python_none_converts_pandas_na_to_none():
    result = to_python_none(pd.NA)
    assert result is None


def test_to_python_none_converts_numpy_nan_to_none():
    result = to_python_none(np.nan)
    assert result is None


def test_to_python_none_preserves_valid_values():
    assert to_python_none("Robin") == "Robin"
    assert to_python_none(42) == 42
    assert to_python_none(0) == 0


# --- persist_aggregation_outputs tests ---


@patch("etl.aggregation.persist.cell_polygon_wkt")
def test_persist_aggregation_outputs_executes_queries_in_order(mock_wkt):
    mock_wkt.return_value = "POLYGON((...))"
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value

    empty_species = pd.DataFrame(
        columns=[
            "species_id",
            "scientific_name",
            "common_name",
            "species_group",
            "record_count",
            "first_year",
            "last_year",
            "has_image",
        ]
    )
    empty_cells = pd.DataFrame(
        columns=[
            "grid_cell",
            "species_no",
            "year",
            "record_count",
            "verified_count",
            "cell_sw_easting",
            "cell_sw_northing",
        ]
    )

    persist_aggregation_outputs(
        connection=mock_connection,
        species_index=empty_species,
        suppressed_counts=empty_cells,
        cell_size_m=1000,
        load_mode="TEST",
    )

    calls = mock_cursor.mock_calls
    assert "TRUNCATE TABLE distribution_cell;" in calls[0].args[0]
    assert "INSERT INTO species" in calls[1].args[0]
    assert "DELETE FROM species" in calls[2].args[0]
    assert "INSERT INTO distribution_cell" in calls[3].args[0]
    mock_connection.commit.assert_called_once()


@patch("etl.aggregation.persist.cell_polygon_wkt")
def test_persist_aggregation_outputs_formats_species_tuples_correctly(mock_wkt):
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value

    species_df = pd.DataFrame(
        {
            "species_id": ["TAX123"],
            "scientific_name": ["Erithacus rubecula"],
            "common_name": [pd.NA],
            "species_group": ["Bird"],
            "record_count": [150],
            "first_year": [1990],
            "last_year": [2023],
            "has_image": [True],
        }
    )

    empty_cells = pd.DataFrame(
        columns=[
            "grid_cell",
            "species_no",
            "year",
            "record_count",
            "verified_count",
            "cell_sw_easting",
            "cell_sw_northing",
        ]
    )

    persist_aggregation_outputs(mock_connection, species_df, empty_cells, 1000, "TEST")

    species_insert_call = mock_cursor.executemany.call_args_list[0]
    inserted_rows = species_insert_call.args[1]

    assert len(inserted_rows) == 1
    row = inserted_rows[0]

    assert row[0] == "TAX123"
    assert row[2] is None
    assert isinstance(row[4], int) and row[4] == 150
    assert row[8] == "TEST"
    assert isinstance(row[9], datetime)


@patch("etl.aggregation.persist.cell_polygon_wkt")
def test_persist_aggregation_outputs_formats_cell_tuples_correctly(mock_wkt):
    mock_wkt.return_value = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
    mock_connection = MagicMock()
    mock_cursor = mock_connection.cursor.return_value.__enter__.return_value

    empty_species = pd.DataFrame(
        columns=[
            "species_id",
            "scientific_name",
            "common_name",
            "species_group",
            "record_count",
            "first_year",
            "last_year",
            "has_image",
        ]
    )

    cells_df = pd.DataFrame(
        {
            "grid_cell": ["ST1234"],
            "species_no": ["TAX123"],
            "year": [2020.0],
            "record_count": [5],
            "verified_count": [3],
            "cell_sw_easting": [1000],
            "cell_sw_northing": [2000],
        }
    )

    persist_aggregation_outputs(mock_connection, empty_species, cells_df, 1000, "TEST")

    cell_insert_call = mock_cursor.executemany.call_args_list[1]
    inserted_rows = cell_insert_call.args[1]

    assert len(inserted_rows) == 1
    row = inserted_rows[0]

    assert row[0] == "ST1234"
    assert row[1] == "TAX123"
    assert isinstance(row[2], int) and row[2] == 2020
    assert row[3] == 1000
    assert row[6] == "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
    mock_wkt.assert_called_once_with(1000, 2000, 1000)
