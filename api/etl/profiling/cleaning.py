"""
Cleans raw input dataframes by standardising column names 
(stripping whitespace, lowering case, and replacing spaces with underscores).
"""

import pandas as pd


# Cleaning column names:
def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Standardises column headers by stripping whitespace, converting to lowercase, and formatting spaces."""
    cleaned_df = df.copy()

    # Strip extra spaces, lowercase everything, and swap spaces for underscores
    cleaned_df.columns = (
        cleaned_df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    )

    return cleaned_df


# Applying cleaning steps
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Applies core data cleaning steps (starting with column name standardisation)."""

    # Cleans the column names
    cleaned_df = clean_column_names(df)

    return cleaned_df
