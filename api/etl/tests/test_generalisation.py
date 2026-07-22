import pandas as pd

from etl.cleaning import (
    clean_data,
)

from etl.rules import SENSITIVE_SPECIES_NOS

from etl.filtering import (
    filter_sensitive_species
)

from etl.generalisation import (
    resolve_species_numbers,
    generalise_sensitive_locations,
    snap_to_grid
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

print(
    "Records:",
    len(resolved_varied)
)

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
    ]
    .head(20)
    .to_string(index=False)
)


# =========================
# IDENTIFY SENSITIVE RECORDS
# =========================

identified_varied = filter_sensitive_species(
    resolved_varied
)

# =========================
# GENERALISE LOCATIONS
# =========================

generalised_varied = generalise_sensitive_locations(
    identified_varied,
    easting_column="eastings",
    northing_column="northings",
    sensitive_column="is_sensitive"
)


# =========================
# SHOW GENERALISED RECORDS
# =========================

print(
    "\n===== GENERALISED SENSITIVE RECORDS ====="
)

print(
    generalised_varied[
        generalised_varied["is_sensitive"] == True
    ][
        [
            "eastings",
            "northings",
            "is_sensitive"
        ]
    ]
    .head(20)
    .to_string(index=False)
)


# =========================
# COMPARE ORIGINAL VS GENERALISED
# =========================

comparison = pd.DataFrame({

    "original_easting":
        identified_varied.loc[
            identified_varied["is_sensitive"],
            "eastings"
        ],

    "generalised_easting":
        generalised_varied.loc[
            generalised_varied["is_sensitive"],
            "eastings"
        ],

    "original_northing":
        identified_varied.loc[
            identified_varied["is_sensitive"],
            "northings"
        ],

    "generalised_northing":
        generalised_varied.loc[
            generalised_varied["is_sensitive"],
            "northings"
        ]

})


print(
    "\n===== ORIGINAL VS GENERALISED ====="
)

print(
    comparison
    .head(20)
    .to_string(index=False)
)


# =========================
# GENERALISATION CHECKS
# =========================

print(
    "\n===== GENERALISATION CHECK ====="
)

print(
    "Sensitive records:",
    len(comparison)
)

print(
    "Easting coordinates changed:",
    (
        comparison["original_easting"]
        != comparison["generalised_easting"]
    )
    .sum()
)

print(
    "Northing coordinates changed:",
    (
        comparison["original_northing"]
        != comparison["generalised_northing"]
    )
    .sum()
)


# =========================
# TEST SNAP TO GRID
# =========================

print(
    "\n===== SNAP TO GRID TEST ====="
)

print(
    "456789 ->",
    snap_to_grid(
        456789,
        10_000
    )
)

print(
    "123456 ->",
    snap_to_grid(
        123456,
        10_000
    )
)