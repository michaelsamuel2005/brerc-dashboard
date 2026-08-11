from etl.load.loader import initial_load, incremental_load
from etl.load.mode import should_run_initial_load


def _get_destination_table_status(connection, table_name: str) -> tuple[bool, bool]:
    """Inspects whether the destination table exists and contains rows."""
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_name = %s
            )
            """,
            (table_name,),
        )
        result = cur.fetchone()
        table_exists = result[0] if result else False

        table_has_rows = False
        if table_exists:
            cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            count_result = cur.fetchone()
            count = count_result[0] if count_result else 0
            table_has_rows = count > 0

    return table_exists, table_has_rows


def run_load(
    df,
    connection,
    ui_map,
):
    """
    Determines whether to run an initial (full) load or an incremental 
    upsert load based on configuration and table state.
    """
    table_name = ui_map.get("table_name", "occurrence_public")

    # Delegate database I/O to a testable helper
    table_exists, table_has_rows = _get_destination_table_status(connection, table_name)

    # Evaluate load mode using the booleans expected by mode.py
    if should_run_initial_load(table_exists, table_has_rows):
        return initial_load(
            df,
            connection,
            table_name=table_name,
        )

    return incremental_load(
        df,
        connection,
        ui_map,
        table_name=table_name,
    )