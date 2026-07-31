import pandas as pd

from etl.safety_gate.location import os_grid_square
from etl.aggregation.cell_filtering import filter_accepted_records
from etl.aggregation.species_index import build_species_index

from etl.config.loader import load_safety_config

CONFIG = load_safety_config() 

# Suppresses low-frequency observations to prevent revealing
# exact locations where only a small number of records exist.
# Counts below this threshold are hidden.
SUPPRESSION_THRESHOLD = CONFIG["aggregation"]["suppression_threshold"]

# Converts records into species x grid cell x year counts 
def aggregate_counts(
    filtered_df: pd.DataFrame,
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

    # Removes records without coordinates, these cannot be converted into grid cell
    df = df.dropna(
        subset=[
            easting_column,
            northing_column
        ]
    )

    # Convert each exact coordinate into its public grid square.
    # Prevents aggregation using precise locations
    # For current row, get easting and nothing row
    # Tells how big the grid should be 1km 
    # OS_grid_square returnd the Grid cell size
    df["grid_cell"] = df.apply(
        lambda row: os_grid_square(
            row[easting_column],
            row[northing_column],
            cell_size_m
        ),
        axis=1,
    )

    # Extract the year from the observation date
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
    )§§

    # Build species table from species that actually ppear in the records being loaded
    species_index = build_species_index(
        filtered_records
    )

    # Create species x cell x year counts
    aggregated = aggregate_counts(
        filtered_records,
        easting_column=easting_column,
        northing_column=northing_column,
        date_column=date_column,
        cell_size_m=cell_size_m,
    )

    # Suppresses counts that are too small
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

    if "count" not in aggregated_df.columns:
        raise KeyError(
            "Aggregation dataframe must contain count column"
        )
   
    if threshold is None:
        raise ValueError(
            "SUPPRESSION_THRESHOLD is not set - confirm BRERC's "
            "number before running this for real."
        )

    df = aggregated_df.copy()
    # Finds the cells that need hiding
    suppressed = df["count"] < threshold

    # Add flag stating those records are suppressed
    df["suppressed"] = suppressed
    # Replace the count with null
    df.loc[suppressed, "count"] = pd.NA

    return df