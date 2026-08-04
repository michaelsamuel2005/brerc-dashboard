import pandas as pd

from etl.reconciliation.load import upsert_species


def rebuild_species_index(
    connection,
) -> None:
    """
    Rebuilds species summary table from occurrence_public.

    occurrence_public is already the safety boundary,
    so species metadata is derived only from safe public records.
    """

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
        species_records
        .groupby(
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
    )