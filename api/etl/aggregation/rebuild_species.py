from datetime import datetime

import pandas as pd

from etl.reconciliation.load import upsert_species


def rebuild_species_index(
    connection,
    load_mode: str,
    load_timestamp=None,
) -> None:
    """
    Rebuilds species summary table from occurrence_public.

    occurrence_public is already the safety boundary,
    so species metadata is derived only from safe public records.

    load_mode ("initial" or "incremental") and load_timestamp are
    stamped onto the rebuilt species rows via the "Load" / "Load_date"
    audit columns, same as occurrence_public. If load_timestamp isn't
    given, the current time is used.
    """

    load_timestamp = load_timestamp or datetime.now()

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

    upsert_species(
        species_index,
        connection,
        load_mode=load_mode,
        load_timestamp=load_timestamp,
    )
