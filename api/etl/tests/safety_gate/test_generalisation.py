import pandas as pd
import pytest

from etl.db import get_destination_connection
from etl.safety_gate.generalisation import (
    generalise_locations,
)  # Update with your actual module path if different
from etl.tests.conftest import needs_db


@pytest.fixture
def connection():
    with get_destination_connection() as conn:
        yield conn


@needs_db
def test_generalise_locations_applies_resolution_tiers(connection):
    # Confirms effective_resolution_m handles missing, below-floor, and valid values.
    # Expects [1000.0, 100.0, 1000.0, 100.0, 1000.0] based on the yaml config defaults, else fails.
    df = pd.DataFrame(
        {
            "easting": [359234] * 5,
            "northing": [173456] * 5,
            "resolution": [None, 50, 1000, 100, None],
        }
    )

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert result["effective_resolution_m"].tolist() == [
        1000.0,  # Default sensitive resolution fallback
        100.0,  # Raised to D0 floor
        1000.0,  # Valid passthrough
        100.0,  # Valid passthrough
        1000.0,  # Default sensitive resolution fallback
    ]


@needs_db
def test_generalise_locations_produces_coordinates_for_locatable_rows(connection):
    # Confirms rows with real easting/northing get a non-null longitude/latitude.
    # Expects all rows to be successfully populated by the PostGIS conversion, else fails.
    df = pd.DataFrame(
        {
            "easting": [359234],
            "northing": [173456],
            "resolution": [1000],
        }
    )

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert result["longitude"].notna().all()
    assert result["latitude"].notna().all()
    assert result["snapped_easting"].notna().all()
    assert result["snapped_northing"].notna().all()


@needs_db
def test_generalise_locations_keeps_rows_with_missing_coordinates(connection, capsys):
    # Confirms rows with missing easting/northing are NOT dropped, but receive null coordinates.
    # Expects 2 rows returned with the missing record carrying null lon/lat, else fails.
    df = pd.DataFrame(
        {
            "easting": [359234, None],
            "northing": [173456, None],
            "resolution": [1000, 1000],
        }
    )

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert len(result) == 2
    assert pd.notna(result["longitude"].iloc[0])
    assert pd.isna(result["longitude"].iloc[1])
    assert pd.isna(result["latitude"].iloc[1])


@needs_db
def test_generalise_locations_preserves_original_row_order(connection):
    # Confirms output row order matches input order despite internal locatable/excluded subset splits.
    # Expects easting order to remain exactly unchanged from the input dataframe, else fails.
    df = pd.DataFrame(
        {
            "easting": [111111, 222222, 333333],
            "northing": [111111, 222222, 333333],
            "resolution": [1000, 1000, 1000],
        }
    )

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert result["easting"].tolist() == [111111, 222222, 333333]


def test_generalise_locations_raises_valueerror_for_missing_connection():
    # Confirms the function enforces a valid database connection for PostGIS access.
    # Expects a ValueError to be raised before processing begins, else fails.
    df = pd.DataFrame({"easting": [1], "northing": [1], "resolution": [1]})

    with pytest.raises(ValueError) as exc_info:
        generalise_locations(
            df=df,
            connection=None,
            easting_column="easting",
            northing_column="northing",
            resolution_column="resolution",
        )

    assert "PostGIS database connection is required" in str(exc_info.value)


def test_generalise_locations_raises_valueerror_for_missing_columns():
    # Confirms the function enforces the presence of required coordinate columns.
    # Expects a ValueError specifying the missing columns to be raised, else fails.
    connection = "dummy_connection"
    df = pd.DataFrame({"easting": [1]})  # Missing northing and resolution

    with pytest.raises(ValueError) as exc_info:
        generalise_locations(
            df=df,
            connection=connection,
            easting_column="easting",
            northing_column="northing",
            resolution_column="resolution",
        )

    assert "Missing required columns" in str(exc_info.value)
    assert "northing" in str(exc_info.value)
