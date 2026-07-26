"""
filter_accepted_record():
    - Take the records loaded from the source
    - Return only records allowed to contribute to the public derived layer 
"""

import pandas as pd 

# Defines the allowed values
ACCEPTED_VERIFIED_VALUES = {
    "Accepted ñ correct",
    "Accepted ñ considered correct",
}

LEGACY_VERIFIED_VALUES = {
    "BRERC",
}

# Recives DF + Verified column
def filter_accepted_records(
        df: pd.DataFrame,
        verified_column: str = "verified",
    ) -> pd.DataFrame:

    df = df.copy()

    # Standardise verified column values:
    # Values = pandas strings + strips whitespace
    verified = (
        df[verified_column]
        .astype("string")
        .str.strip()
    )

    # Finds accepted records in verified column (Returns T or F)
    accepted = verified.isin(
        ACCEPTED_VERIFIED_VALUES
    ) 

    # Finds legacy records: 
    # Checks for missing values, empty strings or legacy values
    # Will give T for any values who are legacy, else false
    legacy = (
        verified.isna()
        | verified.eq("")
        | verified.isin(LEGACY_VERIFIED_VALUES)
    )

    included = accepted | legacy
    
    # Keeps rows only where included == True
    filtered_df = df.loc[included].copy()

    # Adds a legacy marker - from legacy take the T/F values and add them to this column
    filtered_df["is_legacy"] = legacy.loc[
        filtered_df.index
    ]

    return filtered_df 

