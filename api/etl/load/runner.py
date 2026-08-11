"""
Coordinates database loading by checking table states and automatically 
switching between initial (full wipe) and incremental (upsert) modes.
"""

from etl.load.loader import (
    initial_load,
    incremental_load,
)
from etl.load.mode import (
    should_run_initial_load,
)


def _get_destination_table_status(
    connection,
    table_name: str,
) -> tuple[bool, bool]:
    """
    Checks whether the destination table exists in the database and 
    whether it contains any rows.
    """

    with connection.cursor() as cur:
        # Check if the table actually exists in PostgreSQL's information schema
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = %s
            )
            """,
            (table_name,),
        )

        result = cur.fetchone()
        table_exists = result[0] if result else False

        table_has_rows = False

        # If the table exists, check if there's at least one row inside it
        if table_exists:
            cur.execute(
                f"""
                SELECT EXISTS (
                    SELECT 1
                    FROM "public"."{table_name}"
                    LIMIT 1
                )
                """
            )

            result = cur.fetchone()
            table_has_rows = result[0] if result else False

    return table_exists, table_has_rows


def run_load(
    df,
    connection,
    ui_map,
):
    """
    Evaluates destination table health and routes data to either 
    an initial full load or an incremental upsert load.
    """

    # Get the table name from the config map, defaulting to occurrence_public
    table_name = ui_map.get(
        "table_name",
        "occurrence_public",
    )

    # Check if the destination table exists and has records
    table_exists, table_has_rows = _get_destination_table_status(
        connection,
        table_name,
    )

    # If conditions dictate a clean slate, run an initial load (full wipe)
    if should_run_initial_load(
        table_exists,
        table_has_rows,
    ):
        return initial_load(
            df,
            connection,
            table_name=table_name,
        )

    # Otherwise, perform an incremental update (upsert)
    return incremental_load(
        df,
        connection,
        ui_map,
        table_name=table_name,
    )
