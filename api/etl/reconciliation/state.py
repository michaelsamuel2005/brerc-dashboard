"""
Database retrieval functions for the reconciliation pipeline, 
fetching existing record states from the UI database.
"""

def get_ui_map(connection) -> dict:
    """
    Fetches all record IDs and date_mdb_modified values from the 'occurrence_public' 
    table and returns them as a dictionary mapping string record IDs to their 
    last-modified timestamp.

    Used to drive insert/update/delete decisions during reconciliation (see
    diff_id_modified_maps). content_hash is no longer queried here since it's
    not used for change detection.
    """
    with connection.cursor() as cursor:
        # Query every record's identifier and modified-date from the UI database
        cursor.execute(
            """
            SELECT record_id, date_mdb_modified
            FROM occurrence_public
            """
        )
        rows = cursor.fetchall()

    # record_id is cast to str so its type matches build_id_modified_map's
    # unique_no keys (also cast to str). Without this type alignment, int vs str
    # key comparisons fail, causing every record to look like a fresh insert AND delete.
    return {str(row["record_id"]): row["date_mdb_modified"] for row in rows}