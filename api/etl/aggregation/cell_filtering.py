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

# DONT USE "ñ" that was previously here (invalid)

ACCEPTED_VERIFIED_VALUES = {
    "Accepted \u2013 correct",
    "Accepted \u2013 considered correct",
    "Accepted",  # deprecated older grouping, still seen in legacy data
}

LEGACY_VERIFIED_VALUES = {
    "BRERC",
}

def filter_accepted_records(
        df: pd.DataFrame,
        verified_column: str = "verified",
    ) -> pd.DataFrame:

    df = df.copy()

    verified = (
        df[verified_column]
        .astype("string")
        .str.strip()
    )

    accepted = verified.isin(ACCEPTED_VERIFIED_VALUES)

    legacy = (
        verified.isna()
        | verified.eq("")
        | verified.isin(LEGACY_VERIFIED_VALUES)
    )

    included = accepted | legacy

    filtered_df = df.loc[included].copy()
    filtered_df["is_legacy"] = legacy.loc[filtered_df.index]

    return filtered_df