"""
Records are classified as sensitive if they:
- belong to a sensitive species,
- have a sensitive record type, or
- contain an unresolved species.

Fixed sites (e.g. roosts, holts, nests) are currently blurred year-round.
Seasonal exceptions can be added in future if required by the data provider.
"""

import pandas as pd 

from etl.safety_gate.rules import (
    DEFAULT_SENSITIVE_RESOLUTION_M,
    FLAGGED_RECORD_TYPES,
    SENSITIVE_SPECIES_NOS,
    SPECIES_RESOLUTIONS_M,
    D0_FLOOR_M,
)

def classify_chunk(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

    df = df.copy()

    # Required columns for classification to run
    required_columns = {
        "species_no",
        "species_unresolved",
        "record_type"
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"classify_chunk() missing required columns: {sorted(missing)}"
        )

    # ---------------------
    # Setting up the masks:
    # ---------------------

    # Unresolved species: True for records who species can't be
    unresolved_mask = (
        df["species_unresolved"]
    )
    # Sensitive species: True for records belonging to a sensitive species.
    sensitive_species_mask = (
        df["species_no"].isin(
            SENSITIVE_SPECIES_NOS
        )
    )
    # Sensitive Record Type: True for records whose record type is classified as sensitive.
    flagged_record_type_mask = (
        df["record_type"].isin(
            FLAGGED_RECORD_TYPES
        )
    )

    # Combining the masks: If row is TRUE in any of the above masks, it's considered sensitive
    sensitive_mask = (
        unresolved_mask
        | sensitive_species_mask
        | flagged_record_type_mask
    )

    # Two new columns: Sensitive records are marked, and marked needed location blurring 
    df["is_sensitive"] = sensitive_mask
    df["blurred"] = sensitive_mask

    # Store all reasons why a record was classified as sensitive.
    # Start with an empty list for every record.
    df["sensitivity_reason"] = [[] for _ in range(len(df))]

    # Add "unresolved_species" to records where the species could not be resolved.
    df.loc[
        unresolved_mask,
        "sensitivity_reason"
    ] = df.loc[
        unresolved_mask,
        "sensitivity_reason"
    ].apply(lambda x: x + ["unresolved_species"])

    # Add "sensitive_record_type" to records with a flagged record type.
    df.loc[
        flagged_record_type_mask,
        "sensitivity_reason"
    ] = df.loc[
        flagged_record_type_mask,
        "sensitivity_reason"
    ].apply(lambda x: x + ["sensitive_record_type"])

    # Add "sensitive_species" to records containing a sensitive species.
    df.loc[
        sensitive_species_mask,
        "sensitivity_reason"
    ] = df.loc[
        sensitive_species_mask,
        "sensitivity_reason"
    ].apply(lambda x: x + ["sensitive_species"])

    # Convert empty lists into "not_sensitive" for records that triggered no rules.
    df.loc[
        df["sensitivity_reason"].apply(len) == 0,
        "sensitivity_reason"
    ] = "not_sensitive"

    # Every record is set with the minimum (D0) resolution by default
    df["resolution_m"] = D0_FLOOR_M

    # Increase the blur distance for sensitive records
    df.loc[
        sensitive_mask,
        "resolution_m"
    ] = DEFAULT_SENSITIVE_RESOLUTION_M

    # # Apply species-specific resolutions.
    # for species_no, resolution in (
    #     SPECIES_RESOLUTIONS_M.items()
    # ):

    #     species_mask = (
    #         df["species_no"]
    #         == species_no
    #     )

    #     df.loc[
    #         species_mask
    #         & sensitive_species_mask,
    #         "resolution_m"
    #     ] = resolution

    return df
