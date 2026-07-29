import pandas as pd
import pytest
from unittest.mock import patch

from etl.aggregation.counts import (
    aggregate_counts,
    suppress_low_counts,
)


# --- aggregate_counts tests ---

def test_aggregate_counts_raises_when_cell_size_not_set():
    # Confirms a missing reporting grid size raises ValueError.
    # Expects ValueError, else fails.
    df = pd.DataFrame()

    with pytest.raises(ValueError):
        aggregate_counts(
            df,
            easting_column="eastings",
            northing_column="northings",
            date_column="record_date",
            cell_size_m=None,
        )


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_counts_records_by_species_cell_and_year(
    mock_grid_square,
):
    # Confirms records are grouped by species, grid cell and year.
    # Expects one aggregated row with count 2, else fails.
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 1],
        "eastings": [100, 200],
        "northings": [300, 400],
        "record_date": ["01/01/2024", "15/06/2024"],
    })

    result = aggregate_counts(
        df,
        easting_column="eastings",
        northing_column="northings",
        date_column="record_date",
        cell_size_m=1000,
    )

    assert len(result) == 1
    assert result.loc[0, "species_no"] == 1
    assert result.loc[0, "grid_cell"] == "TQ27"
    assert result.loc[0, "year"] == 2024
    assert result.loc[0, "count"] == 2


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_drops_rows_with_missing_coordinates(
    mock_grid_square,
):
    # Confirms records missing coordinates are excluded.
    # Expects only one record to be counted, else fails.
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 1],
        "eastings": [100, pd.NA],
        "northings": [300, 400],
        "record_date": ["01/01/2024", "01/01/2024"],
    })

    result = aggregate_counts(
        df,
        "eastings",
        "northings",
        "record_date",
        1000,
    )

    assert result.loc[0, "count"] == 1


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_drops_invalid_dates(
    mock_grid_square,
):
    # Confirms invalid dates are excluded from aggregation.
    # Expects only valid dates to be counted, else fails.
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 1],
        "eastings": [100, 100],
        "northings": [200, 200],
        "record_date": ["01/01/2024", "not a date"],
    })

    result = aggregate_counts(
        df,
        "eastings",
        "northings",
        "record_date",
        1000,
    )

    assert result.loc[0, "count"] == 1


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_separates_species(
    mock_grid_square,
):
    # Confirms different species are aggregated separately.
    # Expects one row per species, else fails.
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 2],
        "eastings": [100, 100],
        "northings": [200, 200],
        "record_date": ["01/01/2024", "01/01/2024"],
    })

    result = aggregate_counts(
        df,
        "eastings",
        "northings",
        "record_date",
        1000,
    )

    assert len(result) == 2


# --- suppress_low_counts tests ---

def test_suppress_low_counts_raises_when_threshold_not_set():
    # Confirms a missing suppression threshold raises ValueError.
    # Expects ValueError, else fails.
    df = pd.DataFrame({
        "count": [1],
    })

    with pytest.raises(ValueError):
        suppress_low_counts(df, threshold=None)


def test_suppress_low_counts_suppresses_small_counts():
    # Confirms counts below the threshold are hidden.
    # Expects count to become pd.NA, else fails.
    df = pd.DataFrame({
        "count": [2],
    })

    result = suppress_low_counts(df, threshold=5)

    assert pd.isna(result.loc[0, "count"])
    assert result.loc[0, "suppressed"]


def test_suppress_low_counts_keeps_count_at_threshold():
    # Confirms counts exactly equal to the threshold are not suppressed.
    # Expects count unchanged, else fails.
    df = pd.DataFrame({
        "count": [5],
    })

    result = suppress_low_counts(df, threshold=5)

    assert result.loc[0, "count"] == 5
    assert not result.loc[0, "suppressed"]


def test_suppress_low_counts_keeps_large_counts():
    # Confirms counts above the threshold remain visible.
    # Expects count unchanged, else fails.
    df = pd.DataFrame({
        "count": [10],
    })

    result = suppress_low_counts(df, threshold=5)

    assert result.loc[0, "count"] == 10
    assert not result.loc[0, "suppressed"]


def test_suppress_low_counts_preserves_row_count():
    # Confirms suppression does not remove rows.
    # Expects the same number of rows, else fails.
    df = pd.DataFrame({
        "count": [1, 5, 10],
    })

    result = suppress_low_counts(df, threshold=5)

    assert len(result) == 3