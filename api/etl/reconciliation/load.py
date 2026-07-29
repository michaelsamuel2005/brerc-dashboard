"""
    Real DB writes against Victor's B6 draft schema (db/b6_schema.sql),
    specifically the occurrence_public table.

    OPEN QUESTIONS FOR VICTOR (confirm before relying on this):
      1. occurrence_public has no content_hash column yet - needed
         for D7 reconciliation to diff against next run. Needs adding:
             ALTER TABLE occurrence_public ADD COLUMN content_hash TEXT;
      2. occurrence_public.species_id has a FK to species(species_id).
         Species rows must be upserted into `species` BEFORE any
         occurrence_public write, or inserts will fail on the FK.
         (This file assumes that's handled separately - see
         upsert_species below - call it first in the orchestrator.)

    Uses upsert (INSERT ... ON CONFLICT DO UPDATE) for both insert
    and update - simpler than two code paths, and makes a re-run
    naturally idempotent even for edge cases (e.g. a record that
    was deleted then re-added with the same id).
"""

import pandas as pd


def upsert_species(species_df: pd.DataFrame, connection) -> None:
    """
    Must run BEFORE insert_records/update_records, since
    occurrence_public.species_id has a foreign key to this table.
    """
    if species_df.empty:
        return

    rows = list(
        species_df[
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
        ].itertuples(index=False, name=None)
    )

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO species (
                species_id,
                scientific_name,
                common_name,
                species_group,
                record_count,
                first_year,
                last_year,
                has_image
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT (species_id) DO UPDATE SET
                scientific_name = EXCLUDED.scientific_name,
                common_name     = EXCLUDED.common_name,
                species_group   = EXCLUDED.species_group,
                record_count    = EXCLUDED.record_count,
                first_year      = EXCLUDED.first_year,
                last_year       = EXCLUDED.last_year,
                has_image       = EXCLUDED.has_image
            """,
            rows,
        )

    connection.commit()


def _upsert_occurrences(records_df: pd.DataFrame, connection) -> None:
    if records_df.empty:
        return

    required = {
        "record_id",
        "species_id",
        "record_year",
        "grid_ref",
        "locality",
        "precision_metres",
        "verified",
        "content_hash",
    }

    missing = required - set(records_df.columns)

    if missing:
        raise KeyError(
            f"records_df is missing columns required to write to occurrence_public: {missing}"
        )

    rows = list(
        records_df[
            [
                "record_id",
                "species_id",
                "record_year",
                "grid_ref",
                "precision_metres",
                "locality",
                "verified",
                "content_hash",
            ]
        ].itertuples(index=False, name=None)
    )

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO occurrence_public (
                record_id,
                species_id,
                record_year,
                grid_ref,
                precision_metres,
                locality,
                verified,
                content_hash
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT (record_id) DO UPDATE SET
                species_id       = EXCLUDED.species_id,
                record_year      = EXCLUDED.record_year,
                grid_ref         = EXCLUDED.grid_ref,
                precision_metres = EXCLUDED.precision_metres,
                locality         = EXCLUDED.locality,
                verified         = EXCLUDED.verified,
                content_hash     = EXCLUDED.content_hash
            """,
            rows,
        )

    connection.commit()


def insert_records(records_df: pd.DataFrame, connection) -> None:
    _upsert_occurrences(records_df, connection)


def update_records(records_df: pd.DataFrame, connection) -> None:
    _upsert_occurrences(records_df, connection)


def delete_records(record_ids: set, connection) -> None:
    if not record_ids:
        return

    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM occurrence_public
            WHERE record_id = ANY(%s)
            """,
            (list(record_ids),),
        )

    connection.commit()