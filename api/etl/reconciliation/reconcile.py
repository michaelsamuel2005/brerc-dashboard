"""
Core reconciliation orchestration module. 
Executes a two-pass reconciliation process: compares source and UI database hashes 
to isolate inserts, updates, and deletes, processes data through safety and publishing gates, 
and synchronises the database.
"""
import logging
import pandas as pd

# Imports functions to assist on finding out what records have changed
from etl.reconciliation.diff import diff_id_hash_maps
from etl.reconciliation.load import (
    delete_records,
    insert_records,
    update_records,
)
from etl.reconciliation.streaming import (
    build_source_hash_map,
    iter_source_chunks,
)

# Imports functions which makes the records safe to view in public dashboard
from etl.aggregation.cell_filtering import filter_accepted_records
from etl.load.loader import load_safety_config

# ETL load metadata ("Load" / "Load_date")
from etl.load.metadata import add_load_metadata
from etl.matching.species import resolve_species_numbers
from etl.reconciliation.map_to_schema import map_to_occurrence_public
from etl.safety_gate.classification import classify_chunk
from etl.safety_gate.generalisation import generalise_locations
from etl.safety_gate.public_output import (
    add_coarse_locality,
    prepare_public_output,
)

logger = logging.getLogger(__name__)

CONFIG = load_safety_config()

VERIFIED_COLUMN = CONFIG["columns"]["verified"]
EASTING_COLUMN = CONFIG["columns"]["eastings"]
NORTHING_COLUMN = CONFIG["columns"]["northings"]


def make_safe_for_publishing(
    df: pd.DataFrame,
    dictionary_df: pd.DataFrame,
    connection,
    easting_column: str = EASTING_COLUMN,
    northing_column: str = NORTHING_COLUMN,
    resolution_column: str = "resolution_m",
) -> pd.DataFrame:
    """
    Runs raw source records through the full safety pipeline (verification filtering, 
    species resolution, sensitivity classification, location generalisation, and masking), 
    then maps the result onto the public database schema.
    """

    if df.empty:
        return pd.DataFrame(
            columns=[
                "record_id",
                "species_id",
                "record_year",
                "grid_ref",
                "locality",
                "precision_metres",
                "verified",
                "content_hash",
            ]
        )

    # Drop unverified or rejected records prior to classification and generalisation
    filtered = filter_accepted_records(df, verified_column=VERIFIED_COLUMN)

    # Adds species_no to their name
    resolved = resolve_species_numbers(filtered, dictionary_df)

    # Filter out records with unresolved species because species_id is a mandatory foreign key
    unresolved_count = resolved["species_no"].isna().sum()
    if unresolved_count:
        logger.warning(
            "%d records excluded from public load because species could not be resolved.",
            unresolved_count,
        )

    resolved = resolved.dropna(subset=["species_no"])

    # Classify sensitivity and determine blur thresholds
    classified = classify_chunk(resolved)

    # Blur the location of the species
    generalised = generalise_locations(
        classified,
        connection,
        easting_column=easting_column,
        northing_column=northing_column,
        resolution_column=resolution_column,
    )

    # Build coarse locality strings using the snapped/blurred coordinates
    with_locality = add_coarse_locality(
        generalised,
        easting_column="snapped_easting",
        northing_column="snapped_northing",
    )

    # Remove sensitive internal columns that shouldn't face the public dashboard
    safe_df = prepare_public_output(with_locality)

    # Reattach content hashes mapped from unique record IDs
    hash_lookup = with_locality.set_index("unique_no")["content_hash"]

    # For every value look up its hash_lookup, stored as content_hash
    safe_df["content_hash"] = safe_df["unique_no"].map(hash_lookup)

    # Map processed internal columns to the exact column names of 'occurrence_public'
    safe_df = map_to_occurrence_public(safe_df)

    # Returned safe df to the reconciliation load functions
    return safe_df


def reconcile(
    records_df: pd.DataFrame,
    dictionary_df: pd.DataFrame,
    ui_map: dict,
    connection,
    load_mode: str,
    load_timestamp,
) -> dict:
    """
    Executes the two-pass reconciliation pipeline:
        - Pass 1: Builds source hash maps and diffs against the UI state to find inserts, updates, and deletes.
        - Pass 2: Streams chunks, filters for modified/new rows, pushes them through the safety pipeline, 
        stamps metadata, and performs inserts, updates, and database purges.
    """

    # Pass 1: Hash mapping and set differential analysis

    source_map = build_source_hash_map(records_df)

    # Compares the UI with the new source data
    changes = diff_id_hash_maps(source_map, ui_map)

    logger.info(
        "Reconciliation Breakdown — Inserts: %d | Updates: %d | Deletes: %d | Unchanged: %d",
        len(changes["inserts"]),
        len(changes["updates"]),
        len(changes["deletes"]),
        len(changes["unchanged"]),
    )

    insert_ids = changes["inserts"]
    update_ids = changes["updates"]
    delete_ids = changes["deletes"]

    # Pass 2: Chunked streaming, safety pipeline execution, and persistence
    chunk_count = 0
    for cleaned_chunk in iter_source_chunks(records_df):
        chunk_count += 1
        hashed_chunk = cleaned_chunk.copy()

        # Attach content hashes calculated during pass 1
        hashed_chunk["content_hash"] = (
            hashed_chunk["unique_no"].astype(str).map(source_map)
        )

        # Find new records
        insert_chunk = hashed_chunk[
            hashed_chunk["unique_no"].astype(str).isin(insert_ids)
        ]

        # Find modified records
        update_chunk = hashed_chunk[
            hashed_chunk["unique_no"].astype(str).isin(update_ids)
        ]

        # Process and persist new records
        if not insert_chunk.empty:
            safe_insert = make_safe_for_publishing(
                insert_chunk,
                dictionary_df,
                connection,
            )

            if not safe_insert.empty:
                safe_insert = add_load_metadata(
                    safe_insert,
                    load_mode,
                    load_timestamp,
                )
                insert_records(
                    safe_insert,
                    connection,
                )

        # Process and persist updated records
        if not update_chunk.empty:
            safe_update = make_safe_for_publishing(
                update_chunk,
                dictionary_df,
                connection,
            )

            if not safe_update.empty:
                safe_update = add_load_metadata(
                    safe_update,
                    load_mode,
                    load_timestamp,
                )
                update_records(
                    safe_update,
                    connection,
                )

    # Purge deleted records from the UI database (deletions require ID checks only)
    if delete_ids:
        logger.warning(
            "Executing database purge for %d deleted records.",
            len(delete_ids),
        )

    delete_records(delete_ids, connection)
    logger.info("Reconciliation pass completed successfully.")

    return changes
