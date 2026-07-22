import pandas as pd
from etl.cleaning import clean_data
from etl.cleaning import resolve_species_numbers

# Load dictionary
full_dictionary = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/full_dictionary.csv"
)

cleaned_dictionary = clean_data(
    full_dictionary
)

# Load records
varied_sample = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/varied_sample.csv"
)

cleaned_varied = clean_data(
    varied_sample
)

# Resolve species names to SPECIES_NO
resolved_varied = resolve_species_numbers(
    cleaned_varied,
    cleaned_dictionary
)

print("Records:", len(resolved_varied))

print(
    "Missing SPECIES_NO:",
    resolved_varied["species_no"].isna().sum()
)

print(
    "Unique species:",
    resolved_varied["species_no"].nunique()
)

print(
    resolved_varied[
        [
            "scientific_name",
            "species_no"
        ]
    ].head(20).to_string(index=False)
)