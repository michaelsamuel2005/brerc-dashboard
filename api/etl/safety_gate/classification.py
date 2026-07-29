"""
    Classify records for sensitivity using vectorised operations.

    This function is designed to process a chunk of records at a time,
    rather than one record at a time. D2

    # D3: fixed sites (roosts/setts/holts/nests/hibernacula) blur year-round.
    # BRERC has not yet supplied seasonal windows for any species, so there
    # is currently NO date-based un-blurring anywhere in this pipeline -
    # every sensitive record stays blurred regardless of record_date.
    # If/when BRERC supplies a seasonal species list with date ranges,
    # that logic would go here, and would only ever *narrow* blurring for
    # species explicitly marked seasonal - never widen it.
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

    # Creates a copy of the DF 
    df = df.copy()

    # For unresolved species: Checks if species is unresolved
    unresolved_mask = (
        df["species_unresolved"]
    )

    # Sensitive species: Checks if the species number exists in our imported list of sensitive columns
    sensitive_species_mask = (
        df["species_no"].isin(
            SENSITIVE_SPECIES_NOS
        )
    )

    # Sensitive Record Type: Checks if the type of record exists in our imported list of flagged records 
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

    # Creates new columns to flag the record as sensitive and indicate it needs to be blurred
    df["is_sensitive"] = sensitive_mask
    df["blurred"] = sensitive_mask

    # Set the default reason for all rows to "not_sensitive"
    df["sensitivity_reason"] = (
        "not_sensitive"
    )

    # Overwrites the reason:
    # .loc, finds rows where specific mask is True, and change their reason 
    df.loc[
        unresolved_mask,
        "sensitivity_reason"
    ] = "unresolved_species"

    df.loc[
        flagged_record_type_mask,
        "sensitivity_reason"
    ] = "sensitive_record_type"

    df.loc[
        sensitive_species_mask,
        "sensitivity_reason"
    ] = "sensitive_species"

    # Sets the default blurring resolution
    df["resolution_m"] = D0_FLOOR_M

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
