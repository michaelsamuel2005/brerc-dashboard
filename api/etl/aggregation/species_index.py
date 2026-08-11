"""
Builds the species index directly from the species that actually appear 
in the filtered records, rather than from the full species dictionary.
"""

import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

DATE_COLUMN = CONFIG["columns"]["record_date"]


def build_species_index(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Creates a summary table of unique species found in the active records,
    calculating total counts, year ranges, and mapping columns to database schema.
    """
    required_columns = {
        "species_no",
        "scientific_name",
        "common_name",
        "taxanb",
        "unique_no",
        DATE_COLUMN,
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise KeyError(
            f"Missing columns required for species index: " f"{sorted(missing_columns)}"
        )

    df = df.copy()

    # Drops records without a resolved species number
    # species_id is required as the public species identifier
    df = df.dropna(subset=["species_no"])

    # Convert dates into years so we can find the
    # earliest and latest recorded years per species.
    df["record_year"] = pd.to_datetime(
        df[DATE_COLUMN],
        dayfirst=True,
        errors="coerce",
    ).dt.year.astype("Int64")

    # Groups records belonging to the same species.
    # Each group represents one species entry in the species table.
    species_index = (
        df.groupby(
            [
                "species_no",
                "scientific_name",
                "common_name",
                "taxanb",
            ],
            # Keep species even if some fields like common names are missing
            dropna=False,
        )
        .agg(
            # Count how many occurrence records belong to this species.
            record_count=("unique_no", "count"),
            # Find the earliest year this species was recorded.
            first_year=("record_year", "min"),
            # Find the most recent year this species was recorded.
            last_year=("record_year", "max"),
        )
        .reset_index()
        # Rename columns to match the database schema.
        # species_no becomes species_id in the public database.
        .rename(
            columns={
                "species_no": "species_id",
                "taxanb": "species_group",
            }
        )
    )

    # Ensure each species_id is completely unique; duplicates mean bad data.
    if species_index["species_id"].duplicated().any():
        raise ValueError("Species index contains duplicate species IDs")

    # Default image flag to False since image metadata isn't loaded yet.
    species_index["has_image"] = False

    # Return only the exact columns expected by the database table.
    return species_index[
        [
            "species_id",
            "scientific_name",
            "common_name",
            "species_group",
            "record_count",
            "first_year",
            "last_year",
            "has_image",
        ]
    ]
