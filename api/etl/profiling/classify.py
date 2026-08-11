import pandas as pd

from etl.safety_gate.rules import (
    load_sensitive_species,
    FLAGGED_RECORD_TYPES,
)


def classify_sensitive_species(
    df: pd.DataFrame
) -> pd.DataFrame:

    df = df.copy()

    sensitive_species_nos, sensitive_nbn_numbers = (
        load_sensitive_species()
    )

    sensitive_species_mask = df["species_no"].isin(
        sensitive_species_nos
    )

    sensitive_nbn_mask = df["nbn_number"].isin(
        sensitive_nbn_numbers
    )

    flagged_record_type_mask = df["record_type"].isin(
        FLAGGED_RECORD_TYPES
    )

    unresolved_mask = df["species_unresolved"]

    sensitive_mask = (
        sensitive_species_mask
        | sensitive_nbn_mask
        | flagged_record_type_mask
        | unresolved_mask
    )

    print("\n===== SENSITIVE RECORDS =====")

    sensitive_record_types = (
        df.loc[
            sensitive_mask,
            "record_type"
        ]
        .value_counts()
    )

    print(sensitive_record_types)

    print(
        "Sensitive via species_no:",
        sensitive_species_mask.sum()
    )

    print(
        "Sensitive via nbn_number:",
        sensitive_nbn_mask.sum()
    )

    print(
        "Sensitive via record_type:",
        flagged_record_type_mask.sum()
    )

    print(
        "Sensitive via unresolved species (fail-closed):",
        unresolved_mask.sum()
    )

    print(
        "Total sensitive records:",
        sensitive_mask.sum()
    )

    # Sanity check: species_no and nbn_number should agree on
    # sensitivity. Any mismatch suggests an error in how species_no
    # was assigned upstream and is worth investigating manually.
    mismatch = df[
        sensitive_species_mask != sensitive_nbn_mask
    ]

    if len(mismatch) > 0:
        print(
            f"\n {len(mismatch)} records where species_no and "
            "nbn_number sensitivity checks disagree:"
        )

        print(
            mismatch[
                [
                    "scientific_name",
                    "species_no",
                    "nbn_number"
                ]
            ].drop_duplicates()
        )

    else:
        print(
            "\nspecies_no and nbn_number sensitivity checks "
            "agree on all records."
        )

    df["is_sensitive"] = sensitive_mask

    return df