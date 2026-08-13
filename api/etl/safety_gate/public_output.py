"""
Enforces strict data minimisation and privacy boundaries by validating allowed 
public columns, stripping forbidden internal/sensitive data, generating coarse localities, 
and dropping unlocatable records before data reaches the public dashboard.
"""

import logging
import pandas as pd

from etl.safety_gate.location import os_grid_square

logger = logging.getLogger(__name__)

# Matches occurrence_public schema and the API contract's public fields
# (e.g., species_id, precision_metres).
PUBLIC_COLUMNS = [
    "unique_no",
    "species_no",  # public - shown as speciesId in the contract
    "scientific_name",
    "record_type",
    "longitude",
    "latitude",
    "coarse_locality",
    "effective_resolution_m",  # public - shown as precisionMetres in the contract
    "date_of_record",
    "is_legacy",
]
# Genuinely never allowed past the boundary: precise coordinates, free text,
# personal data, and internal classification machinery that could expose sensitivity reasons.
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
    """Fail-fast check to ensure no forbidden columns accidentally bleed into PUBLIC_COLUMNS."""
    forbidden = set(PUBLIC_COLUMNS) & FORBIDDEN_COLUMNS

    if forbidden:
        raise ValueError(f"Forbidden columns found in PUBLIC_COLUMNS: {forbidden}")


# Run validation immediately upon module import
_validate_public_columns()


def add_coarse_locality(
    df: pd.DataFrame,
    easting_column: str = "snapped_easting",
    northing_column: str = "snapped_northing",
) -> pd.DataFrame:
    """Generates coarse OS grid reference locality strings from snapped/blurred coordinates."""
    df = df.copy()

    required = {
        easting_column,
        northing_column,
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing coordinate columns: {missing}")

    coarse_localities = []

    # Pair and convert easting/northing coordinates into grid references
    for easting, northing in zip(
        df[easting_column],
        df[northing_column],
    ):
        # If coordinate exist create grid reference, else store missing value
        if pd.notna(easting) and pd.notna(northing):
            coarse_localities.append(os_grid_square(easting, northing))
        else:
            coarse_localities.append(pd.NA)

    # Adds returned list to DF column
    df["coarse_locality"] = coarse_localities

    # Returns updated dataframe
    return df


def prepare_public_output(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validates column presence, strips unauthorized fields, logs warnings 
    for unlocatable records, and drops rows without coordinates at the final output boundary.
    """
    missing = [column for column in PUBLIC_COLUMNS if column not in df.columns]

    if missing:
        raise KeyError(f"Missing required public columns: {missing}")

    # Retain strictly the approved public columns
    public_df = df[PUBLIC_COLUMNS].copy()

    # Identify records missing latitude or longitude coordinates
    no_coordinates = public_df["longitude"].isna() | public_df["latitude"].isna()

    if no_coordinates.any():
        logger.warning(
            "Dropping %s public records with no coordinates.",
            no_coordinates.sum(),
        )

    # Public maps cannot display records without coordinates;
    # these are filtered out exclusively at this final boundary.
    return public_df.loc[~no_coordinates].reset_index(drop=True)
