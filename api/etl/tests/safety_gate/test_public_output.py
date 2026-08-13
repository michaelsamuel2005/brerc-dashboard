import pandas as pd
import pytest

from etl.safety_gate.public_output import (  # Update with your actual module path if different
    PUBLIC_COLUMNS,
    FORBIDDEN_COLUMNS,
    add_coarse_locality,
    prepare_public_output,
)

# --- add_coarse_locality tests ---


def test_add_coarse_locality_adds_grid_reference():
    # Confirms coarse_locality is successfully created from snapped coordinates.
    # Expects a valid OS grid square string, else fails.
    df = pd.DataFrame(
        {
            "snapped_easting": [529090],
            "snapped_northing": [179645],
        }
    )

    result = add_coarse_locality(df)

    assert result.loc[0, "coarse_locality"] == "TQ27"


def test_add_coarse_locality_returns_na_for_missing_coordinates():
    # Confirms missing coordinates produce pd.NA rather than crashing.
    # Expects pd.NA in the coarse_locality field, else fails.
    df = pd.DataFrame(
        {
            "snapped_easting": [pd.NA],
            "snapped_northing": [179645],
        }
    )

    result = add_coarse_locality(df)

    assert pd.isna(result.loc[0, "coarse_locality"])


def test_add_coarse_locality_preserves_existing_columns():
    # Confirms the function adds coarse_locality without removing existing columns.
    # Expects all original columns plus coarse_locality to be present, else fails.
    df = pd.DataFrame(
        {
            "snapped_easting": [529090],
            "snapped_northing": [179645],
            "unique_no": [1],
        }
    )

    result = add_coarse_locality(df)

    assert "unique_no" in result.columns
    assert "coarse_locality" in result.columns


def test_add_coarse_locality_raises_valueerror_for_missing_columns():
    # Confirms the function enforces the presence of required coordinate columns.
    # Expects a ValueError to be raised if easting or northing columns are missing, else fails.
    df = pd.DataFrame(
        {
            "snapped_easting": [529090],
            # Missing snapped_northing
        }
    )

    with pytest.raises(ValueError) as exc_info:
        add_coarse_locality(df)

    assert "Missing coordinate columns" in str(exc_info.value)


# --- prepare_public_output tests ---


def test_prepare_public_output_returns_only_public_columns():
    # Confirms only PUBLIC_COLUMNS are retained and internal columns are removed.
    # Expects the returned columns to match PUBLIC_COLUMNS exactly, else fails.
    row = {
        "unique_no": 1,
        "species_no": 100,
        "scientific_name": "Test species",
        "record_type": "Observation",
        "longitude": -2.5,
        "latitude": 51.5,
        "coarse_locality": "TQ27",
        "effective_resolution_m": 1000,
        "date_of_record": "2024-01-01",
        "is_legacy": False,
        "comments": "Secret",
        "easting": 529090,
        "northing": 179645,
    }

    df = pd.DataFrame([row])

    result = prepare_public_output(df)

    assert list(result.columns) == PUBLIC_COLUMNS
    assert "comments" not in result.columns
    assert "easting" not in result.columns
    assert "northing" not in result.columns


def test_prepare_public_output_raises_for_missing_required_column():
    # Confirms missing required public columns raise KeyError rather than incomplete output.
    # Expects a KeyError specifying the missing columns, else fails.
    df = pd.DataFrame(
        {
            "unique_no": [1],
        }
    )

    with pytest.raises(KeyError) as exc_info:
        prepare_public_output(df)

    assert "Missing required public columns" in str(exc_info.value)


def test_prepare_public_output_drops_rows_with_missing_longitude():
    # Confirms records missing longitude are removed from the public output.
    # Expects an empty dataframe to be returned, else fails.
    row = {
        "unique_no": 1,
        "species_no": 100,
        "scientific_name": "Test species",
        "record_type": "Observation",
        "longitude": pd.NA,
        "latitude": 51.5,
        "coarse_locality": "TQ27",
        "effective_resolution_m": 1000,
        "date_of_record": "2024-01-01",
        "is_legacy": False,
    }

    df = pd.DataFrame([row])

    result = prepare_public_output(df)

    assert len(result) == 0


def test_prepare_public_output_drops_rows_with_missing_latitude():
    # Confirms records missing latitude are removed from the public output.
    # Expects an empty dataframe to be returned, else fails.
    row = {
        "unique_no": 1,
        "species_no": 100,
        "scientific_name": "Test species",
        "record_type": "Observation",
        "longitude": -2.5,
        "latitude": pd.NA,
        "coarse_locality": "TQ27",
        "effective_resolution_m": 1000,
        "date_of_record": "2024-01-01",
        "is_legacy": False,
    }

    df = pd.DataFrame([row])

    result = prepare_public_output(df)

    assert len(result) == 0


def test_prepare_public_output_preserves_valid_record():
    # Confirms a complete valid record survives the public output boundary unchanged.
    # Expects 1 row retained with correct data, else fails.
    row = {
        "unique_no": 42,
        "species_no": 100,
        "scientific_name": "Test species",
        "record_type": "Observation",
        "longitude": -2.5,
        "latitude": 51.5,
        "coarse_locality": "TQ27",
        "effective_resolution_m": 1000,
        "date_of_record": "2024-01-01",
        "is_legacy": False,
    }

    df = pd.DataFrame([row])

    result = prepare_public_output(df)

    assert len(result) == 1
    assert result.loc[0, "unique_no"] == 42
    assert result.loc[0, "scientific_name"] == "Test species"


# --- constant tests ---


def test_public_and_forbidden_columns_do_not_overlap():
    # Confirms no forbidden column can ever be accidentally exposed in the public API.
    # Expects the set intersection between PUBLIC_COLUMNS and FORBIDDEN_COLUMNS to be empty, else fails.
    overlap = set(PUBLIC_COLUMNS) & FORBIDDEN_COLUMNS

    assert overlap == set()
