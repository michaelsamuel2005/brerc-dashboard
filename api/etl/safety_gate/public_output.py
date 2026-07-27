import pandas as pd

from etl.safety_gate.locality import os_grid_square

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
    "record_date",
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
    # IMPORTANT: easting_column/northing_column must be the SNAPPED
    # (generalised) coordinates from generalise_locations, i.e.
    # "snapped_easting"/"snapped_northing" - never the raw ones.
    df = df.copy()
    df["coarse_locality"] = df.apply(
        lambda row: os_grid_square(
            row[easting_column], row[northing_column]
        )
        if pd.notna(row[easting_column]) and pd.notna(row[northing_column])
        else pd.NA,
        axis=1,
    )
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
        print(
            "WARNING: dropping "
            f"{no_coordinates.sum()} public records "
            "with no coordinates."
        )

    return (
        public_df
        .loc[~no_coordinates]
        .reset_index(drop=True)
    )