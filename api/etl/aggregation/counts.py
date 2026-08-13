"""Aggregates occurrence records into public spatial and temporal grids with privacy suppression."""

import pandas as pd

from etl.safety_gate.location import os_grid_square
from etl.aggregation.cell_filtering import (
    filter_accepted_records,
    _normalise_dashes,
    ACCEPTED_VERIFIED_VALUES,
)
from etl.aggregation.species_index import build_species_index
from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

# Suppresses low-frequency observations to prevent revealing
# exact locations where only a small number of records exist.
SUPPRESSION_THRESHOLD = CONFIG["aggregation"]["suppression_threshold"]


def aggregate_counts(
    filtered_df: pd.DataFrame,
    verified_column: str,
    easting_column: str,
    northing_column: str,
    date_column: str,
    cell_size_m=None,
) -> pd.DataFrame:
    """Converts accepted records into species x grid cell x year aggregated counts."""
    # Takes the grid size from the YAML
    if cell_size_m is None:
        cell_size_m = CONFIG["aggregation"]["cell_size_m"]

    required_columns = {
        "species_no",
        verified_column,
        easting_column,
        northing_column,
        date_column,
    }

    missing_columns = required_columns - set(filtered_df.columns)

    if missing_columns:
        raise KeyError(
            f"Missing columns required for aggregation: " f"{sorted(missing_columns)}"
        )

    df = filtered_df.copy()

    # Removes records without coordinates, can't be converted to cells
    df = df.dropna(
        subset=[
            easting_column,
            northing_column,
        ]
    )

    # Converts coordinate pairs into public grid square
    df["grid_cell"] = [
        os_grid_square(
            easting,
            northing,
            cell_size_m,
        )
        for easting, northing in zip(
            df[easting_column],
            df[northing_column],
        )
    ]

    # Remove records that could not be converted into a
    # valid public grid reference
    df = df.dropna(subset=["grid_cell"])

    # Store the south-west corner of each grid cell
    df["cell_sw_easting"] = (df[easting_column] // cell_size_m) * cell_size_m
    df["cell_sw_northing"] = (df[northing_column] // cell_size_m) * cell_size_m

    # Extract observation year
    df["year"] = pd.to_datetime(
        df[date_column],
        dayfirst=True,
        errors="coerce",
    ).dt.year

    df = df.dropna(subset=["year"])

    # Determine verification status
    sample_val = (
        df[verified_column].dropna().iloc[0]
        if not df[verified_column].dropna().empty
        else None
    )
    if pd.api.types.is_bool_dtype(df[verified_column]) or isinstance(sample_val, bool):
        df["is_verified"] = df[verified_column].fillna(False).astype(bool)
    else:
        normalized_verified = (
            df[verified_column]
            .astype("string")
            .str.strip()
            .map(lambda v: _normalise_dashes(v) if pd.notna(v) else v)
        )
        df["is_verified"] = normalized_verified.isin(ACCEPTED_VERIFIED_VALUES)

    # Group and aggregate counts by species, cell, and year
    aggregated = (
        df.groupby(
            [
                "species_no",
                "grid_cell",
                "year",
                "cell_sw_easting",
                "cell_sw_northing",
            ]
        )
        .agg(
            record_count=(
                "is_verified",
                "size",
            ),
            verified_count=(
                "is_verified",
                "sum",
            ),
        )
        .reset_index()
    )

    return aggregated

def suppress_low_counts(
    aggregated_df: pd.DataFrame,
    threshold: int = SUPPRESSION_THRESHOLD,
) -> pd.DataFrame:
    """Removes grid cell counts below the suppression threshold for privacy protection."""
    if "record_count" not in aggregated_df.columns:
        raise KeyError("Aggregation dataframe must contain record_count column")

    if threshold is None:
        raise ValueError(
            "SUPPRESSION_THRESHOLD is not set - confirm BRERC's "
            "number before running this for real."
        )

    df = aggregated_df.copy()
    visible_cells = df["record_count"] >= threshold
    return df[visible_cells].copy()


def build_public_aggregation(
    df: pd.DataFrame,
    verified_column: str,
    easting_column: str,
    northing_column: str,
    date_column: str,
    cell_size_m=None,
) -> dict:
    """ 
    Runs the complete public aggregation pipeline including:
    filtering, indexing, and suppression.
    """
    if cell_size_m is None:
        cell_size_m = CONFIG["aggregation"]["cell_size_m"]

    filtered_records = filter_accepted_records(
        df,
        verified_column=verified_column,
    )

    species_index = build_species_index(filtered_records)

    aggregated = aggregate_counts(
        filtered_records,
        verified_column=verified_column,
        easting_column=easting_column,
        northing_column=northing_column,
        date_column=date_column,
        cell_size_m=cell_size_m,
    )

    suppressed_counts = suppress_low_counts(
        aggregated,
        threshold=SUPPRESSION_THRESHOLD,
    )

    return {
        "aggregation": suppressed_counts,
        "species_index": species_index,
    }
