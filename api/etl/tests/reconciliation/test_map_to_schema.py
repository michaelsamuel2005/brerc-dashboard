import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch

from etl.reconciliation.map_to_schema import (
    map_to_occurrence_public,
)

# --- map_to_occurrence_public tests ---


@patch("etl.reconciliation.map_to_schema.DATE_COLUMN", "record_date")
def test_map_to_occurrence_public_maps_columns_correctly():
    # Confirms all required columns are mapped and correctly transformed.
    # Expects the returned dataframe to match the target schema exactly, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [101, 102],
            "species_no": [" A123 ", 456],
            "record_date": ["15/08/2022", "01/01/2023"],
            "coarse_locality": ["ST56", "ST57"],
            "effective_resolution_m": [1000, 100],
            "is_legacy": [False, True],
            "content_hash": ["hash1", "hash2"],
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


@patch("etl.reconciliation.map_to_schema.DATE_COLUMN", "record_date")
def test_map_to_occurrence_public_cleans_junk_dates():
    # Confirms junk prefixes on dates are ignored and the year is extracted correctly.
    # Expects the regex to extract the valid date portion and parse the year, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "species_no": ["1"],
            "record_date": [" - 17/10/2023"],  # Junk prefix
            "coarse_locality": ["ST56"],
            "effective_resolution_m": [1000],
            "is_legacy": [False],
            "content_hash": ["hash1"],
        }
    )

    result = map_to_occurrence_public(df)

    assert result["record_year"].tolist() == [2023]


@patch("etl.reconciliation.map_to_schema.DATE_COLUMN", "record_date")
def test_map_to_occurrence_public_handles_unparseable_dates():
    # Confirms genuinely invalid dates are coerced to NaN instead of crashing.
    # Expects the year for invalid dates to evaluate as null/NaN, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1, 2],
            "species_no": ["1", "2"],
            "record_date": ["Not a date", "99/99/9999"],
            "coarse_locality": ["ST56", "ST57"],
            "effective_resolution_m": [1000, 100],
            "is_legacy": [False, False],
            "content_hash": ["hash1", "hash2"],
        }
    )

    result = map_to_occurrence_public(df)

    # pandas parses invalid coerced dates to NaT (Not a Time), and dt.year becomes NaN (float)
    assert pd.isna(result["record_year"].iloc[0])
    assert pd.isna(result["record_year"].iloc[1])


@patch("etl.reconciliation.map_to_schema.DATE_COLUMN", "record_date")
def test_map_to_occurrence_public_does_not_modify_original_dataframe():
    # Confirms the input dataframe is left completely unchanged (mutation check).
    # Expects the original dataframe to lack the new mapped columns, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
            "species_no": [" 123 "],
            "record_date": ["15/08/2022"],
            "coarse_locality": ["ST56"],
            "effective_resolution_m": [1000],
            "is_legacy": [False],
            "content_hash": ["hash1"],
        }
    )

    map_to_occurrence_public(df)

    assert "record_id" not in df.columns
    assert "species_id" not in df.columns
    assert df["species_no"].tolist() == [" 123 "]  # Remains unstripped in original
