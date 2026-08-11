"""
Main execution pipeline orchestrator for the BRERC ETL process. 
Coordinates data cleaning, species resolution, spatial aggregation, database persistence, 
provenance tracking, and reconciliation into a single unified transactional run.
"""

# python -c "from etl.job import nightly_job; nightly_job()"
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
    Executes the complete end-to-end ETL pipeline sequence:
        1. Clean incoming source and dictionary dataframes.
        2. Resolve species numbers against the master dictionary.
        3. Build public spatial and taxonomic aggregation summaries.
        4. Persist species index and aggregation outputs to the database.
        5. Upsert pipeline execution provenance metadata.
        6. Run two-pass occurrence record reconciliation against the UI state.

    The load_mode ('initial' or 'incremental') is stamped onto every row written 
    during this execution via the 'Load' and 'Load_date' audit metadata columns.
    """

    start_time = time.time()
    logger.info(
        "Starting ETL pipeline execution with load_mode='%s' (%d source rows).",
        load_mode,
        len(source_df),
    )

    try:
        # Step 1: Clean raw column names and formats
        logger.info("Cleaning source and dictionary dataframes...")
        cleaned_source = clean_data(source_df)
        cleaned_dictionary = clean_data(dictionary_df)

        # Step 2: Match and resolve species identifiers (species_no)
        logger.info("Resolving species numbers...")
        resolved_source = resolve_species_numbers(
            cleaned_source,
            cleaned_dictionary,
        )

        # Step 3: Build derived public aggregation layers
        logger.info("Building public aggregation layer...")
        aggregation_outputs = build_public_aggregation(
            resolved_source,
            verified_column=VERIFIED_COLUMN,
            easting_column=EASTING_COLUMN,
            northing_column=NORTHING_COLUMN,
            date_column=DATE_COLUMN,
        )

        # Step 4: Persist species index and suppression counts.
        # This MUST happen before occurrence writes because occurrence tables
        # maintain foreign key constraints pointing to the species table.
        persist_aggregation_outputs(
            connection,
            species_index=aggregation_outputs["species_index"],
            suppressed_counts=aggregation_outputs["aggregation"],
            cell_size_m=CONFIG["aggregation"]["cell_size_m"],
            load_mode=load_mode,
        )

        # Step 5: Update pipeline run metadata provenance
        logger.info("Upserting pipeline provenance metadata...")
        upsert_provenance(connection, load_mode=load_mode)

        # Step 6: Synchronise and reconcile individual occurrence records
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
        logger.info("ETL pipeline completed successfully in %.2f seconds.", duration)

        return {
            "reconciliation": reconciliation_summary,
            "aggregation": aggregation_outputs,
        }

    except Exception as e:
        logger.exception("ETL pipeline failed during execution: %s", e)
        raise
