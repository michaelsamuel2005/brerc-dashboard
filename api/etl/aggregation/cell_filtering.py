"""
filter_accepted_records():
    - Take the records loaded from the source
    - Return only records allowed to contribute to the public derived layer

Verification status terms per NBN standard:
    Accepted - correct
    Accepted - considered correct
    Unconfirmed - plausible
    Unconfirmed - not reviewed

Deprecated older groupings still seen in older data: "Accepted",
"Unconfirmed" (bare, no dash) - included here as fallbacks since
BRERC's older records may still use them.
"""

import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()

# DONT USE "ñ" that was previously here (invalid)

def _normalise_dashes(value: str) -> str:
    """
    Treat en-dash (–) and em-dash (—) the same as a plain hyphen (-).
    We don't know for certain whether BRERC's real export uses a plain
    hyphen or a typographic dash in values like "Accepted - correct",
    so both config values and incoming data are normalised the same
    way before comparison, rather than betting on one or the other.
    """
    return (
        value
        .replace("\u2013", "-")  # en-dash –
        .replace("\u2014", "-")  # em-dash —
        .replace("ñ", "-")  
    )

# Values which are considered verified and safe to include
ACCEPTED_VERIFIED_VALUES = {
    _normalise_dashes(value)
    for value in CONFIG["verified_values"]["accepted"]
}

# Older records which are included but marked as legacy
LEGACY_VERIFIED_VALUES = {
    _normalise_dashes(value)
    for value in CONFIG["verified_values"]["legacy"]
}

def filter_accepted_records(
        df: pd.DataFrame,
        verified_column: str = "verified",
    ) -> pd.DataFrame:
    
    # Ensures the verification column exists before filtering
    required_columns = {verified_column}

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise KeyError(
            f"Missing columns required for verification filtering: "
            f"{sorted(missing_columns)}"
        )

    df = df.copy()

    # Converts values to strings & removes whitespace
    verified = (
        df[verified_column]
        .astype("string")
        .str.strip()
        .map(lambda v: _normalise_dashes(v) if pd.notna(v) else v)
    )

    # Identifies records with accepted verification status
    accepted = verified.isin(ACCEPTED_VERIFIED_VALUES)

    # Marking legacy records (NaN, empty, or legacy)
    legacy = (
        verified.isna()
        | verified.eq("")
        | verified.isin(LEGACY_VERIFIED_VALUES)
    )

    # Keep both accepted and legacy records
    included = accepted | legacy

    # Keep rows were included is true
    filtered_df = df.loc[included].copy()
    # Get the legacy values, from the filtered_df 
    filtered_df["is_legacy"] = legacy.loc[filtered_df.index]

    return filtered_df