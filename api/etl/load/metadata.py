from datetime import datetime

import pandas as pd


def add_load_metadata(
    df: pd.DataFrame,
    load_number: int,
    load_timestamp: datetime,
) -> pd.DataFrame:
    """
    Returns a copy of the dataframe with ETL load metadata attached.

    Each row receives the same load number and timestamp,
    representing the ETL run that produced the data.
    """

    # Takes a copy of the original dataframe
    df = df.copy()

    # Each row gets the same load number (same ETL run)
    df["load_number"] = load_number

    # Each row gets the same timestamp (same ETL run)
    df["date_of_load"] = load_timestamp

    return df


def get_next_load_number(connection) -> int:
    """
    Returns the next ETL load number, based on the highest
    load_number already written to occurrence_public.
    Starts from 1 if the table is empty.
    """
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(load_number), 0) + 1 AS next_load_number
            FROM occurrence_public
            """
        )
        return cur.fetchone()["next_load_number"]