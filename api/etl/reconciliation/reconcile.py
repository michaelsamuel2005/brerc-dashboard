import pandas as pd

from etl.reconciliation.hashing import add_content_hash
from etl.reconciliation.diff import (
    build_id_hash_map,
    diff_id_hash_maps,
    get_reconciliation_records,
)
from etl.reconciliation.load import (
    insert_records,
    update_records,
    delete_records,
)

# Adjust these three imports to your real module paths -
# same as classify.py/species.py/generalisation.py/public_output.py
# used elsewhere in the pipeline.
from etl.safety_gate.classify import classify_chunk
from etl.matching.species import resolve_species_numbers
from etl.safety_gate.generalisation import generalise_locations
from etl.safety_gate.public_output import add_coarse_locality, prepare_public_output

def make_safe_for_publishing(
    df: pd.DataFrame,
    dictionary_df: pd.DataFrame,
    connection,
    easting_column: str = "eastings",
    northing_column: str = "northings",
    resolution_column: str = "effective_resolution_m",
) -> pd.DataFrame:
    """
    Runs raw source rows through the full safety pipeline before they
    are allowed anywhere near the UI database. This is the only path
    inserts/updates should ever take - insert_records/update_records
    must never receive anything that hasn't been through this.
    """
    if df.empty:
        # Preserve content_hash even on an empty frame, so downstream
        # concat/merge doesn't break on a missing column.
        return df.assign(**{col: pd.Series(dtype="object") for col in
                             ("longitude", "latitude", "coarse_locality")})

    resolved = resolve_species_numbers(df, dictionary_df)
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

    # content_hash isn't a PUBLIC_COLUMN (it's not public-facing) but
    # the UI table still needs to store it, so next run can diff
    # against it. Re-attach it by unique_no after prepare_public_output
    # has stripped everything else down.
    hash_lookup = with_locality.set_index("unique_no")["content_hash"]
    safe_df["content_hash"] = safe_df["unique_no"].map(hash_lookup)

    return safe_df


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
    insert_records(safe_inserts, connection)
    update_records(safe_updates, connection)
    delete_records(records["deletes"], connection)

    return changes