"""
Main entry point and orchestrator for the BRERC ETL pipeline. 
Manages logging configuration, config caching, source/dictionary data ingestion 
(supporting both CSV and database modes), incremental vs initial load decisions, 
and nightly batch job execution.
"""

from functools import lru_cache
import logging

# Imports database connections and pipeline components
from etl.db import (
    check_table_exists,
    check_table_has_rows,
    get_destination_connection,
    get_source_connection,
)
from etl.load.loader import load_safety_config
from etl.load.metadata import get_last_load_date
from etl.load.mode import should_run_initial_load
from etl.load.reload import force_full_reload
from etl.pipeline import run_pipeline
from etl.reconciliation.state import get_ui_map

import pandas as pd

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Cached wrapper to load safety and pipeline configurations."""
    return load_safety_config()


def load_source_data(source_connection=None, watermark_date=None):
    """
    Loads BRERC source occurrence records from either CSV files or a database source.
    Bridges the raw source column ('modified_date') to the required target column ('date_mdb_modified').
    """
    config = get_config()
    mode = config["source"].get("mode", "csv")
    
    # safety.yaml defines: modified_date: date_mdb_modified
    # Source key = 'modified_date', Target value = 'date_mdb_modified'
    columns_config = config.get("columns", {})
    source_modified_col = "modified_date"
    target_modified_col = columns_config.get("modified_date", "date_mdb_modified")

    if mode == "csv":
        df = pd.read_csv(config["source"]["records_path"])

        # Determine which column name is present in the raw CSV
        active_col = source_modified_col if source_modified_col in df.columns else target_modified_col

        if watermark_date is not None:
            df[active_col] = pd.to_datetime(df[active_col])
            df = df[df[active_col] >= watermark_date]

    elif mode == "database":
        if source_connection is None:
            raise ValueError(
                "source_connection is required when source.mode is 'database'"
            )

        query = config["source"]["records_query"]

        if watermark_date is not None:
            query = (
                f"SELECT * FROM ({query}) AS filtered_source "
                f"WHERE {source_modified_col} >= %(watermark_date)s"
            )

            df = pd.read_sql(
                query,
                source_connection,
                params={"watermark_date": watermark_date},
            )
        else:
            df = pd.read_sql(
                query,
                source_connection,
            )
        
        active_col = source_modified_col if source_modified_col in df.columns else target_modified_col

    else:
        raise ValueError(f"Unknown source.mode: {mode!r}")

    # Ensure the mandatory pipeline/database target column ('date_mdb_modified') exists
    if target_modified_col not in df.columns:
        if active_col in df.columns:
            df[target_modified_col] = df[active_col]
        else:
            raise KeyError(
                f"Source data is missing the required modification column (checked '{source_modified_col}' and '{target_modified_col}')."
            )

    return df


def load_species_dictionary(source_connection=None):
    """Loads the master species dictionary used for synonym-safe species resolution from CSV or database."""
    config = get_config()
    mode = config["source"].get("mode", "csv")

    if mode == "csv":
        return pd.read_csv(config["source"]["dictionary_path"])

    if mode == "database":
        if source_connection is None:
            raise ValueError(
                "source_connection is required when source.mode is 'database'"
            )

        return pd.read_sql(
            config["source"]["dictionary_query"],
            source_connection,
        )

    raise ValueError(f"Unknown source.mode: {mode!r}")


def get_current_ui_map(connection):
    """Retrieves the current occurrence_public state."""
    return get_ui_map(connection)


def nightly_job():
    """Orchestrates the nightly ETL pipeline run."""
    logger.info("Starting nightly ETL job pipeline.")

    try:
        config = get_config()
        mode = config["source"].get("mode", "csv")

        with get_destination_connection() as connection:
            table_name = config["destination"]["table"]

            table_exists = check_table_exists(connection, table_name)
            table_has_rows = (
                check_table_has_rows(connection, table_name)
                if table_exists
                else False
            )

            run_initial = should_run_initial_load(table_exists, table_has_rows)
            load_mode = "initial" if run_initial else "incremental"
            watermark_date = None

            if (
                load_mode == "incremental"
                and mode == "database"
                and config["load"].get("incremental_check", True)
            ):
                watermark_date = get_last_load_date(connection)
                if watermark_date is None:
                    load_mode = "initial"
            elif load_mode == "incremental" and mode == "database":
                load_mode = "initial"

            if load_mode == "initial":
                connection.commit()
                logger.warning("Forcing full reload of table: %s", table_name)
                force_full_reload()

            if mode == "database":
                with get_source_connection() as source_connection:
                    source_df = load_source_data(
                        source_connection, watermark_date=watermark_date
                    )
                    dictionary_df = load_species_dictionary(source_connection)
            else:
                source_df = load_source_data(watermark_date=None)
                dictionary_df = load_species_dictionary()

            ui_map = get_current_ui_map(connection)

            logger.info("Running pipeline in '%s' mode.", load_mode)

            result = run_pipeline(
                source_df,
                dictionary_df,
                ui_map,
                connection,
                load_mode,
            )

        reconciliation_summary = result.get("reconciliation", {})
        logger.info(
            "Nightly ETL completed successfully. Summary -> Inserts: %d | Updates: %d | Deletes: %d | Unchanged: %d",
            len(reconciliation_summary.get("inserts", [])),
            len(reconciliation_summary.get("updates", [])),
            len(reconciliation_summary.get("deletes", [])),
            len(reconciliation_summary.get("unchanged", [])),
        )

        return result

    except Exception as error:
        logger.exception("Nightly ETL failed: %s", error)
        raise