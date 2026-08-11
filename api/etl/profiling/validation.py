"""
Data validation and profiling utility functions used to inspect 
record uniqueness, species name formats, region flags, and dictionary matching.
"""

import pandas as pd


def validate_unique_no(df: pd.DataFrame) -> None:
    """Inspects unique record numbers for duplicates, missing values, and uniqueness metrics."""

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
    """
    Profiles scientific name formats, checks for missing entries, 
    and flags potentially invalid strings.
    """
    columns = ["scientific_name", "scientific"]

    scientific_column = None

    for column in columns:
        if column in df.columns:
            scientific_column = column
            break

    if scientific_column is None:
        print("No scientific name column exists")
        return

    missing_count = df[scientific_column].isna().sum()

    print(f"Missing species names: {missing_count}")

    # Basic scientific-name format (REGEX - Genus species)
    pattern = r"^[A-Z][a-z-]+ [a-z-]+$"

    names = df[scientific_column].fillna("").astype(str).str.strip()

    scientific_pattern = names.str.match(pattern)
    invalid_names = df[~scientific_pattern]

    print(f"Potentially invalid names: {len(invalid_names)}")
    print("\nPotentially invalid values:")
    print(invalid_names[scientific_column].unique())
    print("\nLooks like scientific names:", scientific_pattern.sum())
    print("Percentage:", round(scientific_pattern.mean() * 100, 2), "%")


def validate_avon_flag(df: pd.DataFrame) -> None:
    """Validates the 'outofavon' regional flag column to ensure expected Yes/No values."""
    if "outofavon" not in df.columns:
        print("outofavon column does not exist")
        return

    out_of_avon = df["outofavon"]

    print("Unique values:", out_of_avon.unique())
    print("\nValue counts:")
    print(out_of_avon.value_counts(dropna=False))

    allowed_values = {"Yes", "No"}

    # Find rows where outofavon is not explicitly 'Yes' or 'No'
    invalid_values = df[~out_of_avon.isin(allowed_values)]

    print(f"\nInvalid values: {len(invalid_values)}")
    valid_count = out_of_avon.isin(allowed_values).sum()
    print(f"Valid values: {valid_count}")
    print(f"Total rows: {len(df)}")


def validate_record_type(df: pd.DataFrame) -> None:
    """Profiles the distribution and missing counts of distinct record types."""
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


def calculate_dictionary_match(
    record_df: pd.DataFrame, dictionary_df: pd.DataFrame
) -> None:
    """
    Calculates match rates and identifies unmatched names 
    between records and the master dictionary.
    """
    record_column = "scientific_name"
    dictionary_column = "scientific"

    record_species = record_df[record_column]
    dictionary_species = dictionary_df[dictionary_column]

    # Get distinct names from records + dictionary
    record_names = set(record_species.dropna().str.strip().unique())
    dictionary_names = set(dictionary_species.dropna().str.strip().unique())

    # Find matches
    matched_names = record_names.intersection(dictionary_names)

    # Find unmatched names
    unmatched_names = record_names - dictionary_names

    # Calculate match rate
    match_rate = len(matched_names) / len(record_names) * 100

    print(f"Distinct record names: {len(record_names)}")
    print(f"Matched names: {len(matched_names)}")
    print(f"Unmatched names: {len(unmatched_names)}")
    print(f"Match rate: {match_rate:.2f}%")

    print("\nSample unmatched names:")
    print(list(unmatched_names)[:20])


def get_sensitive_record_types(df: pd.DataFrame) -> None:
    """Extracts and displays unique record types flagged as sensitive."""

    # Note for dropdown menu -> record type is recordtype
    if "recordtype" not in df.columns:
        print("recordtype column does not exist")
        return

    # Select recordtype values where sensitive is 'yes'
    sensitive_record_types = (
        df.loc[df["sensitive"] == "yes", "recordtype"].dropna().unique()
    )

    print(sensitive_record_types)
    print(f"Distinct record names: {len(sensitive_record_types)}")


def get_verified_types(df: pd.DataFrame) -> None:
    """Profiles the verification status column for value distribution and missing data."""
    if "verified" not in df.columns:
        print("verified column does not exist")
        return

    verified_type = df["verified"]

    print("\nDistinct values:")
    print(verified_type.unique())

    print("\nValue counts:")
    print(verified_type.value_counts(dropna=False))

    print("\nMissing values:")
    print(verified_type.isna().sum())
