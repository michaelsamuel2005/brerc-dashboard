import pandas as pd

from etl.cleaning import clean_data
from etl.generalisation import (
    resolve_species_numbers,
    report_match_coverage,
    check_nbn_consistency,
)


# =========================
# LOAD DICTIONARY
# =========================

full_dictionary = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/full_dictionary.csv"
)
cleaned_dictionary = clean_data(full_dictionary)


# =========================
# LOAD RECORDS
# =========================

varied_sample = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/varied_sample.csv"
)
cleaned_varied = clean_data(varied_sample)


# =========================
# RESOLVE SPECIES NUMBERS (D4)
# =========================

resolved_varied = resolve_species_numbers(
    cleaned_varied,
    cleaned_dictionary
)

print("Records:", len(resolved_varied))
print("Missing SPECIES_NO:", resolved_varied["species_no"].isna().sum())
print("Unique species matched:", resolved_varied["species_no"].nunique())

print(
    resolved_varied[["scientific_name", "species_no"]]
    .head(20)
    .to_string(index=False)
)


# =========================
# MATCH COVERAGE (D4 requirement)
# =========================

report_match_coverage(resolved_varied)


# =========================
# NBN CONSISTENCY CHECK (D4)
# Only sensitive species carry an nbn_number in the dictionary —
# this proves every synonym row for a sensitive species agrees
# on the same nbn_number, so D1 can safely group them later.
# =========================

print("\n===== NBN CONSISTENCY CHECK (sensitive species) =====")
check_nbn_consistency(cleaned_dictionary)