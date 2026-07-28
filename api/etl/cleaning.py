import pandas as pd 

# Cleaning column names:
def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:

    cleaned_df = df.copy()

    cleaned_df.columns = (
        cleaned_df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    return cleaned_df

# Applying cleaning steps
def clean_data(df: pd.DataFrame) -> pd.DataFrame:

    # Cleans the column names
    cleaned_df = clean_column_names(df)

    # Returns the cleaned DF
    return cleaned_df