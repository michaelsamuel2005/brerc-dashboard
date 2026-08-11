import pandas as pd

def build_id_hash_map(df: pd.DataFrame) -> dict:
    return dict(zip(df["unique_no"], df["content_hash"]))


def diff_id_hash_maps(source_map: dict, ui_map: dict):
    source_ids = set(source_map)
    ui_ids = set(ui_map)

    inserts = source_ids - ui_ids
    deletes = ui_ids - source_ids
    possible_updates = source_ids & ui_ids

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

def get_reconciliation_records(
        source_df: pd.DataFrame,
        changes: dict,
    ) -> dict:

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