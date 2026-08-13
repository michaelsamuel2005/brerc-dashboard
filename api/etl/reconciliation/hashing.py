"""
Generates deterministic SHA-256 content hashes for occurrence records 
based on a fixed set of configuration columns to detect updates during reconciliation.
"""

import hashlib
from datetime import date, datetime
import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

HASH_COLUMNS = CONFIG["reconciliation"]["hash_columns"]


def _normalised_hash_value(value) -> str:
    """
    Normalises cell values (handling missing data, dates, and strings) 
    to guarantee consistent hashes.
    """
    if pd.isna(value):
        return ""

    # Convert timestamps and dates into standard ISO format for consistency
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()

    # Convert everything else to string and strip whitespace
    # so minor formatting changes don't alter the hash
    return str(value).strip()


def row_content_hash(row: pd.Series) -> str:
    """Calculates a secure SHA-256 hash for a single row using the configured hash columns."""
    missing = set(HASH_COLUMNS) - set(row.index)

    if missing:
        raise KeyError(f"Missing columns required for hashing: {missing}")

    # Extract and normalise values in a strict, deterministic order
    parts = [_normalised_hash_value(row[col]) for col in HASH_COLUMNS]

    # Joins values into one string and generates SHA-256 hash (AS REQUIRED)
    payload = "||".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def add_content_hash(df: pd.DataFrame) -> pd.DataFrame:
    """
    Appends a 'content_hash' column to the dataframe by 
    running row_content_hash across all rows.
    """
    df = df.copy()

    # Generates one unique content hash per record
    df["content_hash"] = df.apply(
        row_content_hash,
        axis=1,
    )

    return df
