import pandas as pd

from etl.pipeline import run_pipeline
from etl.config.loader import load_safety_config
from etl.reconciliation.state import get_ui_map
from app.db import get_connection


CONFIG = load_safety_config()


def load_source_data():
    """
    Development version:
    Loads BRERC records from CSV.

    Later:
    Replace this with a database query
    to retrieve the latest source records.
    """
    return pd.read_csv(
        CONFIG["source"]["records_path"]
    )


def load_species_dictionary():
    """
    Loads species lookup table used for
    synonym-safe species resolution.
    """
    return pd.read_csv(
        CONFIG["source"]["dictionary_path"]
    )


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