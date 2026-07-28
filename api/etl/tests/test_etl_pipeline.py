"""
Full ETL integration test.

Checks:
- Raw records flow through the pipeline.
- Rejected records disappear.
- Species resolution works.
- Species index only contains public species.
- Aggregates reconcile.
- Suppression hides small counts.
- No forbidden fields leak into derived outputs.
"""

import pandas as pd

from etl.aggregation.cell_filtering import filter_accepted_records
from etl.aggregation.species_index import build_species_index
from etl.aggregation.counts import (
    aggregate_counts,
    suppress_low_counts,
)

from etl.safety_gate.classify import classify_chunk
from etl.matching.species import resolve_species_numbers
from etl.safety_gate.public_output import PUBLIC_COLUMNS


ACCEPTED_VALUE = "Accepted"


def test_full_etl_pipeline():

    # -----------------------------------------
    # 1. Raw source-like input
    # -----------------------------------------

    raw = pd.DataFrame(
        [
            {
                "unique_no": 1,
                "scientific_name": "Meles meles",
                "species_no": 300,
                "common_name": "Badger",
                "taxanb": "Mammals",
                "verified": ACCEPTED_VALUE,
                "record_type": "Observation",
                "easting": 400000,
                "northing": 300000,
                "record_date": "01/01/2023",
                "place": "Sensitive location",
                "comments": "Private note",
            },

            {
                "unique_no": 2,
                "scientific_name": "Meles meles",
                "species_no": 300,
                "common_name": "Badger",
                "taxanb": "Mammals",
                "verified": "Rejected",
                "record_type": "Observation",
                "easting": 400100,
                "northing": 300100,
                "record_date": "02/01/2023",
                "place": "Rejected place",
                "comments": "Ignore",
            },
        ]
    )


   # -----------------------------------------
    # 2. Verification filter
    # -----------------------------------------

    filtered = filter_accepted_records(
        raw,
        verified_column="verified",
    )

    assert set(filtered["unique_no"]) == {1}


    # -----------------------------------------
    # 3. Species resolution (D4)
    # -----------------------------------------

    dictionary = pd.DataFrame(
        [
            {
                "scientific": "Meles meles",
                "species_no": 300,
                "nbn_number": "NBN002",
                "common_name": "Badger",
                "taxanb": "Mammals",
            }
        ]
    )

    resolved = resolve_species_numbers(
        filtered,
        dictionary,
    )


    # -----------------------------------------
    # 4. Safety classification
    # -----------------------------------------

    classified = classify_chunk(resolved)