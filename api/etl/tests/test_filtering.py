import pandas as pd

from etl.cleaning import (
    clean_data,
)
from etl.filtering import (
    filter_sensitive_species
)
from etl.generalisation import (
    resolve_species_numbers,
)

# =========================
# LOAD DICTIONARY
# =========================

full_dictionary = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/full_dictionary.csv"
)

cleaned_dictionary = clean_data(
    full_dictionary
)

# =========================
# LOAD RECORDS
# =========================

varied_sample = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/varied_sample.csv"
)

cleaned_varied = clean_data(
    varied_sample
)

# =========================
# RESOLVE SPECIES NUMBERS
# =========================

resolved_varied = resolve_species_numbers(
    cleaned_varied,
    cleaned_dictionary
)

# =========================
# FILTER SENSITIVE RECORDS
# =========================

filtered_varied = filter_sensitive_species(
    resolved_varied
)

# =========================
# DISPLAY RESULTS
# =========================

print(
    "\n===== FILTERING TEST ====="
)

print(
    "Total records:",
    len(filtered_varied)
)

print(
    "Sensitive records:",
    filtered_varied["is_sensitive"].sum()
)

print(
    "Non-sensitive records:",
    (
        ~filtered_varied["is_sensitive"]
    ).sum()
)

print(
    "\nSensitive records:"
)

print(
    filtered_varied[
        filtered_varied["is_sensitive"] == True
    ][
        [
            "scientific_name",
            "species_no",
            "record_type",
            "is_sensitive"
        ]
    ]
    .head(20)
    .to_string(index=False)
)