from etl.load.mode import should_run_initial_load


def run_load(
    df,
    connection,
    ui_map,
):

    if should_run_initial_load(connection):
        return initial_load(
            df,
            connection,
        )

    return incremental_load(
        df,
        connection,
        ui_map,
    )