"""
normalise_species_name()
    - Takes column called names
    - Returns pandas series
    - Normalises names and returns new pandas series

resolve_species_numbers()
    - gets the associated species number and nbm_number for species_name
    - Recives two dataframes
    - Returns a dataframe
    - Creates normalised key for the both records and dictionary for comparison
    - Creates smaller table for the dictionary
    - Drop any possible duplicate scientific names
    - Take the scientific_name_key from column of records and match it against the scientific_key column from the dictionary
    - Attaches matching dictionary information to the records 

snap_to_grid():
    - Takes coordinates, grid-size
    - Returns new coordinate representing centre of grid square
    - Calculation:
        - Find the grid coordinate belongs to 
        - Find the start of the grid block
        - Divide the grid size to get midpoint of grid size
        - Add grid size to the grid block 
        - Returns the centre of the 10km grid section

generalise_sensitive_locations():
    - Takes a copy since we changing coordinates
    - Finds the columns that are sensitive 
    - For both easting and northings:
        - Select rows where sensitive_mask is true and select northing and eastings
        - apply snap_to_grid() to northings and eastings
        - put new values back into same northing and easting rows

"""
import pandas as pd

# Normalising the names for matching
def normalise_species_name(
        names: pd.Series 
    ) -> pd.Series:

    return (
        names
        .astype("string")
        .str.strip()
        .str.lower()
        .str.replace(
            r"\s+",
            " ",
            regex=True
        )
    )

# Resolving the species name to its number
def resolve_species_numbers(
        records_df: pd.DataFrame,
        dictionary_df: pd.DataFrame
    ) -> pd.DataFrame:

    records_df = records_df.copy()
    dictionary_df = dictionary_df.copy()

    # Creates normalised matching keys
    # New results placed in different column
    records_df["scientific_name_key"] = (
        normalise_species_name(
            records_df["scientific_name"]
        )
    )

    dictionary_df["scientific_key"] = (
        normalise_species_name(
            dictionary_df["scientific"]
        )
    )
    
    species_lookup = (
        dictionary_df[
            [
                "scientific",
                "scientific_key",
                "species_no",
                "nbn_number"
            ]
        ]
        .drop_duplicates(
            subset="scientific_key"
        )
    )

    # Merge records_df with species_lookup.
    # Match records_df["scientific_name_key"]
    # Against species_lookup["scientific_key"].
    # Keep every row from records_df (the left DataFrame),
    # Adding the matching species_no where available.
    records_df = records_df.merge(
        species_lookup,
        left_on="scientific_name_key",
        right_on="scientific_key",
        how="left",
        suffixes=("", "_dict")
    )

    # Flags any species unable to be resolved -> Didn't find species_no
    records_df["species_unresolved"] = records_df["species_no"].isna()
    
    print("Records after merge:", len(records_df))

    return records_df

def report_match_coverage(records_df: pd.DataFrame) -> None:
    total = len(records_df)
    matched = records_df["species_no"].notna().sum()
    unmatched = total - matched
 
    print("\n===== SPECIES MATCH COVERAGE =====")
    print(f"Total records: {total}")
    print(f"Matched: {matched} ({matched / total * 100:.2f}%)")
    print(f"Unmatched: {unmatched} ({unmatched / total * 100:.2f}%)")
 
    unmatched_names = (
        records_df.loc[records_df["species_unresolved"], "scientific_name"]
        .dropna()
        .unique()
    )
    print(f"\nUnique unmatched names found: {len(unmatched_names)}")
    print("Sample of unmatched names:")
    for name in list(unmatched_names)[:20]:
        print(f"  - {name}")

# Set default grid size (10000 x 10000)
DEFAULT_GRID_SIZE_METRES = 10_000

def snap_to_grid(
        coordinate: float,
        grid_size: int
    ) -> float:

    return (
        coordinate // grid_size
    ) * grid_size + (
        grid_size / 2
    )

def generalise_sensitive_locations(
        df: pd.DataFrame,
        easting_column: str,
        northing_column: str,
        sensitive_column: str
    ) -> pd.DataFrame:

    df = df.copy()

    sensitive_mask = (
        df[sensitive_column]
        == True
    )

    df.loc[
        sensitive_mask,
        easting_column
    ] = (
        df.loc[
            sensitive_mask,
            easting_column
        ]
        .apply(
            lambda x: snap_to_grid(
                x,
                DEFAULT_GRID_SIZE_METRES
            )
        )
    )

    df.loc[
        sensitive_mask,
        northing_column
    ] = (
        df.loc[
            sensitive_mask,
            northing_column
        ]
        .apply(
            lambda x: snap_to_grid(
                x,
                DEFAULT_GRID_SIZE_METRES
            )
        )
    )

    return df