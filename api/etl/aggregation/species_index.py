# Build the species index from species that actually appear
# in the filtered records, rather than from the full species dictionary.

import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

DATE_COLUMN = CONFIG["columns"]["record_date"]


def build_species_index(
    df: pd.DataFrame,
) -> pd.DataFrame:

    """
    Creates an aggregated species table from the records
    that are actually being loaded into the database.

    One row is created per unique species, containing
    summary information needed by the species table.
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
            f"Missing columns required for species index: "
            f"{sorted(missing_columns)}"
        )

    df = df.copy()

    # Remove records without a resolved species number.
    # These cannot be represented in the species table because
    # species_id is required as the public species identifier.
    df = df.dropna(
        subset=["species_no"]
    )

    # Convert record_date into year.
    # Aggregation functions can then calculate the earliest
    # and latest observed years for each species.
    df["record_year"] = (
        pd.to_datetime(
            df[DATE_COLUMN],
            dayfirst=True,
            errors="coerce",
        )
        .dt.year
        .astype("Int64")
    )

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

            # Keeps species even if some metadata fields
            # such as common name are missing.
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

    # Ensure each species_id maps to exactly one species entry.
    # The database species table expects species_id to identify
    # a single species. Duplicate IDs indicate inconsistent source
    # data or conflicting dictionary mappings.
    if species_index["species_id"].duplicated().any():
        raise ValueError(
            "Species index contains duplicate species IDs"
        )

    # No image data is currently being loaded.
    # Default value is False until image metadata exists.
    species_index["has_image"] = False

    # Return only columns required by the species table schema.
    # Ensures output matches what the database insert expects.
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