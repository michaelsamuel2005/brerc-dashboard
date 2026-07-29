# Build the species index from species that actually appear
# in the filtered records, rather than from the full species dictionary.

"""
Ensure it matches the expected species: DATABASE| SOURCE(CVS column names)
- species_id - species_no
- scientific_name - scientific_name
- common_name - common_name 
- species_group - Represented by TAXANB in the dictionary
- record_count
- first_year
- last_year
- has_image
"""
import pandas as pd

def build_species_index(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Builds one species row for each species that appears
    in the records being loaded.

    Database mapping:
        species_id     <- species_no
        scientific_name <- scientific_name
        common_name    <- common_name
        species_group  <- taxanb
        record_count   <- count of records (how many records of said species)
        first_year     <- earliest record year
        last_year      <- latest record year
        has_image      <- False until image data exists
    """

    df = df.copy()

    # Convert dates BEFORE calculating min/max.
    df["record_year"] = (
        pd.to_datetime(
            df["record_date"],
            dayfirst=True,
            errors="coerce",
        )
        .dt.year
    )

    species_index = (
        df.groupby(
            [
                "species_no",
                "scientific_name",
                "common_name",
                "taxanb",
            ],
            dropna=False,
        )
        .agg(
            record_count=("unique_no", "count"),
            first_year=("record_year", "min"),
            last_year=("record_year", "max"),
        )
        .reset_index()
        .rename(
            columns={
                "species_no": "species_id",
                "taxanb": "species_group",
            }
        )
    )

    # No image data is currently being loaded.
    species_index["has_image"] = False

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