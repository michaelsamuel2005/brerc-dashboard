# Build the species index from species that actually appear
# in the filtered records, rather than from the full species dictionary.

import pandas as pd 

def build_species_index(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

    # Takes two columns from the DF
    species_index = (
        df[
            [
                "species_no",
                "scientific_name",
            ]
        ]
        # Removes duplicate species
        # Resets the row numbers 
        .drop_duplicates()
        .reset_index(drop=True)
    )

    return species_index