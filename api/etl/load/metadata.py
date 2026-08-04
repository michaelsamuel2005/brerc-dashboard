from datetime import datetime

import pandas as pd

# Takes the dataframe you want to add metadata to
def add_load_metadata(
    df: pd.DataFrame,
    load_number: int,
    load_timestamp: datetime,
) -> pd.DataFrame:
    
    # Takes a copy of the original dataframe
    df = df.copy()

    # Each row, will get the same load number (same ETL run)
    df["load_number"] = load_number
    # Each row will get the same timestamp (same ETL run)
    df["date_of_load"] = load_timestamp

    # Returns the copied dataframe with 2 new columns
    return df