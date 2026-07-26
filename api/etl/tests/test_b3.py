import pandas as pd

from etl.reconciliation.hashing import (
    add_content_hash,
)

from etl.reconciliation.diff import (
    build_id_hash_map,
    diff_id_hash_maps,
    get_reconciliation_records,
)

def run_reconciliation(source_df, ui_df):
    """
    Simulates one reconciliation run.

    Returns:
        updated UI state
        detected changes
    """

    # Hash the current source records
    source_df = add_content_hash(source_df)

    # Build ID -> hash maps
    source_map = build_id_hash_map(source_df)
    ui_map = build_id_hash_map(ui_df)

    # Detect changes
    changes = diff_id_hash_maps(
        source_map,
        ui_map,
    )

    # Get actual rows to insert/update
    records = get_reconciliation_records(
        source_df,
        changes,
    )

    # Simulate database operations
    new_ui_df = ui_df.copy()

    # INSERT new records
    new_ui_df = pd.concat(
        [
            new_ui_df,
            records["inserts"],
        ],
        ignore_index=True,
    )

    # UPDATE changed records
    updates = records["updates"]

    for _, row in updates.iterrows():
        unique_no = row["unique_no"]

        new_ui_df = new_ui_df[
            new_ui_df["unique_no"] != unique_no
        ]

        new_ui_df = pd.concat(
            [
                new_ui_df,
                pd.DataFrame([row]),
            ],
            ignore_index=True,
        )

    # DELETE retracted records
    new_ui_df = new_ui_df[
        ~new_ui_df["unique_no"].isin(
            records["deletes"]
        )
    ]

    return (
        new_ui_df.reset_index(drop=True),
        changes,
    )

def test_b3_reconciliation_lifecycle():

    # --------------------------------------------------
    # 1. Initial full load
    # --------------------------------------------------

    source_df = pd.DataFrame({
        "unique_no": ["A", "B", "C"],
        "scientific_name": [
            "Species A",
            "Species B",
            "Species C",
        ],
    })

    ui_df = pd.DataFrame(
        columns=[
            "unique_no",
            "scientific_name",
            "content_hash",
        ]
    )

    ui_df, changes = run_reconciliation(
        source_df,
        ui_df,
    )

    assert changes["inserts"] == {"A", "B", "C"}
    assert changes["updates"] == set()
    assert changes["deletes"] == set()

    assert set(ui_df["unique_no"]) == {
        "A",
        "B",
        "C",
    }

    # --------------------------------------------------
    # 2. Edit record A
    # --------------------------------------------------

    edited_source_df = pd.DataFrame({
        "unique_no": ["A", "B", "C"],
        "scientific_name": [
            "Species A edited",
            "Species B",
            "Species C",
        ],
    })

    ui_df, changes = run_reconciliation(
        edited_source_df,
        ui_df,
    )

    assert changes["updates"] == {"A"}
    assert changes["inserts"] == set()
    assert changes["deletes"] == set()

    updated_record = ui_df[
        ui_df["unique_no"] == "A"
    ].iloc[0]

    assert (
        updated_record["scientific_name"]
        == "Species A edited"
    )

    # --------------------------------------------------
    # 3. Retract record B
    # --------------------------------------------------

    retracted_source_df = pd.DataFrame({
        "unique_no": ["A", "C"],
        "scientific_name": [
            "Species A edited",
            "Species C",
        ],
    })

    ui_df, changes = run_reconciliation(
        retracted_source_df,
        ui_df,
    )

    assert changes["deletes"] == {"B"}

    assert set(ui_df["unique_no"]) == {
        "A",
        "C",
    }

    # --------------------------------------------------
    # 4. Run again without changes
    # --------------------------------------------------

    ui_before_rerun = ui_df.copy()

    ui_df, changes = run_reconciliation(
        retracted_source_df,
        ui_df,
    )

    assert changes["inserts"] == set()
    assert changes["updates"] == set()
    assert changes["deletes"] == set()

    assert changes["unchanged"] == {
        "A",
        "C",
    }

    pd.testing.assert_frame_equal(
        ui_df.sort_values("unique_no").reset_index(drop=True),
        ui_before_rerun.sort_values("unique_no").reset_index(drop=True),
    )