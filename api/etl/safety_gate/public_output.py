import pandas as pd
import logging

from etl.safety_gate.location import os_grid_square

logger = logging.getLogger(__name__)

# Matches occurrence_public (db/b6_schema.sql) + the API contract's
# public fields (species_id, precision_metres are shown to users -
# see /api/species, /api/distribution/cells in the contract §10).
PUBLIC_COLUMNS = [
    "unique_no",
    "species_no",             # public - shown as speciesId in the contract
    "scientific_name",
    "record_type",
    "longitude",
    "latitude",
    "coarse_locality",
    "effective_resolution_m", # public - shown as precisionMetres in the contract
    "date_of_record",
    "is_legacy",
]

# Genuinely never allowed past the boundary - precise location, free
# text, personal data, and INTERNAL classification machinery that
# reveals why/whether a record was flagged sensitive (is_sensitive,
# sensitivity_reason would tell an adversary which records to target).
FORBIDDEN_COLUMNS = {
    "place",
    "comments",
    "easting",
    "northing",
    "grid_reference",
    "recorder_name",
    "sensitivity_reason",
    "is_sensitive",
    "nbn_number",
}


def _validate_public_columns() -> None:
    forbidden = set(PUBLIC_COLUMNS) & FORBIDDEN_COLUMNS

    if forbidden:
        raise ValueError(
            f"Forbidden columns found in PUBLIC_COLUMNS: {forbidden}"
        )

_validate_public_columns()

def add_coarse_locality(
    df: pd.DataFrame,
    easting_column: str = "snapped_easting",
    northing_column: str = "snapped_northing",
) -> pd.DataFrame:

    df = df.copy()

    required = {
        easting_column,
        northing_column,
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing coordinate columns: {missing}"
        )

    coarse_localities = []

    # Loops through each coordinate pair
    # zip() - pairs two coordinate columns together
    for easting, northing in zip(
        df[easting_column],
        df[northing_column],
    ):
        # If coordinate exist create grid reference, else store missing value
        if pd.notna(easting) and pd.notna(northing):
            coarse_localities.append(
                os_grid_square(easting, northing)
            )
        else:
            coarse_localities.append(pd.NA)

    # Adds returned list to DF column
    df["coarse_locality"] = coarse_localities

    # Returns updated dataframe
    return df


def prepare_public_output(df: pd.DataFrame) -> pd.DataFrame:
    missing = [
        column
        for column in PUBLIC_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise KeyError(
            f"Missing required public columns: {missing}"
        )

    public_df = df[PUBLIC_COLUMNS].copy()

    no_coordinates = (
        public_df["longitude"].isna()
        | public_df["latitude"].isna()
    )

    if no_coordinates.any():
        logger.warning(
            "Dropping %s public records with no coordinates.",
            no_coordinates.sum(),
        )

    # Public maps cannot display records without coordinates.
    # These are removed only at the final output boundary.
    return (
        public_df
        .loc[~no_coordinates]
        .reset_index(drop=True)
    )