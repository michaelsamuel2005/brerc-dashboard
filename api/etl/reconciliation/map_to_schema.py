"""
    Maps the safety pipeline's output (PUBLIC_COLUMNS shape) onto
    occurrence_public's real column names (db/b6_schema.sql).

    grid_ref and locality are both sourced from coarse_locality today
    (grid square only - unitary authority data doesn't exist yet, see
    add_coarse_locality's own note). They will diverge naturally once
    that data lands: grid_ref stays grid-square-only, locality
    becomes the fuller "authority + grid square" D0 description. No
    code change needed here when that happens - just a richer
    coarse_locality value flowing through the same column.

    verified = NOT is_legacy. Safe because filter_accepted_records's
    accepted/legacy masks are mutually exclusive by construction.
"""

import pandas as pd


def map_to_occurrence_public(safe_df: pd.DataFrame) -> pd.DataFrame:
    df = safe_df.copy()

    df["record_year"] = pd.to_datetime(
        df["record_date"], dayfirst=True
    ).dt.year

    return pd.DataFrame({
        "record_id": df["unique_no"],
        "species_id": df["species_no"],
        "record_year": df["record_year"],
        "grid_ref": df["coarse_locality"],
        "locality": df["coarse_locality"],
        "precision_metres": df["effective_resolution_m"],
        "verified": ~df["is_legacy"].astype(bool),
        "content_hash": df["content_hash"],
    })