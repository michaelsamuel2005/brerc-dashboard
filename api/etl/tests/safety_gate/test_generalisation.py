import pandas as pd
import pytest

from etl.safety_gate.generalisation import generalise_locations
from app.db import get_connection
from tests.conftest import needs_db


@pytest.fixture
def connection():
    with get_connection() as conn:
        yield conn


@needs_db
def test_generalise_locations_applies_resolution_tiers(connection):
    # Confirms effective_resolution_m:
    # - missing values default to 1000m
    # - values below the D0 floor are raised to 100m
    # - valid resolutions pass through unchanged.
    #
    # Expects [1000, 100, 1000, 100, 1000], else fails.

    df = pd.DataFrame({
        "easting": [359234] * 5,
        "northing": [173456] * 5,
        "resolution": [None, 50, 1000, 100, None],
    })

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert result["effective_resolution_m"].tolist() == [
        1000,
        100,
        1000,
        100,
        1000,
    ]

@needs_db
def test_generalise_locations_produces_coordinates_for_locatable_rows(connection):
    # Confirms rows with real easting/northing get a non-null longitude/latitude.
    # Expects all rows populated, else fails.
    df = pd.DataFrame({
        "easting": [359234],
        "northing": [173456],
        "resolution": [1000],
    })

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert result["longitude"].notna().all()
    assert result["latitude"].notna().all()


@needs_db
def test_generalise_locations_keeps_rows_with_missing_coordinates(connection, capsys):
    # Confirms rows with missing easting/northing are NOT dropped (D5 —
    # never silently drop), but get null longitude/latitude instead.
    # Expects 2 rows returned, row 1 has null lon/lat, else fails.
    df = pd.DataFrame({
        "easting": [359234, None],
        "northing": [173456, None],
        "resolution": [1000, 1000],
    })

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert len(result) == 2
    assert pd.isna(result["longitude"].iloc[1])
    assert pd.isna(result["latitude"].iloc[1])


@needs_db
def test_generalise_locations_preserves_original_row_order(connection):
    # Confirms output row order matches input order, even though the
    # function internally splits rows into locatable/excluded subsets.
    # Expects easting order unchanged, else fails.
    df = pd.DataFrame({
        "easting": [111111, 222222, 333333],
        "northing": [111111, 222222, 333333],
        "resolution": [1000, 1000, 1000],
    })

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert result["easting"].tolist() == [111111, 222222, 333333]