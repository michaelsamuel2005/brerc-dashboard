"""
Rebuilds the species summary table using only safe records 
from the public occurrences table.
"""

from datetime import datetime

import pandas as pd

from etl.reconciliation.load import upsert_species


def rebuild_species_index(
    connection,
    load_mode: str,
    load_timestamp=None,
) -> None:
    """
    Pulls safe records from occurrence_public, groups them by species 
    to calculate counts and date ranges, adds default placeholders 
    for missing fields, and updates the species table.
    """

    # Use current time if no specific timestamp was given for the run
    load_timestamp = load_timestamp or datetime.now()

    # Grab everything needed from the public records table
    species_records = pd.read_sql(
        """
        SELECT
            species_id,
            scientific_name,
            record_year
        FROM occurrence_public
        """,
        connection,
    )

    if species_records.empty:
        return

    # Group by species to tally up total records and find the date range
    species_index = (
        species_records.groupby(
            [
                "species_id",
                "scientific_name",
            ],
            dropna=False,
        )
        .agg(
            record_count=("species_id", "count"),
            first_year=("record_year", "min"),
            last_year=("record_year", "max"),
        )
        .reset_index()
    )

    # Fields not available from occurrence_public
    # are populated safely with defaults.
    species_index["common_name"] = None
    species_index["species_group"] = "unknown"
    species_index["has_image"] = False

    # Put columns in the exact order the database expects them
    species_index = species_index[
        [
            "species_id",
            "scientific_name",
            "common_name",
            "species_group",
            "record_count",
            "first_year",
            "last_year",
            "has_image",
        ]
    ]

    # Push the finalised summary table into the database
    upsert_species(
        species_index,
        connection,
        load_mode=load_mode,
        load_timestamp=load_timestamp,
    )
