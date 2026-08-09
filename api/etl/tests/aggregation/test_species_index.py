import pandas as pd
import pytest

from etl.aggregation.species_index import build_species_index

# --- build_species_index tests ---

def test_build_species_index_creates_one_row_per_species():
    # Confirms one output row is created for each unique species.
    # Expects two species rows, else fails.
    df = pd.DataFrame({
        "unique_no": [1, 2],
        "species_no": [10, 20],
        "scientific_name": ["Robin", "Blackbird"],
        "common_name": ["Robin", "Blackbird"],
        "taxanb": ["Bird", "Bird"],
        "date_of_record": ["01/01/2024", "01/01/2024"],
    })

    result = build_species_index(df)

    assert len(result) == 2


def test_build_species_index_counts_records_per_species():
    # Confirms record_count is the number of records for each species.
    # Expects record_count of 2, else fails.
    df = pd.DataFrame({
        "unique_no": [1, 2],
        "species_no": [10, 10],
        "scientific_name": ["Robin", "Robin"],
        "common_name": ["Robin", "Robin"],
        "taxanb": ["Bird", "Bird"],
        "date_of_record": ["01/01/2024", "02/01/2024"],
    })

    result = build_species_index(df)

    assert result.loc[0, "record_count"] == 2


def test_build_species_index_calculates_first_and_last_year():
    # Confirms first_year and last_year are calculated correctly.
    # Expects 2022 and 2024, else fails.
    df = pd.DataFrame({
        "unique_no": [1, 2, 3],
        "species_no": [10, 10, 10],
        "scientific_name": ["Robin"] * 3,
        "common_name": ["Robin"] * 3,
        "taxanb": ["Bird"] * 3,
        "date_of_record": [
            "01/01/2022",
            "01/01/2024",
            "01/01/2023",
        ],
    })

    result = build_species_index(df)

    assert result.loc[0, "first_year"] == 2022
    assert result.loc[0, "last_year"] == 2024


def test_build_species_index_renames_columns():
    # Confirms database column names are produced.
    # Expects species_id and species_group columns, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "species_no": [10],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "taxanb": ["Bird"],
        "date_of_record": ["01/01/2024"],
    })

    result = build_species_index(df)

    assert "species_id" in result.columns
    assert "species_group" in result.columns
    assert "species_no" not in result.columns
    assert "taxanb" not in result.columns


def test_build_species_index_sets_has_image_false():
    # Confirms all species default to has_image=False.
    # Expects False, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "species_no": [10],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "taxanb": ["Bird"],
        "date_of_record": ["01/01/2024"],
    })

    result = build_species_index(df)

    assert result.loc[0, "has_image"] == False


def test_build_species_index_preserves_missing_species_group():
    # Confirms missing species_group values are retained rather than dropped.
    # Expects one output row with a missing species_group, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "species_no": [10],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "taxanb": [pd.NA],
        "date_of_record": ["01/01/2024"],
    })

    result = build_species_index(df)

    assert len(result) == 1
    assert pd.isna(result.loc[0, "species_group"])


def test_build_species_index_returns_expected_columns():
    # Confirms only the expected database columns are returned.
    # Expects the correct column order, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "species_no": [10],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "taxanb": ["Bird"],
        "date_of_record": ["01/01/2024"],
    })

    result = build_species_index(df)

    assert list(result.columns) == [
        "species_id",
        "scientific_name",
        "common_name",
        "species_group",
        "record_count",
        "first_year",
        "last_year",
        "has_image",
    ]


def test_build_species_index_raises_error_on_missing_columns():
    # Confirms a missing required column safely halts execution.
    # Expects a KeyError to be raised, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "scientific_name": ["Robin"],
    })

    with pytest.raises(KeyError, match="Missing columns required for species index"):
        build_species_index(df)


def test_build_species_index_drops_missing_species_no():
    # Confirms records without a species_no are excluded from the index.
    # Expects empty dataframe output, else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "species_no": [pd.NA],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "taxanb": ["Bird"],
        "date_of_record": ["01/01/2024"],
    })

    result = build_species_index(df)

    assert len(result) == 0


def test_build_species_index_raises_error_on_duplicate_species_id():
    # Confirms conflicting metadata mapping to the same species ID raises an error.
    # Expects a ValueError to be raised, else fails.
    df = pd.DataFrame({
        "unique_no": [1, 2],
        "species_no": [10, 10],  # Same ID
        "scientific_name": ["Robin", "Different Robin"],  # Different metadata creates two groups
        "common_name": ["Robin", "Robin"],
        "taxanb": ["Bird", "Bird"],
        "date_of_record": ["01/01/2024", "01/01/2024"],
    })

    with pytest.raises(ValueError, match="Species index contains duplicate species IDs"):
        build_species_index(df)


def test_build_species_index_handles_invalid_dates():
    # Confirms unparseable dates do not break the aggregation.
    # Expects first_year and last_year to be missing (pd.NA), else fails.
    df = pd.DataFrame({
        "unique_no": [1],
        "species_no": [10],
        "scientific_name": ["Robin"],
        "common_name": ["Robin"],
        "taxanb": ["Bird"],
        "date_of_record": ["invalid_date_string"],
    })

    result = build_species_index(df)

    assert len(result) == 1
    assert pd.isna(result.loc[0, "first_year"])
    assert pd.isna(result.loc[0, "last_year"])