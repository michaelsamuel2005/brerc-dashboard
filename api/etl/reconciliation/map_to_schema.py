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

    # Dates arrive in two quite different shapes depending on the source:
    #
    #   CSV mode      free text, sometimes with junk prefixed ("  - 17/10/2023"),
    #                 in UK day-first order.
    #   database mode a real DATE column, which pandas renders ISO ("2024-05-14").
    #
    # The regex below handles the first. On its own it silently fails the second —
    # it matches nothing, record_year becomes NULL, and because
    # occurrence_public.record_year is NOT NULL the entire nightly run aborts on
    # the first record. So parse the raw value as a fallback wherever the regex
    # found nothing, and only then give up (NaT).
    raw_dates = df[DATE_COLUMN]

    extracted = (
        raw_dates.astype("string")
        .str.extract(r"(\d{1,2}/\d{1,2}/\d{2,4})", expand=False)
    )
    day_first = pd.to_datetime(extracted, dayfirst=True, errors="coerce")

    # Anything the regex could not see — real dates, ISO strings — parsed directly.
    direct = pd.to_datetime(raw_dates, errors="coerce")

    df["record_year"] = day_first.fillna(direct).dt.year

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