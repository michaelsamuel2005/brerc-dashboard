def get_ui_map(connection) -> dict:
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT record_id, content_hash
                FROM occurrence_public
                """
            )

            rows = cursor.fetchall()

    return {
        row["record_id"]: row["content_hash"]
        for row in rows
    }