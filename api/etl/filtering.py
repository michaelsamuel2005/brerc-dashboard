import pandas as pd
from etl.rules import (
    SENSITIVE_SPECIES_NOS,
    FLAGGED_RECORD_TYPES
)


def filter_sensitive_species(
    df: pd.DataFrame
) -> pd.DataFrame:

    sensitive_species_mask = (
        df["species_no"]
        .isin(SENSITIVE_SPECIES_NOS)
    )

    flagged_record_type_mask = (
        df["record_type"]
        .isin(FLAGGED_RECORD_TYPES)
    )

    sensitive_mask = (
        sensitive_species_mask
        |
        flagged_record_type_mask
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
        "Sensitive species records:",
        sensitive_species_mask.sum()
    )

    print(
        "Flagged record type records:",
        flagged_record_type_mask.sum()
    )

    print(
        "Total sensitive records:",
        sensitive_mask.sum()
    )
    return df[~sensitive_mask].copy()