import pandas as pd 

def filter_sensitive_species(df):

    # species_id = SPECIES_No 
    return df[
        # selects species_id column, compares against sensitive ID set
        # returns species_id NOT in sensitive set 
        ~df["species_id"].isin(SENSITIVE_SPECIES_IDS)
    ].copy()