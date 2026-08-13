"""
Functions for comparing source and UI database records to determine 
inserts, updates, and deletes during ETL reconciliation.
"""

import logging
import pandas as pd

from etl.load.loader import load_safety_config

logger = logging.getLogger(__name__)

CONFIG = load_safety_config()
MODIFIED_COLUMN = CONFIG["columns"]["modified_date"]


def build_id_hash_map(df: pd.DataFrame) -> dict:
    """
    Maps each record's unique number to its content hash.

    NOTE: content_hash is retained for storage/audit purposes only.
    It is NOT used for change detection — see build_id_modified_map.
    """

    required = {
        "unique_no",
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
            df["unique_no"].astype(str),
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
    required = {"unique_no", MODIFIED_COLUMN}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {sorted(missing)}")

    return dict(
        zip(
            df["unique_no"].astype(str),
            df[MODIFIED_COLUMN],
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


def diff_id_modified_maps(source_map: dict, ui_map: dict):
    """
    Compares source and UI date_mdb_modified maps using set operations to isolate 
    new records (inserts), removed records (deletes), and modified records (updates).

    Renamed from diff_id_hash_maps: the comparison logic itself is unchanged
    (it's a generic id -> value diff), only the maps passed in have changed
    from content_hash-based to date_mdb_modified-based.
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
    updates = {
        unique_no
        for unique_no in possible_updates
        if source_map[unique_no] != ui_map[unique_no]
    }

    unchanged = possible_updates - updates

    logger.info(
        "Reconciliation diff complete: %d records to insert, %d to update, %d to delete.",
        len(inserts),
        len(updates),
        len(deletes),
    )

    if deletes:
        logger.warning(
            "Reconciliation: Identified %d obsolete records to delete from the UI database.",
            len(deletes),
        )

    return {
        "inserts": inserts,
        "updates": updates,
        "deletes": deletes,
        "unchanged": unchanged,
    }