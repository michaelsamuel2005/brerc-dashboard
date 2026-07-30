# Fixed list of columns used to determin if a record has changed
# Same values in columns = same hash, Changed value in columns = different hash 
# Reconciliation pipeline updates record in the UI dastabase

import hashlib
import pandas as pd

from datetime import date, datetime
from etl.config.loader import load_safety_config

CONFIG = load_safety_config() 

HASH_COLUMNS = CONFIG["reconciliation"]["hash_columns"]

def _normalised_hash_value(value) -> str:
    if pd.isna(value):
        return ""

    # Converts all date/time into ISO format -> consistent hashes
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    # Converts remaining value to string and removes whitespaces 
    # -> so formatting doesn't change hash
    return str(value).strip()


def row_content_hash(row: pd.Series) -> str:
    missing = set(HASH_COLUMNS) - set(row.index)

    if missing: 
        raise KeyError(
            f"Missing columns required for hashing: {missing}"
        )

    # Extract and normalises each value in column in fixed orfer
    parts = [
        _normalised_hash_value(row[col]) 
        for col in HASH_COLUMNS
    ]

    # Joins values into one string and generates SHA-256 hash (AS REQUIRED)
    payload = "||".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def add_content_hash(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    # Generates one content hash per record
    df["content_hash"] = df.apply(
        row_content_hash, 
        axis=1,
    )

    return df

