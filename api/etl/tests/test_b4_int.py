"""
B4 integration test.

Checks the whole B4 derived-data flow:

raw records
    ↓
accepted filtering
    ↓
species index generation
    ↓
species x cell x year aggregation
    ↓
D5 low-count suppression

This does not test:
- PostGIS location maths
- B3 reconciliation
- safety classification

Those have their own tests.
"""


import pandas as pd

from etl.aggregation.filtering import (
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


def test_b4_full_derived_pipeline():

    # --------------------------------------------------
    # 1. Raw source-like records
    # --------------------------------------------------

    records = pd.DataFrame(
        [
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

            # rejected record should disappear
            {
                "unique_no": 3,
                "species_no": 200,
                "scientific_name": "Sensitive species",
                "common_name": "Sensitive",
                "taxanb": "Mammals",
                "verified": "Rejected",
                "easting": 401000,
                "northing": 301000,
                "record_date": "03/01/2023",
            },
        ]
    )


    # --------------------------------------------------
    # 2. Verification filtering
    # --------------------------------------------------

    filtered = filter_accepted_records(
        records,
        verified_column="verified",
    )

    assert set(filtered["unique_no"]) == {
        1,
        2,
    }


    # --------------------------------------------------
    # 3. Species index
    # --------------------------------------------------

    species_index = build_species_index(
        filtered
    )

    assert len(species_index) == 1

    assert species_index.iloc[0]["species_id"] == 100

    assert species_index.iloc[0]["record_count"] == 2


    # --------------------------------------------------
    # 4. Aggregation
    # --------------------------------------------------

    aggregated = aggregate_counts(
        filtered,
        easting_column="easting",
        northing_column="northing",
        date_column="record_date",
        cell_size_m=1000,
    )


    assert aggregated["count"].sum() == 2


    # --------------------------------------------------
    # 5. D5 suppression
    # --------------------------------------------------

    suppressed = suppress_low_counts(
        aggregated,
        threshold=3,
    )


    assert len(suppressed) == 1

    assert suppressed.iloc[0]["suppressed"] == True

    assert pd.isna(
        suppressed.iloc[0]["count"]
    )