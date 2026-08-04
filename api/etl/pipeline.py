from etl.profiling.cleaning import clean_data
from etl.reconciliation.reconcile import reconcile
from etl.aggregation.counts import build_public_aggregation
from etl.aggregation.persist import persist_aggregation_outputs
from etl.matching.species import resolve_species_numbers

from etl.load.loader import load_safety_config

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
):
    """
    Runs the complete ETL pipeline.

    Steps:
        1. Clean the source data
        2. Resolve species numbers
        3. Reconcile occurrence records
        4. Rebuild public aggregation layer
        5. Persist derived tables
    """

    # Clean incoming tables: Cleans column names
    cleaned_source = clean_data(source_df)
    cleaned_dictionary = clean_data(dictionary_df)

    # Add species_no using the dictionary lookup
    resolved_source = resolve_species_numbers(
        cleaned_source,
        cleaned_dictionary,
    )

    # Update occurrence_public
    reconciliation_summary = reconcile(
        resolved_source,
        ui_map,
        connection,
    )

    # Rebuild derived aggregation layer
    aggregation_outputs = build_public_aggregation(
        resolved_source,
        verified_column=VERIFIED_COLUMN,
        easting_column=EASTING_COLUMN,
        northing_column=NORTHING_COLUMN,
        date_column=DATE_COLUMN,
    )

    # Store species + distribution_cell tables
    persist_aggregation_outputs(
        connection,
        species_index=aggregation_outputs["species_index"],
        suppressed_counts=aggregation_outputs["aggregation"],
        cell_size_m=CONFIG["aggregation"]["cell_size_m"],
        load_number=1,
    )

    return {
        "reconciliation": reconciliation_summary,
        "aggregation": aggregation_outputs,
    }