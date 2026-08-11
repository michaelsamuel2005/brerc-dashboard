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


# Loaded lazily (not at import time) so importing this module never
# requires safety.yaml to already exist on disk - only calling
# get_config() does. lru_cache means it's still only read once per
# process, just on first use rather than at import.

@lru_cache(maxsize=1)
def get_config() -> dict:
    return load_safety_config()


def load_source_data(source_connection=None, watermark_date=None):
    """
    For loading BRERC's raw records:

    Reads from CSV if CONFIG["source"]["mode"] == "csv"
    Queries the source database directly if "database" (production)

    If watermark_date is given, only rows modified on/after that
    timestamp are returned (incremental load). If watermark_date is
    None, every row is returned (initial/full load).
    """

    config = get_config()
    mode = config["source"].get("mode", "csv")
    modified_column = config["columns"]["modified_date"]

    if mode == "csv":
        df = pd.read_csv(
            config["source"]["records_path"]
        )

        if watermark_date is not None:
            df[modified_column] = pd.to_datetime(df[modified_column])
            df = df[df[modified_column] >= watermark_date]

        return df

    if mode == "database":
        if source_connection is None:
            raise ValueError(
                "source_connection is required when "
                "source.mode is 'database'"
            )

        query = config["source"]["records_query"]

        if watermark_date is not None:
            # Wrap the configured query so incremental filtering works
            # regardless of what the base query already selects.
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

    raise ValueError(f"Unknown source.mode: {mode!r}")


def load_species_dictionary(source_connection=None):
    """
    Loads species lookup table used for synonym-safe species resolution.
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

    raise ValueError(f"Unknown source.mode: {mode!r}")


def get_current_ui_map(connection):
    """
    Retrieves current occurrence_public state.

    Used by reconciliation:
        unique_no -> content_hash

    Allows the ETL to detect:
        - inserts
        - updates
        - deletes
    """

    return get_ui_map(connection)

def nightly_job():
    print("Starting nightly ETL")

    try:
        config = get_config()
        mode = config["source"].get("mode", "csv")

        with get_destination_connection() as connection:
            table_name = config["destination"]["table"]  # "occurrence_public"

            table_exists = check_table_exists(connection, table_name)
            table_has_rows = (
                check_table_has_rows(connection, table_name)
                if table_exists
                else False
            )

            run_initial = should_run_initial_load(
                table_exists,
                table_has_rows,
            )
            load_mode = "initial" if run_initial else "incremental"

            # Only look for a watermark when we're actually attempting an
            # incremental load AND the source is a database.
            #
            # The supplied CSV fixture does not contain the configured
            # date_mdb_modified column, so CSV mode cannot use a watermark.
            # Reconciliation still detects inserts, updates and deletes
            # by comparing content hashes.
            watermark_date = None

            if (
                load_mode == "incremental"
                and mode == "database"
                and config["load"].get("incremental_check", True)
            ):
                watermark_date = get_last_load_date(connection)

                if watermark_date is None:
                    # Table exists/has rows but carries no Load_date yet
                    # (e.g. pre-migration data) - fall back to a full load
                    # rather than incrementally filtering against nothing.
                    load_mode = "initial"

            elif (
                load_mode == "incremental"
                and mode == "database"
            ):
                # incremental_check is off - always do a full load.
                load_mode = "initial"

            if load_mode == "initial":
                print(f"Forcing full reload of {table_name}")
                force_full_reload()

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

            ui_map = get_current_ui_map(connection)

            print(f"Running pipeline in '{load_mode}' mode")

            result = run_pipeline(
                source_df,
                dictionary_df,
                ui_map,
                connection,
                load_mode,
            )

        print("Nightly ETL completed")
        return result

    except Exception as error:
        print(f"Nightly ETL failed: {error}")
        raise