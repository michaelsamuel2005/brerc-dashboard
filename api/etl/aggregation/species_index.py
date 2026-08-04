# Build the species index from species that actually appear
# in the filtered records, rather than from the full species dictionary.

import pandas as pd

from etl.config.loader import load_safety_config

CONFIG = load_safety_config()
DATE_COLUMN = CONFIG["columns"]["record_date"]

def build_species_index(
    df: pd.DataFrame,
) -> pd.DataFrame:

    """
    Creates an aggregated species table from the records
    that are actually being loaded into the database. 

    One row is created per unique species, containing
    summary information needed by the species table
    """

    df = df.copy()

    # Convert record_date into year 
    # Aggregation function can calculate the earliest and lastest observed years 
    df["record_year"] = (
        pd.to_datetime(
            df[DATE_COLUMN],
            dayfirst=True,
            errors="coerce",
        )
        .dt.year
    )

    # Groups records belonging to the same species 
    species_index = (
        df.groupby(
            [
                "species_no",
                "scientific_name",
                "common_name",
                "taxanb",
            ],
            # Keeps species even if some name/group fields are missing
            dropna=False,
        )
        .agg(
            # Count how many occurrence records belong to this species
            record_count=("unique_no", "count"),
            # Find the earliest year this species was recorded
            first_year=("record_year", "min"),
            # Find the most recent year this species was recorded
            last_year=("record_year", "max"),
        )
        .reset_index()
        # Rename columns to match the database schema public UI will use
        .rename(
            columns={
                "species_no": "species_id",
                "taxanb": "species_group",
            }
        )
    )

    # No image data is currently being loaded.
    species_index["has_image"] = False

    # Returns the colimns required by the database
    # Ensures the output matches the species table schema 
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