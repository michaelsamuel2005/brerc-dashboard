import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch

from etl.reconciliation.map_to_schema import (
    map_to_occurrence_public,
)

# --- map_to_occurrence_public tests ---


@patch("etl.reconciliation.map_to_schema.MODIFIED_COLUMN", "modified_date")
def test_map_to_occurrence_public_maps_columns_correctly():
    # Confirms all required columns are mapped and correctly transformed.
    # Expects the returned dataframe to match the target schema exactly, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [101, 102],
            "species_no": [" A123 ", 456],
            "record_year": [2022, 2023],
            "coarse_locality": ["ST56", "ST57"],
            "effective_resolution_m": [1000, 100],
            "is_legacy": [False, True],
            "content_hash": ["hash1", "hash2"],
            "modified_date": ["2022-08-15", "2023-01-01"],
        }
    )

    result = map_to_occurrence_public(df)

    assert list(result.columns) == [
        "record_id",
        "species_id",
        "record_year",
        "grid_ref",
        "locality",
        "precision_metres",
        "verified",
        "content_hash",
        "date_mdb_modified",
    ]

    assert result["record_id"].tolist() == [101, 102]
    # Confirms species_no is converted to string and stripped
    assert result["species_id"].tolist() == ["A123", "456"]
    assert result["record_year"].tolist() == [2022, 2023]
    assert result["grid_ref"].tolist() == ["ST56", "ST57"]
    assert result["locality"].tolist() == ["ST56", "ST57"]
    assert result["precision_metres"].tolist() == [1000, 100]
    # Confirms verified is the inverse of is_legacy
    assert result["verified"].tolist() == [True, False]
    assert result["content_hash"].tolist() == ["hash1", "hash2"]
    assert result["date_mdb_modified"].tolist() == ["2022-08-15", "2023-01-01"]


@patch("etl.reconciliation.map_to_schema.MODIFIED_COLUMN", "modified_date")
def test_map_to_occurrence_public_writes_years_as_whole_numbers():
    # Confirms years come out as whole numbers (2014, never "2014.0"), even when
    # the column arrives as floats because one value is missing.
    # Date parsing itself is tested in etl/tests/profiling/test_record_year.py.
    df = pd.DataFrame(
        {
            "unique_no": [1, 2],
            "species_no": ["1", "2"],
            "record_year": [2014.0, np.nan],
            "coarse_locality": ["ST56", "ST57"],
            "effective_resolution_m": [1000, 100],
            "is_legacy": [False, False],
            "content_hash": ["hash1", "hash2"],
            "modified_date": ["2023-01-01", "2023-01-02"],
        }
    )

    result = map_to_occurrence_public(df)

    assert str(result["record_year"].dtype) == "Int64"
    assert result["record_year"].iloc[0] == 2014
    assert pd.isna(result["record_year"].iloc[1])


@patch("etl.reconciliation.map_to_schema.MODIFIED_COLUMN", "modified_date")
def test_map_to_occurrence_public_does_not_modify_original_dataframe():
    # Confirms the input dataframe is left completely unchanged (mutation check).
    # Expects the original dataframe to lack the new mapped columns, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "species_no": [" 123 "],
            "record_year": [2022],
            "coarse_locality": ["ST56"],
            "effective_resolution_m": [1000],
            "is_legacy": [False],
            "content_hash": ["hash1"],
            "modified_date": ["2022-08-15"],
        }
    )

    map_to_occurrence_public(df)

    assert "record_id" not in df.columns
    assert "species_id" not in df.columns
    assert "date_mdb_modified" not in df.columns
    assert df["species_no"].tolist() == [" 123 "]  # Remains unstripped in original