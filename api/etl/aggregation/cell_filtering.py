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

from etl.config.loader import load_safety_config

CONFIG = load_safety_config()

# DONT USE "ñ" that was previously here (invalid)

# Values which are considered verified and safe to include
ACCEPTED_VERIFIED_VALUES = set(
    CONFIG["verified_values"]["accepted"]
)

# Older records which are included but marked as legacy
LEGACY_VERIFIED_VALUES = set(
    CONFIG["verified_values"]["legacy"]
)

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