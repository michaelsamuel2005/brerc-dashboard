"""
    Full B4 pipeline integration test.

    Tests the complete derived-data flow:

    raw records
        ↓
    verification filter
        ↓
    species index
        ↓
    species x cell x year aggregation
        ↓
    D5 low-count suppression

    This does not test individual functions
    (covered elsewhere). It checks that the pieces
    work correctly together.
"""

import pandas as pd

from etl.aggregation.cell_filtering import (
    filter_accepted_records,
    ACCEPTED_VERIFIED_VALUES,
)

from etl.aggregation.species_index import (
    build_species_index,
)

from etl.aggregation.counts import (
    aggregate_counts,
    suppress_low_counts,
)


ACCEPTED_VALUE = next(iter(ACCEPTED_VERIFIED_VALUES))


def make_full_dataset():

    return pd.DataFrame(
        [
            # species 100
            # two records in same cell/year
            {
                "unique_no": 1,
                "species_no": 100,
                "scientific_name": "Myotis daubentonii",
                "common_name": "Daubenton's bat",
                "taxanb": "Mammals",
                "verified": ACCEPTED_VALUE,
                "easting": 400000,
                "northing": 300000,
                "record_date": "01/01/2023",
            },

            {
                "unique_no": 2,
                "species_no": 100,
                "scientific_name": "Myotis daubentonii",
                "common_name": "Daubenton's bat",
                "taxanb": "Mammals",
                "verified": ACCEPTED_VALUE,
                "easting": 400100,
                "northing": 300100,
                "record_date": "02/01/2023",
            },


            # legacy record should survive
            {
                "unique_no": 3,
                "species_no": 300,
                "scientific_name": "Meles meles",
                "common_name": "European badger",
                "taxanb": "Mammals",
                "verified": "BRERC",
                "easting": 402000,
                "northing": 302000,
                "record_date": "05/01/2023",
            },


            # rejected must disappear
            {
                "unique_no": 4,
                "species_no": 999,
                "scientific_name": "Hidden species",
                "common_name": "Hidden",
                "taxanb": "Mammals",
                "verified": "Rejected",
                "easting": 405000,
                "northing": 305000,
                "record_date": "10/01/2023",
            },
        ]
    )


def test_full_b4_pipeline():

    raw = make_full_dataset()


    # -----------------------------
    # 1. Filter accepted records
    # -----------------------------

    filtered = filter_accepted_records(
        raw,
        verified_column="verified",
    )

    assert set(filtered["unique_no"]) == {
        1,
        2,
        3,
    }


    # -----------------------------
    # 2. Build species index
    # -----------------------------

    species_index = build_species_index(
        filtered
    )


    assert set(
        species_index["species_id"]
    ) == {
        100,
        300,
    }


    assert species_index[
        species_index["species_id"] == 100
    ]["record_count"].iloc[0] == 2



    # -----------------------------
    # 3. Aggregate counts
    # -----------------------------

    aggregated = aggregate_counts(
        filtered,
        easting_column="easting",
        northing_column="northing",
        date_column="record_date",
        cell_size_m=1000,
    )


    # all filtered records accounted for
    assert aggregated["count"].sum() == 3



    # -----------------------------
    # 4. Apply D5 suppression
    # -----------------------------

    suppressed = suppress_low_counts(
        aggregated,
        threshold=2,
    )


    # species 300 only has 1 record
    # so it should disappear from exact counts

    badger_row = suppressed[
        suppressed["species_no"] == 300
    ].iloc[0]


    assert badger_row["suppressed"] == True
    assert pd.isna(
        badger_row["count"]
    )


    # bat has 2 records, equal to threshold
    # current policy = show it

    bat_row = suppressed[
        suppressed["species_no"] == 100
    ].iloc[0]


    assert bat_row["suppressed"] == False
    assert bat_row["count"] == 2



def test_b4_pipeline_is_repeatable():

    raw = make_full_dataset()

    def run_pipeline():

        filtered = filter_accepted_records(
            raw,
            verified_column="verified",
        )

        aggregated = aggregate_counts(
            filtered,
            easting_column="easting",
            northing_column="northing",
            date_column="record_date",
            cell_size_m=1000,
        )

        return suppress_low_counts(
            aggregated,
            threshold=2,
        ).sort_values(
            [
                "species_no",
                "grid_cell",
                "year",
            ]
        ).reset_index(drop=True)


    first = run_pipeline()
    second = run_pipeline()


    pd.testing.assert_frame_equal(
        first,
        second,
    )