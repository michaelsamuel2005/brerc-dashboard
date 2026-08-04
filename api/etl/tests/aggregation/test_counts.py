import pandas as pd
import pytest
from unittest.mock import patch

from etl.aggregation.counts import (
    aggregate_counts,
    suppress_low_counts,
)


# --- aggregate_counts tests ---

def test_aggregate_counts_uses_config_when_cell_size_not_provided():
    df = pd.DataFrame({
        "species_no": [123],
        "verified": [True],
        "eastings": [359234],
        "northings": [173456],
        "record_date": ["01/01/2020"],
    })

    result = aggregate_counts(
        filtered_df=df,
        verified_column="verified",
        easting_column="eastings",
        northing_column="northings",
        date_column="record_date",
        cell_size_m=None,
    )

    assert "grid_cell" in result.columns
    assert len(result) == 1


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_counts_records_by_species_cell_and_year(
    mock_grid_square,
):
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 1],
        "verified": [True, True],
        "eastings": [100, 200],
        "northings": [300, 400],
        "record_date": ["01/01/2024", "15/06/2024"],
    })

    result = aggregate_counts(
        df,
        verified_column="verified",
        easting_column="eastings",
        northing_column="northings",
        date_column="record_date",
        cell_size_m=1000,
    )

    assert len(result) == 1
    assert result.loc[0, "species_no"] == 1
    assert result.loc[0, "grid_cell"] == "TQ27"
    assert result.loc[0, "year"] == 2024
    assert result.loc[0, "record_count"] == 2
    assert result.loc[0, "verified_count"] == 2


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_drops_rows_with_missing_coordinates(
    mock_grid_square,
):
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 1],
        "verified": [True, True],
        "eastings": [100, pd.NA],
        "northings": [300, 400],
        "record_date": ["01/01/2024", "01/01/2024"],
    })

    result = aggregate_counts(
        df,
        verified_column="verified",
        easting_column="eastings",
        northing_column="northings",
        date_column="record_date",
        cell_size_m=1000,
    )

    assert result.loc[0, "record_count"] == 1


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_drops_invalid_dates(
    mock_grid_square,
):
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 1],
        "verified": [True, True],
        "eastings": [100, 100],
        "northings": [200, 200],
        "record_date": ["01/01/2024", "not a date"],
    })

    result = aggregate_counts(
        df,
        verified_column="verified",
        easting_column="eastings",
        northing_column="northings",
        date_column="record_date",
        cell_size_m=1000,
    )

    assert result.loc[0, "record_count"] == 1


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_separates_species(
    mock_grid_square,
):
    mock_grid_square.return_value = "TQ27"

    df = pd.DataFrame({
        "species_no": [1, 2],
        "verified": [True, True],
        "eastings": [100, 100],
        "northings": [200, 200],
        "record_date": ["01/01/2024", "01/01/2024"],
    })

    result = aggregate_counts(
        df,
        verified_column="verified",
        easting_column="eastings",
        northing_column="northings",
        date_column="record_date",
        cell_size_m=1000,
    )

    assert len(result) == 2


# --- suppress_low_counts tests ---

def test_suppress_low_counts_raises_when_threshold_not_set():

    df = pd.DataFrame({
        "record_count": [1],
    })

    with pytest.raises(ValueError):
        suppress_low_counts(df, threshold=None)


def test_suppress_low_counts_removes_small_counts():

    df = pd.DataFrame({
        "record_count": [2],
    })

    result = suppress_low_counts(
        df,
        threshold=5,
    )

    assert len(result) == 0


def test_suppress_low_counts_keeps_count_at_threshold():

    df = pd.DataFrame({
        "record_count": [5],
    })

    result = suppress_low_counts(
        df,
        threshold=5,
    )

    assert len(result) == 1
    assert result.loc[0, "record_count"] == 5


def test_suppress_low_counts_keeps_large_counts():

    df = pd.DataFrame({
        "record_count": [10],
    })

    result = suppress_low_counts(
        df,
        threshold=5,
    )

    assert len(result) == 1
    assert result.loc[0, "record_count"] == 10


def test_suppress_low_counts_preserves_visible_rows():

    df = pd.DataFrame({
        "record_count": [1, 5, 10],
    })

    result = suppress_low_counts(
        df,
        threshold=5,
    )

    assert len(result) == 2