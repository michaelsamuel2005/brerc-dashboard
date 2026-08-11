from datetime import datetime
import logging
import time

from etl.profiling.cleaning import clean_data
from etl.reconciliation.reconcile import reconcile
from etl.aggregation.counts import build_public_aggregation
from etl.aggregation.persist import persist_aggregation_outputs
from etl.matching.species import resolve_species_numbers
from etl.provenance import upsert_provenance
from etl.load.loader import load_safety_config

logger = logging.getLogger(__name__)

CONFIG = load_safety_config()

VERIFIED_COLUMN = CONFIG["columns"]["verified"]
EASTING_COLUMN = CONFIG["columns"]["eastings"]
NORTHING_COLUMN = CONFIG["columns"]["northings"]
DATE_COLUMN = CONFIG["columns"]["record_date"]


def run_pipeline(
    source_df,
    dictionary_df,
    ui_map,
    connection,
    load_mode,
): 
    """
    Runs the complete ETL pipeline.

    Steps:
        1. Clean the source data
        2. Resolve species numbers
        3. Rebuild species and aggregation layer
        4. Reconcile occurrence records
        5. Persist derived tables

    load_mode is "initial" or "incremental", decided by the caller
    (nightly_job) based on watermark state, and is stamped onto every
    row written this run via the "Load" / "Load_date" audit columns.
    """

    start_time = time.time()
    logger.info(
        "Starting ETL pipeline execution with load_mode='%s' (%d source rows).",
        load_mode,
        len(source_df),
    )

    try:
        # Clean incoming tables: Cleans column names
        logger.info("Cleaning source and dictionary dataframes...")
        cleaned_source = clean_data(source_df)
        cleaned_dictionary = clean_data(dictionary_df)

        # Add species_no using the dictionary lookup
        logger.info("Resolving species numbers...")
        resolved_source = resolve_species_numbers(
            cleaned_source,
            cleaned_dictionary,
        )

        # Rebuild derived aggregation layer
        logger.info("Building public aggregation layer...")
        aggregation_outputs = build_public_aggregation(
            resolved_source,
            verified_column=VERIFIED_COLUMN,
            easting_column=EASTING_COLUMN,
            northing_column=NORTHING_COLUMN,
            date_column=DATE_COLUMN,
        )

        # Store species + distribution_cell tables
        # This must happen before occurrence_public because
        # occurrence_public has a foreign key to species.
        logger.info(
            "Persisting aggregation outputs and species index to database..."
        )
        persist_aggregation_outputs(
            connection,
            species_index=aggregation_outputs["species_index"],
            suppressed_counts=aggregation_outputs["aggregation"],
            cell_size_m=CONFIG["aggregation"]["cell_size_m"],
            load_mode=load_mode,
        )

        logger.info("Upserting pipeline provenance metadata...")
        upsert_provenance(connection, load_mode=load_mode)

        # Update occurrence_public
        logger.info("Running occurrence record reconciliation...")
        reconciliation_summary = reconcile(
            resolved_source,
            cleaned_dictionary,
            ui_map,
            connection,
            load_mode=load_mode,
            load_timestamp=datetime.now(),
        )

        duration = time.time() - start_time
        logger.info(
            "ETL pipeline completed successfully in %.2f seconds.", duration
        )

        return {
            "reconciliation": reconciliation_summary,
            "aggregation": aggregation_outputs,
        }

    except Exception as e:
        logger.exception("ETL pipeline failed during execution: %s", e)
        raise

# python -c "from etl.job import nightly_job; nightly_job()"
