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
    Checks whether the destination table exists and
    whether it contains any rows.
    """

    with connection.cursor() as cur:
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

        table_exists = (
            result[0]
            if result
            else False
        )

        table_has_rows = False

        if table_exists:
            cur.execute(
                f'''
                SELECT EXISTS (
                    SELECT 1
                    FROM "public"."{table_name}"
                    LIMIT 1
                )
                '''
            )

            result = cur.fetchone()

            table_has_rows = (
                result[0]
                if result
                else False
            )

    return table_exists, table_has_rows


def run_load(
    df,
    connection,
    ui_map,
):
    """
    Determines whether to perform an initial load or
    incremental load based on the destination table state.
    """

    table_name = ui_map.get(
        "table_name",
        "occurrence_public",
    )

    table_exists, table_has_rows = (
        _get_destination_table_status(
            connection,
            table_name,
        )
    )

    if should_run_initial_load(
        table_exists,
        table_has_rows,
    ):
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