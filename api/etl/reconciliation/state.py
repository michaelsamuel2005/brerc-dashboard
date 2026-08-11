# Opens database connection, cursor can send SQL commands to postgreSQL


def get_ui_map(connection) -> dict:
    with connection.cursor() as cursor:
        # Gets every records ID and content hash
        cursor.execute(
            """
            SELECT record_id, content_hash
            FROM occurrence_public
            """
        )
        rows = cursor.fetchall()

    # record_id is cast to str so its type matches build_id_hash_map's
    # unique_no keys (also cast to str) - without this, int vs str
    # keys never compare equal in the reconciliation diff, causing
    # every record to look like a fresh insert AND a delete each run.
    return {str(row["record_id"]): row["content_hash"] for row in rows}
