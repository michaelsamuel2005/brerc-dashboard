
"""
UNDER THIS FILE CONTAINS ALL THE VALIDATION FUNCTIONS CURRENTLY IN USE:

FUNCTIONS:
- validate_unique_no() - Checks if all unique_no are UNIQUE and NON NULL (For reptile & sample)
    - Reminder (T = 1, F = 0) 
    - sum() will sum all the values returned from the functions being (T or F)

- validate_species_name() - Checks species name
    # Loops through each column in columns array 
    # If found set as scientific column
        # Checks missing species name

    Checking scientific species name format

        # Convert values to strings and handle missing values
    # Removes whitespaces from beg and end

        # Check which values match the basic scientific-name pattern
            # Returns potentially invalid names (Don't match pattern)

                # Counts num of rows in invalid_names

- validate_avon_flag()
    # If it doesn't exist, skip db
    - See all different values in the column
    - Counts all the values - ensyres missing values aren;t skipped
    - Defined allowed values
    - Finds invalid rows 
    - Count valid values

- validate_record_type() 
- what diff record types exist
how many of each type are there
are any record types missing 

- calculate_dictionary_match  - how many species in records dataset exist in the dictionary dataset
- two datasets use different column names 

- get_sensitive_record_types()
    - checking for all the sensative record types in the dropdown for rules
    - checks the sensitive column for every row 
    - keeps rows only where its true 
    - loc has structure [rows, columns]
    - from df, select recordtype values (column selected) for rows where sensitive = yes

"""
import pandas as pd

def validate_unique_no(df: pd.DataFrame) -> None:

    # If it doesn't exist, skip db
    if "unique_no" not in df.columns:
        print("unique_no column does not exist")
        return

    # Stores unique_no in variable
    unique_no = df["unique_no"]

    # duplicate_count - checks if value has been seen earlier
    # missing_count - checks if any values are missing
    # unique_count - checks how many different non-missing values exist
    duplicate_count = unique_no.duplicated().sum()
    missing_count = unique_no.isna().sum()
    unique_count = unique_no.nunique()

    print(f"Unique values: {unique_count}")
    print(f"Duplicate values: {duplicate_count}")
    print(f"Missing values: {missing_count}")

def validate_species_name(df: pd.DataFrame) -> None:

    columns = [
        "scientific_name", 
        'scientific'
    ]

    scientific_column = None 

    for column in columns:
        if column in df.columns:
            scientific_column = column
            break

    if scientific_column is None:
        print("No scientific name column exists")
        return

    missing_count = (
        df[scientific_column]
        .isna()
        .sum()
    )

    print(f"Missing species names: {missing_count}")

    # Basic scientific-name format (REGEX - Genus species)
    pattern = r"^[A-Z][a-z-]+ [a-z-]+$"

    names = (
        df[scientific_column]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    scientific_pattern = names.str.match(pattern)
    invalid_names = df[~scientific_pattern]

    print(f"Potentially invalid names: {len(invalid_names)}")
    
    print("\nPotentially invalid values:")
    
    print(
        invalid_names[
            scientific_column
        ].unique()
    )

    print("\nLooks like scientific names:", scientific_pattern.sum())
    
    print(
        "Percentage:",
        round(scientific_pattern.mean() * 100, 2),
        "%"
    )
    
def validate_avon_flag (df: pd.DataFrame) -> None:

    if "outofavon" not in df.columns:
        print("outofavon column does not exist")
        return

    out_of_avon = df["outofavon"]

    print("Unique values:", out_of_avon.unique())
    
    print("\nValue counts:")
    print(out_of_avon.value_counts(dropna=False))

    allowed_values = {"Yes", "No"}

    # Find rows where outofavon is not "yes" or "no"
    # In dataframe get column check if value is in allowed, keep all that aren't
    invalid_values = df[
        ~out_of_avon.isin(allowed_values)
    ]

    print(f"\nInvalid values: {len(invalid_values)}")

    valid_count = out_of_avon.isin(allowed_values).sum()

    print(f"Valid values: {valid_count}")
    print(f"Total rows: {len(df)}")

def validate_record_type (df: pd.DataFrame) -> None:

    if "record_type" not in df.columns:
        print("record_type column does not exist")
        return

    record_type = df["record_type"]

    print("\nDistinct values:")
    print(record_type.unique())

    print("\nValue counts:")
    print(record_type.value_counts(dropna=False))

    print("\nMissing values:")
    print(record_type.isna().sum())

def calculate_dictionary_match (
        record_df: pd.DataFrame,
        dictionary_df: pd.DataFrame
    ) -> None:

    record_column = "scientific_name"
    dictionary_column = "scientific"

    record_species = record_df[record_column]
    dictionary_species = dictionary_df[dictionary_column]

    # Get distinct names from records + dictionary
    record_names = set(
        record_species
        .dropna()
        .str.strip()
        .unique()
    )

    dictionary_names = set(
        dictionary_species
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

def get_sensitive_record_types(df: pd.DataFrame) -> None:
    
    # Note for dropdown menu -> record type is recordtype 
    if "recordtype" not in df.columns:
        print("recordtype column does not exist")
        return

    sensitive_record_types = (
        df.loc[
            df["sensitive"] == "yes", 
            "recordtype"
        ]
        .dropna()
        .unique()
    )

    print(sensitive_record_types)
    print(f"Distinct record names: {len(sensitive_record_types)}")


