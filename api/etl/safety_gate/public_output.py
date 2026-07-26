import pandas as pd

from etl.safety_gate.locality import os_grid_square

PUBLIC_COLUMNS = [
    "unique_no",
    "scientific_name",
    "record_type",
    "longitude",
    "latitude",
    "coarse_locality",
    "record_date",
]

FORBIDDEN_COLUMNS = {
    "place",
    "comments",
    "easting",
    "northing",
    "grid_reference",
    "recorder_name",
    "sensitivity_reason",
    "is_sensitive",
    "species_no",
    "nbn_number",
    "effective_resolution_m",
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
    # coarse_locality is a D0 safety field; building it from precise
    # coordinates would defeat the point of blurring them.
    df = df.copy()
    # NOTE: grid square only for now - no unitary authority lookup
    # yet, add it here later once that data source exists.
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

    # Records with no coordinates (excluded upstream in
    # generalise_locations) are kept elsewhere for record counts,
    # but must never reach public/map output.
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