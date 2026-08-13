"""
Filters raw source records based on NBN verification standards.
Determines which rows are permitted to contribute to the public derived layer.
"""

import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

# DONT USE "ñ" that was previously here (invalid)


def _normalise_dashes(value: str) -> str:
    """
    Treat en-dash (–) and em-dash (—) as the same as a a plain hyphen (-).
    Due to BRERC real export being unclear with which hyphen it uses.
    """
    return (
        value.replace("\u2013", "-")  # en-dash –
        .replace("\u2014", "-")  # em-dash —
        .replace("ñ", "-")
    )


# Values which are considered verified and safe to include
ACCEPTED_VERIFIED_VALUES = {
    _normalise_dashes(value) for value in CONFIG["verified_values"]["accepted"]
}

# Older records which are included but marked as legacy
LEGACY_VERIFIED_VALUES = {
    _normalise_dashes(value) for value in CONFIG["verified_values"]["legacy"]
}


def filter_accepted_records(
    df: pd.DataFrame,
    verified_column: str = "verified",
) -> pd.DataFrame:
    """
    Filters source records to retain accepted and legacy statuses, 
    returning a filtered dataframe with an added 'is_legacy' flag.

    Verification status terms per NBN standard:
        Accepted - correct
        Accepted - considered correct
        Unconfirmed - plausible
        Unconfirmed - not reviewed

    """

    # Ensures the verification column exists before filtering
    required_columns = {verified_column}

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise KeyError(
            f"Missing columns required for verification filtering: "
            f"{sorted(missing_columns)}"
        )

    df = df.copy()

    # Normalise whitespace and typographic dashes for reliable comparison
    verified = (
        df[verified_column]
        .astype("string")
        .str.strip()
        .map(lambda v: _normalise_dashes(v) if pd.notna(v) else v)
    )

    # Identifies records with accepted verification status
    accepted = verified.isin(ACCEPTED_VERIFIED_VALUES)

    # Marking legacy records (NaN, empty, or legacy)
    legacy = verified.isna() | verified.eq("") | verified.isin(LEGACY_VERIFIED_VALUES)

    # Keep both accepted and legacy records
    included = accepted | legacy

    # Keep rows were included is true
    filtered_df = df.loc[included].copy()
    # Get the legacy values, from the filtered_df
    filtered_df["is_legacy"] = legacy.loc[filtered_df.index]

    return filtered_df
