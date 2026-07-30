import pandas as pd

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

from etl.safety_gate.classification import classify_chunk
from etl.matching.species import resolve_species_numbers
from etl.safety_gate.generalisation import generalise_locations
from etl.safety_gate.public_output import add_coarse_locality, prepare_public_output


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

    # D5: verified-only + legacy-flagged-not-dropped, BEFORE anything
    # else runs. A record failing both accepted and legacy checks
    # must never reach classification, generalisation, or the DB.
    filtered = filter_accepted_records(df, verified_column=VERIFIED_COLUMN)

    resolved = resolve_species_numbers(filtered, dictionary_df)
    classified = classify_chunk(resolved)
    generalised = generalise_locations(
        classified,
        connection,
        easting_column=easting_column,
        northing_column=northing_column,
        resolution_column=resolution_column,
    )
    with_locality = add_coarse_locality(
        generalised,
        easting_column="snapped_easting",
        northing_column="snapped_northing",
    )

    safe_df = prepare_public_output(with_locality)

    hash_lookup = with_locality.set_index("unique_no")["content_hash"]
    safe_df["content_hash"] = safe_df["unique_no"].map(hash_lookup)

    return map_to_occurrence_public(safe_df)


def reconcile(
    source_df: pd.DataFrame,
    dictionary_df: pd.DataFrame,
    ui_map: dict,
    connection,
) -> dict:

    # 1. Calculate hashes from the raw source data (post-cleaning -
    #    make sure source_df has already been through clean_data()
    #    before it reaches here).
    source_df = add_content_hash(source_df)

    # 2. Build: unique_no -> content_hash
    source_map = build_id_hash_map(source_df)

    # 3. Compare current source against existing UI records
    changes = diff_id_hash_maps(source_map, ui_map)

    # 4. Select the actual raw rows needed for INSERT/UPDATE
    records = get_reconciliation_records(source_df, changes)

    # 5. Run the safety pipeline BEFORE anything reaches the UI
    #    database - inserts and updates must never see raw data.
    safe_inserts = make_safe_for_publishing(
        records["inserts"], dictionary_df, connection
    )
    safe_updates = make_safe_for_publishing(
        records["updates"], dictionary_df, connection
    )

    # 6. Apply database changes - only ever safe_* data past this point.

    # Build species rows from the records that are actually being loaded.
    species_records = pd.concat(
        [
            records["inserts"],
            records["updates"],
        ],
        ignore_index=True,
    )

    if not species_records.empty:
        filtered_species_records = filter_accepted_records(
            species_records,
            verified_column=VERIFIED_COLUMN,
        )

        resolved_species_records = resolve_species_numbers(
            filtered_species_records,
            dictionary_df,
        )

        species_index = build_species_index(
            resolved_species_records
        )

        upsert_species(
            species_index,
            connection,
        )

    insert_records(safe_inserts, connection)
    update_records(safe_updates, connection)
    delete_records(records["deletes"], connection)

    return changes