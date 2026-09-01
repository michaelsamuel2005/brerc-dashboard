import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from etl.aggregation.counts import (
    SUPPRESSION_THRESHOLD,
    suppress_low_counts,
    aggregate_counts,
    build_public_aggregation,
)


def test_legacy_example_matches_safe_v1_k1_without_becoming_release_authority():
    assert SUPPRESSION_THRESHOLD == 1

# --- suppress_low_counts tests ---


def test_suppress_low_counts_keeps_records_above_threshold():
    df = pd.DataFrame({"record_count": [10, 5, 2], "grid_cell": ["A1", "B2", "C3"]})
    result = suppress_low_counts(df, threshold=5)
    assert len(result) == 2
    assert "C3" not in result["grid_cell"].values


def test_suppress_low_counts_removes_records_below_threshold():
    df = pd.DataFrame({"record_count": [4, 1], "grid_cell": ["A1", "B2"]})
    result = suppress_low_counts(df, threshold=5)
    assert len(result) == 0


def test_suppress_low_counts_raises_error_on_missing_column():
    df = pd.DataFrame({"grid_cell": ["A1", "B2"]})
    with pytest.raises(KeyError, match="must contain record_count column"):
        suppress_low_counts(df, threshold=5)


def test_suppress_low_counts_raises_error_on_none_threshold():
    df = pd.DataFrame({"record_count": [10, 5]})
    with pytest.raises(ValueError, match="SUPPRESSION_THRESHOLD is not set"):
        suppress_low_counts(df, threshold=None)


# --- aggregate_counts tests ---


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_calculates_correct_totals(mock_grid_square):
    mock_grid_square.return_value = "ST1234"
    df = pd.DataFrame(
        {
            "species_no": [1, 1],
            "verified": [True, False],
            "easting": [1050, 1060],
            "northing": [2050, 2060],
            "date": ["01/01/2020", "15/06/2020"],
        }
    )
    result = aggregate_counts(
        df, "verified", "easting", "northing", "date", cell_size_m=1000
    )
    assert len(result) == 1
    assert result.loc[0, "record_count"] == 2
    assert result.loc[0, "verified_count"] == 1
    assert result.loc[0, "year"] == 2020


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_drops_missing_coordinates(mock_grid_square):
    df = pd.DataFrame(
        {
            "species_no": [1],
            "verified": [True],
            "easting": [pd.NA],
            "northing": [2050],
            "date": ["01/01/2020"],
        }
    )
    result = aggregate_counts(
        df, "verified", "easting", "northing", "date", cell_size_m=1000
    )
    assert len(result) == 0


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_drops_invalid_dates(mock_grid_square):
    mock_grid_square.return_value = "ST1234"
    df = pd.DataFrame(
        {
            "species_no": [1],
            "verified": [True],
            "easting": [1050],
            "northing": [2050],
            "date": ["invalid_date_string"],
        }
    )
    result = aggregate_counts(
        df, "verified", "easting", "northing", "date", cell_size_m=1000
    )
    assert len(result) == 0


@patch("etl.aggregation.counts.os_grid_square")
def test_aggregate_counts_calculates_cell_sw_corners(mock_grid_square):
    mock_grid_square.return_value = "ST1234"
    df = pd.DataFrame(
        {
            "species_no": [1],
            "verified": [True],
            "easting": [1567],
            "northing": [2999],
            "date": ["01/01/2020"],
        }
    )
    result = aggregate_counts(
        df, "verified", "easting", "northing", "date", cell_size_m=1000
    )
    assert result.loc[0, "cell_sw_easting"] == 1000
    assert result.loc[0, "cell_sw_northing"] == 2000


def test_aggregate_counts_raises_keyerror_on_missing_columns():
    df = pd.DataFrame({"species_no": [1], "easting": [1000]})
    with pytest.raises(KeyError, match="Missing columns required for aggregation"):
        aggregate_counts(df, "verified", "easting", "northing", "date", 1000)


# --- build_public_aggregation tests ---


@patch("etl.aggregation.counts.filter_accepted_records")
@patch("etl.aggregation.counts.build_species_index")
@patch("etl.aggregation.counts.aggregate_counts")
@patch("etl.aggregation.counts.suppress_low_counts")
def test_build_public_aggregation_orchestrates_pipeline(
    mock_suppress, mock_aggregate, mock_species_index, mock_filter
):
    mock_filter.return_value = pd.DataFrame()
    mock_species_index.return_value = {"species_1": "Robin"}
    mock_aggregate.return_value = pd.DataFrame()
    mock_suppress.return_value = pd.DataFrame({"suppressed": [True]})

    df = pd.DataFrame()
    result = build_public_aggregation(
        df, "verified", "easting", "northing", "date", cell_size_m=1000
    )

    assert "aggregation" in result
    assert "species_index" in result
    mock_filter.assert_called_once()
    mock_species_index.assert_called_once()
    mock_aggregate.assert_called_once()
    mock_suppress.assert_called_once()
