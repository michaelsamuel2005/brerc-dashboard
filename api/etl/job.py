import pandas as pd

from functools import lru_cache

from etl.pipeline import run_pipeline
from etl.load.loader import load_safety_config
from etl.load.metadata import get_last_load_date
from etl.reconciliation.state import get_ui_map
from etl.db import (
    get_source_connection,
    get_destination_connection,
    check_table_exists,
    check_table_has_rows,
)
from etl.load.reload import force_full_reload
from etl.load.mode import should_run_initial_load


@lru_cache(maxsize=1)
def get_config() -> dict:
    return load_safety_config()


def load_source_data(source_connection=None, watermark_date=None):
    """
    Loads BRERC source records from either CSV or database.

    In database mode, watermark_date can be used to restrict
    the query to records modified on or after that timestamp.
    """

    config = get_config()
    mode = config["source"].get("mode", "csv")
    modified_column = config["columns"]["modified_date"]

    if mode == "csv":
        df = pd.read_csv(
            config["source"]["records_path"]
        )

        if watermark_date is not None:
            df[modified_column] = pd.to_datetime(
                df[modified_column]
            )
            df = df[
                df[modified_column] >= watermark_date
            ]

        return df

    if mode == "database":
        if source_connection is None:
            raise ValueError(
                "source_connection is required when "
                "source.mode is 'database'"
            )

        query = config["source"]["records_query"]

        if watermark_date is not None:
            query = (
                f"SELECT * FROM ({query}) AS filtered_source "
                f"WHERE {modified_column} >= %(watermark_date)s"
            )

            return pd.read_sql(
                query,
                source_connection,
                params={"watermark_date": watermark_date},
            )

        return pd.read_sql(
            query,
            source_connection,
        )

    raise ValueError(
        f"Unknown source.mode: {mode!r}"
    )


def load_species_dictionary(source_connection=None):
    """
    Loads the species dictionary used for synonym-safe
    species resolution.
    """

    config = get_config()
    mode = config["source"].get("mode", "csv")

    if mode == "csv":
        return pd.read_csv(
            config["source"]["dictionary_path"]
        )

    if mode == "database":
        if source_connection is None:
            raise ValueError(
                "source_connection is required when "
                "source.mode is 'database'"
            )

        return pd.read_sql(
            config["source"]["dictionary_query"],
            source_connection,
        )

    raise ValueError(
        f"Unknown source.mode: {mode!r}"
    )


def get_current_ui_map(connection):
    """
    Retrieves the current occurrence_public state.

    Returns:
        unique_no -> content_hash
    """

    return get_ui_map(connection)


def nightly_job():
    print("Starting nightly ETL")

    try:
        config = get_config()
        mode = config["source"].get("mode", "csv")

        with get_destination_connection() as connection:
            table_name = config["destination"]["table"]

            # Check the destination state.
            table_exists = check_table_exists(
                connection,
                table_name,
            )

            table_has_rows = (
                check_table_has_rows(
                    connection,
                    table_name,
                )
                if table_exists
                else False
            )

            run_initial = should_run_initial_load(
                table_exists,
                table_has_rows,
            )

            load_mode = (
                "initial"
                if run_initial
                else "incremental"
            )

            watermark_date = None

            if (
                load_mode == "incremental"
                and mode == "database"
                and config["load"].get(
                    "incremental_check",
                    True,
                )
            ):
                watermark_date = get_last_load_date(
                    connection
                )

                if watermark_date is None:
                    load_mode = "initial"

            elif (
                load_mode == "incremental"
                and mode == "database"
            ):
                load_mode = "initial"

            # The destination-state queries above open a database
            # transaction. Finish that transaction before opening
            # the separate admin connection used for the schema
            # rebuild. Otherwise the first connection can retain
            # locks on occurrence_public and block the rebuild.
            if load_mode == "initial":
                connection.commit()

                print(
                    f"Forcing full reload of {table_name}"
                )

                force_full_reload()

            # Load source records after the destination has been
            # rebuilt.
            if mode == "database":
                with get_source_connection() as source_connection:
                    source_df = load_source_data(
                        source_connection,
                        watermark_date=watermark_date,
                    )

                    dictionary_df = load_species_dictionary(
                        source_connection
                    )
            else:
                source_df = load_source_data(
                    watermark_date=None
                )

                dictionary_df = load_species_dictionary()

            # The full reload creates a clean destination, so this
            # map now represents the current destination state.
            ui_map = get_current_ui_map(
                connection
            )

            print(
                f"Running pipeline in '{load_mode}' mode"
            )

            result = run_pipeline(
                source_df,
                dictionary_df,
                ui_map,
                connection,
                load_mode,
            )

        print("PIPELINE RESULT:", result)
        print("Nightly ETL completed")

        return result

    except Exception as error:
        print(
            f"Nightly ETL failed: {error}"
        )
        raise