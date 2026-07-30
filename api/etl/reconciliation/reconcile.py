import pandas as pd

# Imports functions to assist on finding out what records have changed
from etl.reconciliation.hashing import add_content_hash
from etl.reconciliation.diff import (
    build_id_hash_map,
    diff_id_hash_maps,
    get_reconciliation_records,
)
from etl.reconciliation.load import (
    upsert_species,
    insert_records,
    update_records,
    delete_records,
)

# Imports functions which makes the records safe to view in public dashboard
from etl.safety_gate.classification import classify_chunk
from etl.matching.species import resolve_species_numbers
from etl.safety_gate.generalisation import generalise_locations
from etl.safety_gate.public_output import add_coarse_locality, prepare_public_output

# Imports functions to help build the species table
from etl.aggregation.cell_filtering import filter_accepted_records
from etl.reconciliation.map_to_schema import map_to_occurrence_public

from etl.aggregation.species_index import build_species_index

from etl.config.loader import load_safety_config

CONFIG = load_safety_config()

VERIFIED_COLUMN = (
    CONFIG["columns"]["verified"]
)

EASTING_COLUMN = (
    CONFIG["columns"]["eastings"]
)
NORTHING_COLUMN = (
    CONFIG["columns"]["northings"]
)

def make_safe_for_publishing(
    df: pd.DataFrame,
    dictionary_df: pd.DataFrame,
    connection,
    easting_column: str = EASTING_COLUMN,
    northing_column: str = NORTHING_COLUMN,
    resolution_column: str = "resolution_m",
) -> pd.DataFrame:
    
    """
    Runs raw source rows through the full safety pipeline, then maps
    the result onto occurrence_public's real column names. This is
    the only path inserts/updates should ever take.
    """

    if df.empty:
        return pd.DataFrame(columns=[
            "record_id", "species_id", "record_year", "grid_ref",
            "locality", "precision_metres", "verified", "content_hash",
        ])

    # D5: Removes records that aren't verified + legacy-flagged 
    # RECORDS must be dropped prior to classification + generalisation
    filtered = filter_accepted_records(df, verified_column=VERIFIED_COLUMN)

    # Adds species_no to their name
    resolved = resolve_species_numbers(filtered, dictionary_df)
    # Classifying if the species are sensitive or not + blur distance
    classified = classify_chunk(resolved)
    # Blur the location of the species
    generalised = generalise_locations(
        classified,
        connection,
        easting_column=easting_column,
        northing_column=northing_column,
        resolution_column=resolution_column,
    )
    # Create a locality string with the blurred coordinates
    with_locality = add_coarse_locality(
        generalised,
        easting_column="snapped_easting",
        northing_column="snapped_northing",
    )

    # Removes all columns public shouldn't see (sensitive columns)
    safe_df = prepare_public_output(with_locality)

    # Sets unique_no as the index, selects content_hash column (uses with_locality DF)
    hash_lookup = with_locality.set_index("unique_no")["content_hash"]
    # For every value look up its hash_lookup, stored as content_hash
    safe_df["content_hash"] = safe_df["unique_no"].map(hash_lookup)

    # Returned safe df to the map function
    return map_to_occurrence_public(safe_df)


def reconcile(
    source_df: pd.DataFrame,
    dictionary_df: pd.DataFrame,
    ui_map: dict,
    connection,
) -> dict:

    # Hashes every record
    source_df = add_content_hash(source_df)

    # Builds the lookup table, converts DF into dictionary
    source_map = build_id_hash_map(source_df)

    # Comapres the UI with the new source data
    changes = diff_id_hash_maps(source_map, ui_map)

    # Get the full rows of the reconciliation columns
    records = get_reconciliation_records(source_df, changes)

    # Every insert and update goes through the safety pipeline
    safe_inserts = make_safe_for_publishing(
        records["inserts"], dictionary_df, connection
    )
    safe_updates = make_safe_for_publishing(
        records["updates"], dictionary_df, connection
    )

    # Builds the species records
    species_records = pd.concat(
        [
            records["inserts"],
            records["updates"],
        ],
        ignore_index=True,
    )

    # If there were records
    if not species_records.empty:
        # Filter the records to only allow records for public view
        filtered_species_records = filter_accepted_records(
            species_records,
            verified_column=VERIFIED_COLUMN,
        )

        # Convert scientific names to the species name
        resolved_species_records = resolve_species_numbers(
            filtered_species_records,
            dictionary_df,
        )

        # Build the species index, one row per species
        species_index = build_species_index(
            resolved_species_records
        )

        # Updates/Inserts species onto species table
        upsert_species(
            species_index,
            connection,
        )

    # Now insert, update or delete records from the source data
    insert_records(safe_inserts, connection)
    update_records(safe_updates, connection)
    delete_records(records["deletes"], connection)

    return changes