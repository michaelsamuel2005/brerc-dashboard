"""
resolve_species_numbers()
    - gets the associated species number for species_name
    - Recives two dataframes
    - Returns a dataframe
    - From dictionary keep only scientific and species_no 
    - Drop any possible duplicate scientific names
    - Take the scientific_name from column the records and match it against the scientific column from the lookup table

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

# Resolving the species name to its number
def resolve_species_numbers(
        records_df: pd.DataFrame,
        dictionary_df: pd.DataFrame
    ) -> pd.DataFrame:

    records_df = records_df.copy()

    species_lookup = (
        dictionary_df[
            ["scientific", "species_no"]
        ]
        .drop_duplicates(
            subset="scientific"
        )
    )

    # Merge records_df with species_lookup.
    # Match records_df["scientific_name"]
    # against species_lookup["scientific"].
    # Keep every row from records_df (the left DataFrame),
    # adding the matching species_no where available.
    records_df = records_df.merge(
        species_lookup,
        left_on="scientific_name",
        right_on="scientific",
        how="left"
    )

    print("Records after merge:", len(records_df))

    return records_df

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