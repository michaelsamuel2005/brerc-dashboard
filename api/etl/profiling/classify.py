"""
Classifies occurrence records as sensitive based on protected species lists, 
flagged record types, and fail-closed rules for unresolved species.
"""

import pandas as pd

from etl.safety_gate.rules import (
    load_sensitive_species,
    FLAGGED_RECORD_TYPES,
)


def classify_sensitive_species(df: pd.DataFrame) -> pd.DataFrame:
    """
    Evaluates records against sensitivity criteria (species lists, NBN numbers, 
    record types, and unresolved status), prints an audit report, and flags 
    sensitive rows.
    """
    df = df.copy()

    # Load master lists of sensitive species identifiers and NBN numbers
    sensitive_species_nos, sensitive_nbn_numbers = load_sensitive_species()

    # Build individual boolean masks for each sensitivity trigger
    sensitive_species_mask = df["species_no"].isin(sensitive_species_nos)
    sensitive_nbn_mask = df["nbn_number"].isin(sensitive_nbn_numbers)
    flagged_record_type_mask = df["record_type"].isin(FLAGGED_RECORD_TYPES)
    unresolved_mask = df["species_unresolved"]

    # Combine all rules into a single catch-all sensitivity mask
    sensitive_mask = (
        sensitive_species_mask
        | sensitive_nbn_mask
        | flagged_record_type_mask
        | unresolved_mask
    )

    # Print a diagnostic breakdown of sensitive records for pipeline logging
    print("\n===== SENSITIVE RECORDS =====")
    sensitive_record_types = df.loc[sensitive_mask, "record_type"].value_counts()
    print(sensitive_record_types)

    print("Sensitive via species_no:", sensitive_species_mask.sum())
    print("Sensitive via nbn_number:", sensitive_nbn_mask.sum())
    print("Sensitive via record_type:", flagged_record_type_mask.sum())
    print("Sensitive via unresolved species (fail-closed):", unresolved_mask.sum())
    print("Total sensitive records:", sensitive_mask.sum())

    # Sanity check: species_no and nbn_number should agree on sensitivity.
    # Any mismatch points to an upstream data assignment error worth investigating.
    mismatch = df[sensitive_species_mask != sensitive_nbn_mask]

    if len(mismatch) > 0:
        print(
            f"\n {len(mismatch)} records where species_no and "
            "nbn_number sensitivity checks disagree:"
        )

        print(
            mismatch[["scientific_name", "species_no", "nbn_number"]].drop_duplicates()
        )
    else:
        print("\nspecies_no and nbn_number sensitivity checks agree on all records.")

    # Attach the final classification flag to the dataframe
    df["is_sensitive"] = sensitive_mask

    return df
