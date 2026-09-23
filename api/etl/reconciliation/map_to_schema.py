"""
Maps safe, processed occurrence dataframes into the exact schema 
structure required by the public-facing 'occurrence_public' database table.
"""

import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()
MODIFIED_COLUMN = CONFIG["columns"]["modified_date"]


def map_to_occurrence_public(safe_df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforms and maps safe occurrence records into public schema columns, 
    handling data type alignment.
    """
    df = safe_df.copy()

    # record_year is worked out upstream by derive_record_year() (see
    # etl/profiling/record_year.py). Int64 so it is written as 2014, not 2014.0.
    df["record_year"] = df["record_year"].astype("Int64")

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