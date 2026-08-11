"""
Handles tracking metadata for ETL runs (like load mode and timestamps) 
and checks database watermarks for incremental loads.
"""

from datetime import datetime

import pandas as pd


def add_load_metadata(
    df: pd.DataFrame,
    load_mode: str,
    load_timestamp: datetime,
) -> pd.DataFrame:
    """
    Attaches the ETL load mode ('initial' or 'incremental') and timestamp 
    as audit columns to every row in the dataframe.
    """
    # Takes a copy of the original dataframe
    df = df.copy()

    # Each row gets the same load mode (same ETL run)
    # Each row gets the same timestamp (same ETL run)
    df["Load"] = load_mode
    df["Load_date"] = load_timestamp

    return df


def get_last_load_date(connection):
    """
    Fetches the most recent Load_date from the database to use as a watermark 
    for incremental loads. Returns None if the table is empty or has no loads yet.
    """
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT MAX("Load_date") AS last_load_date
            FROM occurrence_public
            """
        )
        row = cur.fetchone()
        
        # Safely handle cases where the table is empty or returns NULL
        if not row or row["last_load_date"] is None:
            return None
            
        return row["last_load_date"]