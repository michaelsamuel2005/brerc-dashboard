import pandas as pd

def build_id_hash_map(df: pd.DataFrame) -> dict:

    required = {
        "unique_no",
        "content_hash",
    }

    missing = required - set(df.columns)
    if missing:
        raise KeyError(
            f"Missing required columns: {sorted(missing)}"
        )

    # Creates dictionary, joining two columns, allowing easier access e.g [1:"999"]
    # unique_no is cast to str so it matches the type of record_id coming
    # back from the database (occurrence_public.record_id is VARCHAR) -
    # without this, every record looks like a mismatch (int vs str keys
    # never compare equal), causing false inserts/deletes every run.
    return dict(zip(
        df["unique_no"].astype(str),
        df["content_hash"],
    ))

"""
Builds a complete unique_no -> content_hash mapping by
combining the hash maps from each DataFrame chunk.
"""

# Takes iterable 'chunks" of dataframe combining into one dictionary
def build_id_hash_map_from_chunks(chunks) -> dict:
    # Creates empty dictionary
    source_map = {}

    # loops over dataframes
    for chunk in chunks:
        # calls function over chunk
        chunk_map = build_id_hash_map(chunk)
        # merges dictionary into overall dictionary
        source_map.update(chunk_map)

    return source_map


def diff_id_hash_maps(source_map: dict, ui_map: dict):

    # Converts IDs to sets so insert, deletes and updates
    # Able to be found using fast set operations
    source_ids = set(source_map)
    ui_ids = set(ui_map)

    # Records present in today's source data but not in UI dastabase
    inserts = source_ids - ui_ids
    # Records removed from source since previous reconciliation
    deletes = ui_ids - source_ids
    # Records that exist in both datasets
    possible_updates = source_ids & ui_ids

    # Updates is the set which only includes record whose content hash has changed
    # Create set of unique_no values
    # For each unique_no in possible_updates
    # Omly if the source has is different from ui hash
    updates = {
        unique_no 
        for unique_no in possible_updates 
        if source_map[unique_no] != ui_map[unique_no]
    }

    unchanged = possible_updates - updates

    return {
        "inserts": inserts,
        "updates": updates,
        "deletes": deletes,
        "unchanged": unchanged,
    }

# Gets dataset + ids classified as insert, updates, deletes 
def get_reconciliation_records(
        source_df: pd.DataFrame,
        changes: dict,
    ) -> dict:

    # changes["inserts"]/["updates"] are now sets of STRINGS (see
    # build_id_hash_map), so unique_no must be cast to str here too
    # before comparing, or .isin() will match nothing.
    unique_no_str = source_df["unique_no"].astype(str)

    # Retrieves the full source rows corresponding to each reconciliation action
    inserts = source_df[
        unique_no_str.isin(changes["inserts"])
    ].copy()

    updates = source_df[
        unique_no_str.isin(changes["updates"])
    ].copy()

    return {
        "inserts": inserts,
        "updates": updates,
        "deletes": changes["deletes"],
        "unchanged": changes["unchanged"],
    }