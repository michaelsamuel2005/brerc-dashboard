"""
Database retrieval functions for the reconciliation pipeline, 
fetching existing record states from the UI database.
"""

def get_ui_map(connection) -> dict:
    """
    Fetches all record IDs and content hashes from the 'occurrence_public' table 
    and returns them as a dictionary mapping string record IDs to their content hashes.
    """
    with connection.cursor() as cursor:
        # Query every record's identifier and content hash from the UI database
        cursor.execute(
            """
            SELECT record_id, content_hash
            FROM occurrence_public
            """
        )
        rows = cursor.fetchall()

    # record_id is cast to str so its type matches build_id_hash_map's
    # unique_no keys (also cast to str). Without this type alignment, int vs str
    # key comparisons fail, causing every record to look like a fresh insert AND delete.
    return {str(row["record_id"]): row["content_hash"] for row in rows}
