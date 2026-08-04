import pandas as pd

from etl.safety_gate.location import os_grid_square
from etl.aggregation.cell_filtering import filter_accepted_records
from etl.aggregation.species_index import build_species_index

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

# Suppresses low-frequency observations to prevent revealing
# exact locations where only a small number of records exist.
# Counts below this threshold are removed from the public layer.
SUPPRESSION_THRESHOLD = CONFIG["aggregation"]["suppression_threshold"]


# Converts records into species x grid cell x year counts
def aggregate_counts(
    filtered_df: pd.DataFrame,
    verified_column: str,
    easting_column: str,
    northing_column: str,
    date_column: str,
    cell_size_m=None,
) -> pd.DataFrame:

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
            f"Missing columns required for aggregation: "
            f"{sorted(missing_columns)}"
        )

    df = filtered_df.copy()

    # Removes records without coordinates, these cannot be converted
    # into grid cells.
    df = df.dropna(
        subset=[
            easting_column,
            northing_column,
        ]
    )

    # Convert each coordinate pair into its public grid square.
    # Uses zip() instead of DataFrame.apply(axis=1).
    # apply(axis=1) creates a pandas Series object for every row,
    # which adds overhead when processing millions of records.
    #
    # zip() directly iterates through the coordinate columns,
    # reducing unnecessary pandas overhead.
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
    # valid public grid reference.
    df = df.dropna(
        subset=["grid_cell"]
    )

    # Store the south-west corner of each grid cell.
    #
    # This uses floor division so that every coordinate inside
    # the same grid square receives the same starting point.
    #
    # These values are later used to create the polygon geometry
    # stored in the database.
    df["cell_sw_easting"] = (
        df[easting_column] // cell_size_m
    ) * cell_size_m

    df["cell_sw_northing"] = (
        df[northing_column] // cell_size_m
    ) * cell_size_m

    # Extract the year from the observation date.
    # Invalid dates become NaN and are removed because they cannot
    # contribute to a species x cell x year count.
    df["year"] = (
        pd.to_datetime(
            df[date_column],
            dayfirst=True,
            errors="coerce",
        )
        .dt.year
    )

    df = df.dropna(
        subset=["year"]
    )

    # Convert verification status into a boolean value.
    # This allows aggregation to count only verified records.
    df["is_verified"] = (
        df[verified_column]
        .astype(bool)
    )

    # Count records by:
    #   - species
    #   - reporting grid cell
    #   - observation year
    #
    # Each row represents the number of observations of a species
    # within one grid square during one year.
    #
    # record_count:
    #   Total observations in that cell.
    #
    # verified_count:
    #   Number of verified observations contributing to the cell.
    aggregated = (
        df
        .groupby(
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


def build_public_aggregation(
    df: pd.DataFrame,
    verified_column: str,
    easting_column: str,
    northing_column: str,
    date_column: str,
    cell_size_m=None,
) -> dict:

    """
    Runs the complete B4 aggregation pipeline.

    Ensures only accepted records and marked legacy records
    contribute to public statistics.
    """

    if cell_size_m is None:
        cell_size_m = CONFIG["aggregation"]["cell_size_m"]

    # Remove rejected records before aggregation.
    # Only accepted records + legacy flagged records continue.
    filtered_records = filter_accepted_records(
        df,
        verified_column=verified_column,
    )

    # Build species table from species that actually appear
    # in the records being loaded.
    species_index = build_species_index(
        filtered_records
    )

    # Create species x cell x year counts.
    aggregated = aggregate_counts(
        filtered_records,
        verified_column=verified_column,
        easting_column=easting_column,
        northing_column=northing_column,
        date_column=date_column,
        cell_size_m=cell_size_m,
    )

    # Removes cells with very low counts.
    # Small counts can allow users to identify individual
    # sensitive records.
    suppressed_counts = suppress_low_counts(
        aggregated,
        threshold=SUPPRESSION_THRESHOLD,
    )

    return {
        "aggregation": suppressed_counts,
        "species_index": species_index,
    }


def suppress_low_counts(
    aggregated_df: pd.DataFrame,
    threshold: int = SUPPRESSION_THRESHOLD,
) -> pd.DataFrame:

    if "record_count" not in aggregated_df.columns:
        raise KeyError(
            "Aggregation dataframe must contain record_count column"
        )

    if threshold is None:
        raise ValueError(
            "SUPPRESSION_THRESHOLD is not set - confirm BRERC's "
            "number before running this for real."
        )

    df = aggregated_df.copy()

    # Finds cells with enough records to safely display.
    visible_cells = (
        df["record_count"] >= threshold
    )

    # Remove low-frequency cells entirely.
    # This prevents revealing that a sensitive record exists
    # at a specific location.
    return df[visible_cells].copy()