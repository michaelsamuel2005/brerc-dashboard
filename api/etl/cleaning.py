import pandas as pd

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardise column names.
    """

    df = df.copy()

    df.columns = (df.columns
        # Removes whitespace, lowercases + adding underscores
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
    )

    return df


def validate_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Function to check if theres any rows where both dates are missing
    """

    invalid_rows = df[
        df["precise_date"].isna() &
        df["vague_date"].isna()
    ]

    return invalid_rows


def duplicate_data(df: pd.DataFrame) -> None:
    print("\n===== DUPLICATE VALUES PER COLUMN =====")

    for column in df.columns:
        duplicate_count = df[column].dropna().duplicated().sum()

        print(f"{column}: {duplicate_count} duplicate values")

def duplicate_species(df: pd.DataFrame) -> None:
    column = "scientific_name"

    print(f"\n===== DUPLICATES IN {column} =====")

    duplicate_values = (
        df[column]
        .value_counts()
        .loc[lambda x: x > 1]
    )
    
    pd.set_option("display.max_rows", None)
    print(duplicate_values)

# Takes in df (dataset) which is pandas and returns pandas dataframe (run via python test_cleaning.py)
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and standardise dataset.
    """

    # Make a copy so we don't accidentally modify the original dataframe
    df = df.copy()

    print("===== FIRST 5 ROWS =====")
    print(df.head())

    print("\n===== DATASET SHAPE =====")
    print(df.shape)

    print("\n===== COLUMN NAMES BEFORE CLEANING =====")
    print(df.columns.tolist())

    # Actual cleaning
    df = clean_column_names(df)

    print("\n===== COLUMN NAMES AFTER CLEANING =====")
    print(df.columns.tolist())

    print("\n===== DATA TYPES AND MISSING VALUES =====")
    df.info()

    print("\n===== MISSING VALUES =====")
    print(df.isna().sum())

    print("\n===== MISSING PERCENTAGE =====")
    print((df.isna().mean() * 100).round(2))

    print("\n===== DUPLICATE ROWS =====")
    print(df.duplicated().sum())

    print("\n===== DATA TYPES =====")
    print(df.dtypes)

    print("\n===== DATE VALIDATION =====")

    print(
        df[["precise_date", "vague_date"]]
        .isna()
        .value_counts()
    )

    invalid_dates = validate_dates(df)

    print("\nRows with both dates missing:")
    print(len(invalid_dates))

    duplicate_data(df)
    duplicate_species(df)

    return df