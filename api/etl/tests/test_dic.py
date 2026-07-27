import pandas as pd
from etl.cleaning import clean_data


# --------------------------------------------------
# Load and clean the species dictionary
# --------------------------------------------------

dictionary_df = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/full_dictionary.csv"
)

cleaned_dictionary = clean_data(dictionary_df)


# --------------------------------------------------
# 1. One SPECIES_NO linked to multiple scientific names
# --------------------------------------------------

names_per_species = (
    cleaned_dictionary
    .groupby("species_no")["scientific"]
    .nunique()
)

possible_synonyms_by_species = names_per_species[
    names_per_species > 1
]

print("\nSpecies with multiple scientific names:")
print(possible_synonyms_by_species)


species_synonym_rows = cleaned_dictionary[
    cleaned_dictionary["species_no"].isin(
        possible_synonyms_by_species.index
    )
][
    ["scientific", "species_no", "nbn_number"]
].sort_values("species_no")

print("\nNames grouped by the same species_no:")
print(species_synonym_rows)


# --------------------------------------------------
# 2. One NBN_NUMBER linked to multiple names
# --------------------------------------------------

names_per_nbn = (
    cleaned_dictionary[
        cleaned_dictionary["nbn_number"].notna()
    ]
    .groupby("nbn_number")["scientific"]
    .nunique()
)

multiple_names_per_nbn = names_per_nbn[
    names_per_nbn > 1
]

print("\nNBN numbers with multiple scientific names:")
print(multiple_names_per_nbn)


nbn_name_rows = cleaned_dictionary[
    cleaned_dictionary["nbn_number"].isin(
        multiple_names_per_nbn.index
    )
][
    ["scientific", "species_no", "nbn_number"]
].sort_values("nbn_number")

print("\nNames grouped by the same NBN_NUMBER:")
print(nbn_name_rows)


# --------------------------------------------------
# 3. One NBN_NUMBER linked to multiple SPECIES_NO values
# --------------------------------------------------

species_per_nbn = (
    cleaned_dictionary[
        cleaned_dictionary["nbn_number"].notna()
    ]
    .groupby("nbn_number")["species_no"]
    .nunique()
)

nbn_with_multiple_species = species_per_nbn[
    species_per_nbn > 1
]

print("\nNBN numbers linked to multiple species_no values:")
print(nbn_with_multiple_species)


nbn_species_rows = cleaned_dictionary[
    cleaned_dictionary["nbn_number"].isin(
        nbn_with_multiple_species.index
    )
][
    ["scientific", "species_no", "nbn_number"]
].sort_values("nbn_number")

print("\nDetailed NBN_NUMBER -> multiple SPECIES_NO relationships:")
print(nbn_species_rows)


# --------------------------------------------------
# 4. Check whether shared NBN_NUMBER groups contain
#    sensitive species
# --------------------------------------------------

# Replace this with the actual path to your sensitive species list
sensitive_species_df = pd.read_csv(
    "/Users/tingtinghe/Documents/brerc-dashboard/data/sensitive_species.csv"
)

sensitive_species_df = clean_data(
    sensitive_species_df
)


# Get the SPECIES_NO values from the sensitive list
sensitive_species_nos = set(
    sensitive_species_df["species_no"]
    .dropna()
)


# Find the NBN_NUMBER associated with each sensitive species
sensitive_nbn_numbers = set(
    cleaned_dictionary[
        cleaned_dictionary["species_no"].isin(
            sensitive_species_nos
        )
    ]["nbn_number"]
    .dropna()
)


# Find shared-NBN groups that contain at least
# one sensitive species
shared_nbn_sensitive_groups = nbn_species_rows[
    nbn_species_rows["nbn_number"].isin(
        sensitive_nbn_numbers
    )
]


print(
    "\nShared NBN_NUMBER groups containing "
    "at least one sensitive species:"
)

print(shared_nbn_sensitive_groups)


# --------------------------------------------------
# 5. Show every species associated with those NBN
#    numbers and whether it is already sensitive
# --------------------------------------------------

related_species = cleaned_dictionary[
    cleaned_dictionary["nbn_number"].isin(
        sensitive_nbn_numbers
    )
][
    [
        "scientific",
        "species_no",
        "nbn_number"
    ]
].copy()


related_species["is_sensitive_species_no"] = (
    related_species["species_no"].isin(
        sensitive_species_nos
    )
)


print(
    "\nAll species associated with NBN_NUMBER values "
    "linked to sensitive species:"
)

print(
    related_species
    .sort_values(["nbn_number", "species_no"])
)