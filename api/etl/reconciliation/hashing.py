"""
_normalised_hash_value():
    - If value is missing return empty string
    - If value is date/time -> convert to ISO format
    - For everything else, convert to text, remove extra space (from start/end)

row_content_hash():
    - Pulls row values in fixed order 
    - Normalises them
    - Joins values into one string
    - Converts strings into bytes
    - Produces the final hash string

add_content_hash():
    - Adds content_hash column, stores every records hash
    - Runs row_content_hash() on each row
    - Stores results in a new column 

build_id_hash_map():
    - Builds dictionary:
        - Each record id with its current content hash

diff_id_hash_maps():
    - Compares current source data with whats in UI table
    - Gets all IDs in the new source data
    - Gets all IDs in the UI database 
    - Inserts: IDs in source, but not in UI
    - Deletes: IDs in the UI, but no longer in the source
    - Possible_updates: ID that exist in both (may have changes)
    - For IDs in both, compare the hashes
        - If hashes are different underlying raw row has changed -> update record
    - Unchanged: Records whos hashes are same in both

NEED TO IDENITFY THE RECONCILIATION INPUTS LATER
"""

# Fixed list of fields defining the row's content hash
# Same values in columns = same hash
# Changed value in columns = different hash 

import hashlib
import pandas as pd

# Fixed list of raw fields used to detect source-data change.
# Keep the order stable forever.
HASH_COLUMNS = [
    "scientific_name",
    "common_name",
    "place",
    "abundance",
    "sex_stage",
    "record_type",
    "vitality",
    "verified",
    # "comments" possible ignore since forbidden to show on FE
    "eastings",
    "northings",
]

def _normalised_hash_value(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value).strip()


def row_content_hash(row: pd.Series) -> str:
    parts = [_normalised_hash_value(row[col]) for col in HASH_COLUMNS]
    payload = "||".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def add_content_hash(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["content_hash"] = df.apply(row_content_hash, axis=1)
    return df

