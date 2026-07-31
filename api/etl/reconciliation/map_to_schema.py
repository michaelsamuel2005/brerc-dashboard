import pandas as pd

from etl.config.loader import load_safety_config

CONFIG = load_safety_config()
DATE_COLUMN = CONFIG["columns"]["record_date"]

# Takes the clean dataframe
# Maps it to the occurence_public database table

def map_to_occurrence_public(safe_df: pd.DataFrame) -> pd.DataFrame:
    df = safe_df.copy()

    # Returns only the year rn (may need to change later)
    df["record_year"] = pd.to_datetime(
        df[DATE_COLUMN], dayfirst=True
    ).dt.year

    return pd.DataFrame({
        "record_id": df["unique_no"],
        "species_id": df["species_no"],
        "record_year": df["record_year"],
        "grid_ref": df["coarse_locality"],
        "locality": df["coarse_locality"], # Change once we can calculate unitary authority data
        "precision_metres": df["effective_resolution_m"],
        "verified": ~df["is_legacy"].astype(bool),
        "content_hash": df["content_hash"],
    })