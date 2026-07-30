# Opens database connection, cursor can send SQL commands to postgreSQL

def get_ui_map(connection) -> dict:
    with connection:
        with connection.cursor() as cursor:
            # Gets every records ID and content hash
            cursor.execute(
                """
                SELECT record_id, content_hash
                FROM occurrence_public
                """
            )

            rows = cursor.fetchall()

    # Returns dictionary for every row in rows where:
    # Key is "record_id" and value is "content_hash"
    return {
        row["record_id"]: row["content_hash"]
        for row in rows
    }