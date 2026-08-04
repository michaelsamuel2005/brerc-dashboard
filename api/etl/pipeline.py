from etl.profiling.cleaning import clean_data
from etl.reconciliation.reconcile import reconcile
from etl.aggregation.counts import build_public_aggregation
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
        2. Reconcile changes into the public database
        3. Rebuild the public aggregation layer.

    Returns: 
        Reconciliation summary and rebuilt aggregation outputs
    """

    # Clean incoming tables: Cleans column names
    cleaned_source = clean_data(source_df)
    cleaned_dictionary = clean_data(dictionary_df)

    resolved_source = resolve_species_numbers(cleaned_source, cleaned_dictionary)

    # Update the occurence_public
    reconciliation_summary = reconcile(
        resolved_source,
        ui_map,
        connection,
    )

    # Rebuilt the derived aggreation layer (SHOULD MAYBE USE LOADED RECORDS)
    aggregation_outputs = build_public_aggregation(
        resolved_source,      # not cleaned_source
        verified_column=VERIFIED_COLUMN,
        easting_column=EASTING_COLUMN,
        northing_column=NORTHING_COLUMN,
        date_column=DATE_COLUMN,
    )

    return {
        "reconciliation": reconciliation_summary,
        "aggregation": aggregation_outputs,
    }