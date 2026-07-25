import pandas as pd

from etl.reconciliation.hashing import (
    add_content_hash,
)

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


def reconcile(
    source_df: pd.DataFrame,
    ui_map: dict,
    connection,
) -> dict:

    # 1. Calculate hashes from the raw source data
    source_df = add_content_hash(source_df)

    # 2. Build:
    #    unique_no -> content_hash
    source_map = build_id_hash_map(source_df)

    # 3. Compare current source against existing UI records
    changes = diff_id_hash_maps(
        source_map,
        ui_map,
    )

    # 4. Select the actual rows needed for INSERT/UPDATE
    records = get_reconciliation_records(
        source_df,
        changes,
    )

    # 5. Apply database changes
    insert_records(
        records["inserts"],
        connection,
    )

    update_records(
        records["updates"],
        connection,
    )

    delete_records(
        records["deletes"],
        connection,
    )

    return changes