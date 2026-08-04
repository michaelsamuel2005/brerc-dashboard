import pandas as pd

from etl.pipeline import run_pipeline
from etl.config.loader import load_safety_config
from etl.reconciliation.state import get_ui_map
from etl.db import get_source_connection
from app.db import get_connection

CONFIG = load_safety_config()

def load_source_data(source_connection=None):
    """
    For loading BRERC's raw records: 
    
    Reads from CSV if CONFIG["source"]["mode"] == "csv"
    Queries the source database directly if "database" (production)
    """

    mode = CONFIG["source"].get("mode", "csv")

    if mode == "csv":
        return pd.read_csv(
            CONFIG["source"]["records_path"]
        )

    if mode == "database":
        if source_connection is None:
            raise ValueError(
                "source_connection is required when "
                "source.mode is 'database'"
            )
        return pd.read_sql(
            CONFIG["source"]["records_query"],
            source_connection,
        )
    raise ValueError(f"Unknown source.mode: {mode!r}")

def load_species_dictionary(source_connection=None):
    """
    Loads species lookup table used for synonym-safe species resolution.
    """
    mode = CONFIG["source"].get("mode", "csv")

    if mode == "csv":
        return pd.read_csv(
            CONFIG["source"]["dictionary_path"]
        )
    
    if mode == "database":
        if source_connection is None:
            raise ValueError(
                "source_connection is required when "
                "source.mode is 'database'"
            )
        return pd.read_sql(
            CONFIG["source"]["dictionary_query"],
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
        mode = CONFIG["source"].get("mode", "csv")

        if mode == "database":
            with get_source_connection() as source_connection:
                source_df = load_source_data(source_connection)
                dictionary_df = load_species_dictionary(source_connection)
        else:
            source_df = load_source_data()
            dictionary_df = load_species_dictionary()

        with get_connection() as connection:
            ui_map = get_current_ui_map(connection)

            result = run_pipeline(
                source_df,
                dictionary_df,
                ui_map,
                connection,
            )

        print("Nightly ETL completed")
        return result

    except Exception as error:
        print(f"Nightly ETL failed: {error}")
        raise



if __name__ == "__main__":
    nightly_job()