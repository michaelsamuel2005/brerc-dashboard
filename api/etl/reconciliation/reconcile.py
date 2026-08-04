import pandas as pd

# Imports functions to assist on finding out what records have changed
from etl.reconciliation.diff import (
    diff_id_hash_maps,
)
from etl.reconciliation.load import (
    upsert_species,
    insert_records,
    update_records,
    delete_records,
)

from etl.reconciliation.streaming import (
    iter_source_chunks,
    build_source_hash_map,
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

from etl.load.loader import load_safety_config

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

# How many rows to process per chunk through the safety gate + DB write.
# Keeps peak memory down at scale (millions of records) - the initial
# read + diff step still sees the whole dataset (that's Step B: chunked
# reading + two-pass diffing, not yet done), but the expensive part -
# safety-gate processing + writing - now happens in smaller batches.

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

    # Records without a resolved species_no cannot enter occurrence_public
    # because occurrence_public.species_id is a required foreign key
    # linked to the species table.
    #
    # These records have already gone through fail-closed logic, but they
    # cannot be represented in the public database without a species ID.

    unresolved_count = resolved["species_no"].isna().sum()

    if unresolved_count:
        print(
            f"{unresolved_count} records excluded from public load "
            "because species could not be resolved"
        )

    resolved = resolved.dropna(
        subset=["species_no"]
    )

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
    safe_df["content_hash"] = safe_df["unique_no"].map(
        hash_lookup
    )

    # Map internal ETL column names to occurrence_public schema names.
    # This creates species_id from species_no.
    safe_df = map_to_occurrence_public(safe_df)

    # Returned safe df to the reconciliation load functions
    return safe_df

def reconcile(
    dictionary_df: pd.DataFrame,
    ui_map: dict,
    connection,
) -> dict:

    # Pass 1

    # Streams through the source data to build the unique_no ->
    # content_hash lookup map.
    source_map = build_source_hash_map()

    # Comapres the UI with the new source data
    changes = diff_id_hash_maps(source_map, ui_map)

    insert_ids = changes["inserts"]
    update_ids = changes["updates"]
    delete_ids = changes["deletes"]

    # Stores records that contribute to the species table 
    species_records = []

    # Pass 2

    for cleaned_chunk in iter_source_chunks():

        hashed_chunk = cleaned_chunk.copy()

        # Attach content hashes calculated during pass 1
        hashed_chunk["content_hash"] = (
            hashed_chunk["unique_no"]
            .astype(str)
            .map(source_map)
        )

        # Find new records
        insert_chunk = hashed_chunk[
            hashed_chunk["unique_no"]
            .astype(str)
            .isin(insert_ids)
        ]

        # Find modified records
        update_chunk = hashed_chunk[
            hashed_chunk["unique_no"]
            .astype(str)
            .isin(update_ids)
        ]


        # Process inserts immediately
        if not insert_chunk.empty:

            species_records.append(insert_chunk)

            safe_insert = make_safe_for_publishing(
                insert_chunk,
                dictionary_df,
                connection,
            )

            if not safe_insert.empty:
                insert_records(
                    safe_insert,
                    connection,
                )


        # Process updates immediately
        if not update_chunk.empty:

            species_records.append(update_chunk)

            safe_update = make_safe_for_publishing(
                update_chunk,
                dictionary_df,
                connection,
            )

            if not safe_update.empty:
                update_records(
                    safe_update,
                    connection,
                )
    
    # Deletes are ID-only (no safety gate needed) - no chunking benefit
    # here, this already sends one array to a single DELETE statement.
    delete_records(delete_ids, connection)

    if species_records:

        species_records = pd.concat(
            species_records,
            ignore_index=True,
        )

        # Only accepted records contribute to species table
        filtered_species_records = filter_accepted_records(
            species_records,
            verified_column=VERIFIED_COLUMN,
        )

        # Add species_no + metadata
        resolved_species_records = resolve_species_numbers(
            filtered_species_records,
            dictionary_df,
        )

        # Build species summary
        species_index = build_species_index(
            resolved_species_records
        )

        # Insert/update species table
        upsert_species(
            species_index,
            connection,
        )

    return changes