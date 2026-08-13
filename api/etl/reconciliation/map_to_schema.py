"""
Maps safe, processed occurrence dataframes into the exact schema 
structure required by the public-facing 'occurrence_public' database table.
"""

import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()
DATE_COLUMN = CONFIG["columns"]["record_date"]
MODIFIED_COLUMN = CONFIG["columns"]["modified_date"]


def map_to_occurrence_public(safe_df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforms and maps safe occurrence records into public schema columns, 
    handling date cleaning, year extraction, and data type alignment.
    """
    df = safe_df.copy()

    # Some raw records contain junk text prefixed to the date (e.g. " - 17/10/2023").
    # Extract clean date patterns and coerce unparseable entries to NaT to prevent crashes.
    cleaned_dates = (
        df[DATE_COLUMN]
        .astype("string")
        .str.extract(r"(\d{1,2}/\d{1,2}/\d{2,4})", expand=False)
    )

    df["record_year"] = pd.to_datetime(
        cleaned_dates, dayfirst=True, errors="coerce"
    ).dt.year

    # Ensure species IDs remain strings since BRERC
    # uses both numeric and prefixed IDs (e.g. Axxxxx).
    df["species_no"] = df["species_no"].astype("string").str.strip()

    # Map internal dataframe columns to public schema column names
    return pd.DataFrame(
        {
            "record_id": df["unique_no"],
            "species_id": df["species_no"],
            "record_year": df["record_year"],
            "grid_ref": df["coarse_locality"],
            "locality": df["coarse_locality"],
            "precision_metres": df["effective_resolution_m"],
            "verified": ~df["is_legacy"].astype(bool),
            "content_hash": df["content_hash"],
            "date_mdb_modified": df[MODIFIED_COLUMN],
        }
    )