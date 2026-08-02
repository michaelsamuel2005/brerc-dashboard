# import pandas as pd

# from etl.config.loader import load_safety_config

# CONFIG = load_safety_config()
# DATE_COLUMN = CONFIG["columns"]["record_date"]

# # Takes the clean dataframe
# # Maps it to the occurence_public database table

# def map_to_occurrence_public(safe_df: pd.DataFrame) -> pd.DataFrame:
#     df = safe_df.copy()

#     # Returns only the year rn (may need to change later)
#     df["record_year"] = pd.to_datetime(
#         df[DATE_COLUMN], dayfirst=True
#     ).dt.year

#     return pd.DataFrame({
#         "record_id": df["unique_no"],
#         "species_id": df["species_no"],
#         "record_year": df["record_year"],
#         "grid_ref": df["coarse_locality"],
#         "locality": df["coarse_locality"], # Change once we can calculate unitary authority data
#         "precision_metres": df["effective_resolution_m"],
#         "verified": ~df["is_legacy"].astype(bool),
#         "content_hash": df["content_hash"],
#     })


import re
import pandas as pd

from etl.config.loader import load_safety_config

CONFIG = load_safety_config()
DATE_COLUMN = CONFIG["columns"]["record_date"]

# Takes the clean dataframe
# Maps it to the occurence_public database table

def map_to_occurrence_public(safe_df: pd.DataFrame) -> pd.DataFrame:
    df = safe_df.copy()

    # Some real records have junk prefixed to the date
    # (e.g. " - 17/10/2023"). Strip anything that isn't part of a
    # date before parsing, and coerce any genuinely unparseable
    # dates to NaT rather than crashing the whole run.
    cleaned_dates = (
        df[DATE_COLUMN]
        .astype("string")
        .str.extract(r"(\d{1,2}/\d{1,2}/\d{2,4})", expand=False)
    )

    df["record_year"] = pd.to_datetime(
        cleaned_dates, dayfirst=True, errors="coerce"
    ).dt.year

    # Species IDs come from the dictionary SPECIES_NO field.
    # BRERC uses both numeric IDs and prefixed IDs (e.g. Axxxxx).
    # Keep them as strings because they are identifiers, not numbers.
    df["species_no"] = (
        df["species_no"]
        .astype("string")
        .str.strip()
    )

    return pd.DataFrame({
        "record_id": df["unique_no"],
        "species_id": df["species_no"],
        "record_year": df["record_year"],
        "grid_ref": df["coarse_locality"],
        "locality": df["coarse_locality"],
        "precision_metres": df["effective_resolution_m"],
        "verified": ~df["is_legacy"].astype(bool),
        "content_hash": df["content_hash"],
    })