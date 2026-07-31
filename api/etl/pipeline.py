from etl.profiling.cleaning import clean_data
from etl.reconciliation.reconcile import reconcile
from etl.aggregation.aggregation import build_public_aggregation

from etl.config.loader import load_safety_config

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

    # Update the occurence_public
    reconciliation_summary = reconcile(
        cleaned_source,
        dictionary_df,
        ui_map,
        connection,
    )

    # Rebuilt the derived aggreation layer 
    aggregation_outputs = build_public_aggregation(
        cleaned_source,
        # change to the ymal
        verified_column=VERIFIED_COLUMN,
        easting_column=EASTING_COLUMN,
        northing_column=NORTHING_COLUMN,
        date_column=DATE_COLUMN,
    )

    return {
        "reconciliation": reconciliation_summary,
        "aggregation": aggregation_outputs,
    }