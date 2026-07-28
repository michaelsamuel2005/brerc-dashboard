import pandas as pd

# Takes in df (dataset) which is pandas and returns pandas dataframe (run via python test_cleaning.py)
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    
    """
    Clean and standardise dataset
    """

    print(df.head())
    # shows all column names
    print(df.columns)
    print(df.info())
    print(df.isna().sum())

    return df