"""
    B4: species x cell x year aggregation, species index, D5
    low-count suppression.

    filter_accepted_records / build_species_index are yours - used
    as-is here, not reimplemented.

    TODO before this runs for real:
      - SUPPRESSION_THRESHOLD (BRERC's number, not yet given)
      - CELL_SIZE_M (product decision, not yet confirmed)
      - confirm whether blank `verified` should count as legacy
        (currently does, per filter_accepted_records) - flagged for
        the project/mentor check
"""

import pandas as pd

from etl.safety_gate.location import os_grid_square

SUPPRESSION_THRESHOLD = None           # TODO: BRERC's number - not yet given

def aggregate_counts(
    filtered_df: pd.DataFrame,
    easting_column: str,
    northing_column: str,
    date_column: str,
    cell_size_m: int,
) -> pd.DataFrame:
    """
    Counts by species_no x grid cell x year. Full recompute each
    run - no incremental diffing here, unlike B3.
    """

    if cell_size_m is None:
        raise ValueError(
            "CELL_SIZE_M is not set - confirm the reporting grid "
            "size before running this for real."
        )

    df = filtered_df.copy()


    # Remove records where location cannot be converted into
    # a reporting grid cell. These cannot contribute to the
    # spatial aggregation safely.
    df = df.dropna(
        subset=[
            easting_column,
            northing_column
        ]
    )


    # Convert precise eastings/northings into the reporting grid.
    # This ensures aggregation happens against the public-facing
    # spatial unit rather than exact coordinates.
    df["grid_cell"] = df.apply(
        lambda row: os_grid_square(
            row[easting_column],
            row[northing_column],
            cell_size_m
        ),
        axis=1,
    )


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


    # Count records by:
    #   - species
    #   - reporting grid cell
    #   - observation year
    #
    # Each row represents the number of observations of a species
    # within one grid square during one year.
    aggregated = (
        df
        .groupby(
            [
                "species_no",
                "grid_cell",
                "year",
            ]
        )
        .size()
        .reset_index(
            name="count"
        )
    )


    return aggregated

def suppress_low_counts(
    aggregated_df: pd.DataFrame,
    threshold: int = SUPPRESSION_THRESHOLD,
) -> pd.DataFrame:
    """
    D5: any (species, cell, year) group with count < threshold gets
    its exact count hidden - so a count of 1 (or any small number)
    can never be read straight off the dashboard. Suppressed rows
    keep count as null rather than being dropped, so callers can
    still show "present, not shown" instead of nothing at all.

    NOTE: boundary is currently strict "<" - a count exactly AT
    threshold is shown, not suppressed. Confirm with BRERC whether
    it should be "<=" instead before relying on this in production.
    """
    if threshold is None:
        raise ValueError(
            "SUPPRESSION_THRESHOLD is not set - confirm BRERC's "
            "number before running this for real."
        )

    df = aggregated_df.copy()
    suppressed = df["count"] < threshold

    df["suppressed"] = suppressed
    df.loc[suppressed, "count"] = pd.NA

    return df