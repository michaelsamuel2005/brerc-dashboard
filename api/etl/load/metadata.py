from datetime import datetime

import pandas as pd


def add_load_metadata(
    df: pd.DataFrame,
    load_mode: str,
    load_timestamp: datetime,
) -> pd.DataFrame:
    """
    Returns a copy of the dataframe with ETL load metadata attached.

    Each row receives the same load mode ("initial" or "incremental")
    and timestamp, representing the ETL run that produced the data.
    """

    # Takes a copy of the original dataframe
    df = df.copy()

    # Each row gets the same load mode (same ETL run)
    df["Load"] = load_mode

    # Each row gets the same timestamp (same ETL run)
    df["Load_date"] = load_timestamp

    return df


def get_last_load_date(connection):
    """
    Returns the watermark date for incremental loads: the most recent
    Load_date already written to occurrence_public.

    Returns None if the table is empty (i.e. there has been no
    previous load), which callers should treat as "no watermark yet"
    and fall back to an initial (full) load.
    """
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT MAX("Load_date") AS last_load_date
            FROM occurrence_public
            """
        )
        return cur.fetchone()["last_load_date"]
