import pandas as pd 

# Cleaning column names:
def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy()

    df.columns = (df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
    )

    return df

# Checking Unique_No (For reptile & sample)
# Checks all unique + no null 

def validate_unique_no(df: pd.DataFrame) -> None:

    # If it doesn't exist, skip db
    if "unique_no" not in df.columns:
        print("unique_no column does not exist")
        return

    # Checks for duplicate values 
    # Checks if values appeared earlier (T = 1, F = 0) 
    duplicate_count = df["unique_no"].duplicated().sum()

    # Checks for missing values 
    # (T = 1, F = 0) -> sums all values together
    missing_count = df["unique_no"].isna().sum()

    # Checks the number of different none missing values
    print(f"Unique values: {df['unique_no'].nunique()}")
    print(f"Duplicate values: {duplicate_count}")
    print(f"Missing values: {missing_count}")

# Checks species name

def validate_species_name(df: pd.DataFrame) -> None:

    columns = ["scientific_name", 'scientific']
    scientific_column = None 

    # Loops through each column in columns array 
    # If found set as scientific column
    for column in columns:
        if column in df.columns:
            scientific_column = column
            break

    if scientific_column is None:
        print("No scientific name column exists")
        return

    """
    Missing species name
    """
    # Checks missing species name
    missing_count = df[scientific_column].isna().sum()
    print(f"Missing species names: {missing_count}")

    """
    Checking scientific species name format
    """
    # Basic scientific-name format (REGEX - Genus species)
    pattern = r"^[A-Z][a-z-]+ [a-z-]+$"

    # Convert values to strings and handle missing values
    # Removes whitespaces from beg and end
    names = df[column].fillna("").astype(str).str.strip()

    # Check which values match the basic scientific-name pattern
    scientific_pattern = names.str.match(pattern)

    # Returns potentially invalid names (Don't match pattern)
    invalid_names = df[~scientific_pattern]

    # Counts num of rows in invalid_names
    print(f"Potentially invalid names: {len(invalid_names)}")

    print("\nPotentially invalid values:")
    print(invalid_names[column].unique())

    print("\nLooks like scientific names:", scientific_pattern.sum())

    print(
        "Percentage:",
        round(scientific_pattern.mean() * 100, 2),
        "%"
    )
    
def validate_avon_flag (df: pd.DataFrame) -> None:

    # If it doesn't exist, skip db
    if "outofavon" not in df.columns:
        print("outofavon column does not exist")
        return

    print(df["outofavon"].unique())

    print(df["outofavon"].value_counts(dropna=False))

    allowed_values = {"Yes", "No"}

    invalid_values = df[
        ~df["outofavon"].isin(allowed_values)
    ]

    print(f"Invalid values: {len(invalid_values)}")

    valid_count = df["outofavon"].isin(["Yes", "No"]).sum()

    print(f"Valid values: {valid_count}")
    print(f"Total rows: {len(df)}")

def validate_record_type (df: pd.DataFrame) -> None:

    if "record_type" not in df.columns:
        print("record_type column does not exist")
        return

    column = "record_type"

    print("\n===== RECORD_TYPE VALIDATION =====")

    print("\nDistinct values:")
    print(df[column].unique())

    print("\nValue counts:")
    print(df[column].value_counts(dropna=False))

    print("\nMissing values:")
    print(df[column].isna().sum())

def calculate_dictionary_match (
    records_df: pd.DataFrame,
    dictionary_df: pd.DataFrame
) -> None:

    records_column = "scientific_name"
    dictionary_column = "scientific"

    # Get distinct names from records
    record_names = set(
        records_df[records_column]
        .dropna()
        .str.strip()
        .unique()
    )

     # Get distinct names from dictionary
    dictionary_names = set(
        dictionary_df[dictionary_column]
        .dropna()
        .str.strip()
        .unique()
    )

    # Find matches
    matched_names = record_names.intersection(dictionary_names)

       # Find unmatched names
    unmatched_names = record_names - dictionary_names

    # Calculate match rate
    match_rate = (
        len(matched_names)
        / len(record_names)
        * 100
    )

    print(f"Distinct record names: {len(record_names)}")
    print(f"Matched names: {len(matched_names)}")
    print(f"Unmatched names: {len(unmatched_names)}")
    print(f"Match rate: {match_rate:.2f}%")

    print("\nSample unmatched names:")
    print(list(unmatched_names)[:20])


"""
Overall cleaning/standardisation
"""
def clean_data(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy() 

    print("\n===== DATASET SHAPE =====")
    print(df.shape)

    # COLUMN NAMES
    print("\n===== COLUMN NAMES BEFORE CLEANING =====")
    print(df.columns.tolist())

    df = clean_column_names(df)

    print("\n===== COLUMN NAMES AFTER CLEANING =====")
    print(df.columns.tolist())

    # Unique_No

    #validate_unique_no(df)

    print("\n===== SPECIES NAME VALIDATION =====")

    #validate_species_name(df)

    #validate_avon_flag(df)

    validate_record_type(df)

    return df