"""
Functions for comparing source and UI database records to determine 
inserts, updates, and deletes during ETL reconciliation.
"""

from datetime import date, datetime
import logging
import pandas as pd

import etl.columns as C

logger = logging.getLogger(__name__)


def build_id_hash_map(df: pd.DataFrame) -> dict:
    """
    Maps each record's unique number to its content hash.

    NOTE: content_hash is retained for storage/audit purposes only.
    It is NOT used for change detection — see build_id_modified_map.
    """

    required = {
        C.UNIQUE_NO,
        "content_hash",
    }

    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {sorted(missing)}")

    # unique_no is cast to str so it matches the type of record_id coming
    # back from the database (occurrence_public.record_id is VARCHAR).
    # Without this, int vs str key mismatches cause false inserts/deletes every run.
    return dict(
        zip(
            df[C.UNIQUE_NO].astype(str),
            df["content_hash"],
        )
    )


def build_id_modified_map(df: pd.DataFrame) -> dict:
    """
    Maps each record's unique number to its date_mdb_modified value.

    This is the map used to drive insert/update/delete decisions, per
    reviewer feedback: relying on a source-side SHA hash to detect changes
    assumes a known PostgreSQL version/hash algorithm, which we can't
    guarantee on the client's enterprise instance. date_mdb_modified is a
    reliable, source-controlled signal regardless of PG version or config.
    """
    required = {C.UNIQUE_NO, C.MODIFIED_DATE}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {sorted(missing)}")

    return dict(
        zip(
            df[C.UNIQUE_NO].astype(str),
            df[C.MODIFIED_DATE],
        )
    )


# Takes iterable 'chunks' of dataframe, combining into one dictionary
def build_id_hash_map_from_chunks(chunks) -> dict:
    """Combines individual hash maps from multiple dataframe chunks into one master dictionary."""
    source_map = {}

    for chunk in chunks:
        chunk_map = build_id_hash_map(chunk)
        source_map.update(chunk_map)

    return source_map


def build_id_modified_map_from_chunks(chunks) -> dict:
    """Combines individual date_mdb_modified maps from multiple dataframe chunks into one master dictionary."""
    source_map = {}

    for chunk in chunks:
        chunk_map = build_id_modified_map(chunk)
        source_map.update(chunk_map)

    return source_map


def normalise_modified_date(value):
    """
    Reduces a modified-date value to a plain calendar date so the two sides of
    the comparison agree on type.

    BRERC's date_mdb_modified is a DATE (datetime.date), but occurrence_public
    stores it as TIMESTAMPTZ, so it comes back as a timezone-aware datetime at
    local midnight. date(2026, 9, 19) != datetime(2026, 9, 19, 0, 0, tz) in
    Python, so without this every record compared as "changed".
    """
    if value is None or (not isinstance(value, (date, datetime)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def diff_id_modified_maps(
    source_map: dict,
    ui_map: dict,
    source_hash_map: dict | None = None,
    ui_hash_map: dict | None = None,
):
    """
    Compares source and UI date_mdb_modified maps using set operations to isolate 
    new records (inserts), removed records (deletes), and modified records (updates).

    A record counts as updated when its date_mdb_modified differs OR, when both
    hash maps are given, its content_hash differs. The hash catches edits made
    without the source bumping date_mdb_modified. Both hashes are computed by
    this pipeline in Python (etl.reconciliation.hashing), so they do not depend
    on the source database's PostgreSQL version.

    deletes is (ui_ids - source_ids), so source_map must cover the COMPLETE
    source, not a window of recent changes.
    """
    source_ids = set(source_map)
    ui_ids = set(ui_map)

    # Records present in today's source data but not in UI database
    inserts = source_ids - ui_ids

    # Records removed from source since previous reconciliation
    # (pure ID-set diff — does not depend on hashing or modified dates)
    deletes = ui_ids - source_ids

    # Records that exist in both datasets
    possible_updates = source_ids & ui_ids

    # Identify records where date_mdb_modified has actually changed
    compare_hashes = source_hash_map is not None and ui_hash_map is not None

    updates = {
        unique_no
        for unique_no in possible_updates
        if normalise_modified_date(source_map[unique_no])
        != normalise_modified_date(ui_map[unique_no])
        or (
            compare_hashes
            and source_hash_map.get(unique_no) != ui_hash_map.get(unique_no)
        )
    }

    unchanged = possible_updates - updates

    logger.info(
        "Compared with the dashboard: %d new, %d changed, %d removed from the source.",
        len(inserts),
        len(updates),
        len(deletes),
    )

    return {
        "inserts": inserts,
        "updates": updates,
        "deletes": deletes,
        "unchanged": unchanged,
    }