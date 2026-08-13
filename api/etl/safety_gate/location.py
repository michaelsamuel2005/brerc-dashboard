"""
Converts British National Grid easting and northing coordinates into OS National Grid 
reference strings truncated to specific square sizes (10km, 1km, 100m), 
and builds privacy-compliant coarse localities for public reporting.
"""

import pandas as pd
from OSGridConverter import OSGridReference

# Digits per half for common square sizes
# (e.g., 10km -> 1 digit each side, 1km -> 2 digits each side)
_DIGITS_BY_SQUARE_SIZE_M = {
    10_000: 1,
    1_000: 2,
    100: 3,
}


def os_grid_square(
    easting: float,
    northing: float,
    square_size_m: int = 10_000,
) -> str:
    """
    Converts BNG easting and northing coordinates into an OS National Grid reference string 
    truncated to the specified square size using the OSGridConverter library.
    """
    if square_size_m not in _DIGITS_BY_SQUARE_SIZE_M:
        raise ValueError(
            f"Unsupported square_size_m: {square_size_m}. "
            f"Supported: {sorted(_DIGITS_BY_SQUARE_SIZE_M)}"
        )

    # Prevent invalid or missing coordinates from crashing the ETL pipeline
    if pd.isna(easting) or pd.isna(northing):
        return pd.NA

    try:
        easting = int(easting)
        northing = int(northing)
    except (TypeError, ValueError):
        return pd.NA

    digits = _DIGITS_BY_SQUARE_SIZE_M[square_size_m]

    # Generate full OS grid reference string
    full_ref = str(OSGridReference(easting, northing))
    letters, easting_str, northing_str = full_ref.split(" ")

    # Truncate easting and northing strings based on target square size precision
    return f"{letters}" f"{easting_str[:digits]}" f"{northing_str[:digits]}"


def add_grid_square(
    df: pd.DataFrame,
    easting_column: str,
    northing_column: str,
    square_size_m: int = 10_000,
) -> pd.Series:
    """
    Applies os_grid_square across a DataFrame, returning a Series of grid reference 
    strings or pd.NA for rows with missing/invalid coordinates.
    """

    def _row_ref(row):
        easting = row[easting_column]
        northing = row[northing_column]
        if pd.isna(easting) or pd.isna(northing):
            return pd.NA
        return os_grid_square(easting, northing, square_size_m)

    return df.apply(_row_ref, axis=1)


def add_coarse_locality(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Generates a 1km coarse grid square location string from snapped/blurred coordinates 
    and assigns it as the safe coarse locality for public viewing.
    """
    df = df.copy()

    df["grid_square"] = add_grid_square(
        df,
        easting_column="snapped_easting",
        northing_column="snapped_northing",
        square_size_m=1_000,
    )

    # Do not expose original precise locality names.
    # Coarse locality is set to the safe 1km grid reference string.
    df["coarse_locality"] = df["grid_square"]

    return df
