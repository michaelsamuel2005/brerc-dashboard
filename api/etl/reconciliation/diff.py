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
    return dict(zip(df["unique_no"], df["content_hash"]))


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

    # Retrieves the full source rows corresponding to each reconciliation action
    inserts = source_df[
        source_df["unique_no"].isin(changes["inserts"])
    ].copy()

    updates = source_df[
        source_df["unique_no"].isin(changes["updates"])
    ].copy()

    return {
        "inserts": inserts,
        "updates": updates,
        "deletes": changes["deletes"],
        "unchanged": changes["unchanged"],
    }