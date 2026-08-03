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

# Determines how many records are processed at once, keeps memory usage manageable
CHUNK_SIZE = CONFIG.get("reconciliation", {}).get("chunk_size", 100)

# Yields one chunk at a time
def _chunk_dataframe(df: pd.DataFrame, chunk_size: int):
    """
    Yields df in consecutive slices of chunk_size rows.
    Yields nothing if df is empty.
    """
    for start in range(0, len(df), chunk_size):
        yield df.iloc[start:start + chunk_size]


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


def _process_and_write_in_chunks(
    records_df: pd.DataFrame,
    dictionary_df: pd.DataFrame,
    connection,
    write_fn,
) -> None:
    """
    Splits records_df into CHUNK_SIZE-row pieces, runs each through
    make_safe_for_publishing, and writes each chunk immediately via
    write_fn (insert_records or update_records) - rather than building
    one giant safe dataframe for the whole dataset before writing
    anything.
    """
    for chunk in _chunk_dataframe(records_df, CHUNK_SIZE):
        safe_chunk = make_safe_for_publishing(
            chunk, dictionary_df, connection
        )
        write_fn(safe_chunk, connection)


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

    # Every insert and update goes through the safety pipeline, now
    # processed and written in chunks rather than all at once - keeps
    # peak memory down and lets Postgres start receiving data sooner.
    _process_and_write_in_chunks(
        records["inserts"], dictionary_df, connection, insert_records
    )
    _process_and_write_in_chunks(
        records["updates"], dictionary_df, connection, update_records
    )

    # Builds the species records
    # NOTE: species aggregation still needs to see the FULL inserts +
    # updates set at once (species totals/first_year/last_year would
    # be wrong if computed per-chunk) - this stays un-chunked for now.
    # Chunk-safe aggregation is a separate, bigger piece of work.
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

    # Deletes are ID-only (no safety gate needed) - no chunking benefit
    # here, this already sends one array to a single DELETE statement.
    delete_records(records["deletes"], connection)

    return changes