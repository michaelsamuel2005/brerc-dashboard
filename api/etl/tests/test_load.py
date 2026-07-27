import pandas as pd

from app.db import get_connection

from etl.reconciliation.load import (
    upsert_species,
    insert_records,
    update_records,
    delete_records,
)


def test_species_and_occurrence_insert_update_delete():
    species_df = pd.DataFrame([
        {
            "species_id": 999999,
            "scientific_name": "Test species",
            "common_name": "Test species",
            "species_group": "Test",
            "record_count": 1,
            "first_year": 2020,
            "last_year": 2020,
            "has_image": False,
        }
    ])

    occurrence_df = pd.DataFrame([
        {
            "record_id": 999999,
            "species_id": 999999,
            "record_year": 2020,
            "grid_ref": "SU1234",
            "precision_metres": 1000,
            "locality": "Test locality",
            "verified": True,
            "content_hash": "hash-original",
        }
    ])

    with get_connection() as connection:

        # Species must be inserted before occurrence_public
        upsert_species(
            species_df,
            connection,
        )

        # Insert the occurrence
        insert_records(
            occurrence_df,
            connection,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT record_id, content_hash, grid_ref
                FROM occurrence_public
                WHERE record_id = %s
                """,
                (999999,),
            )

            row = cursor.fetchone()

        assert row["record_id"] == 999999
        assert row["content_hash"] == "hash-original"
        assert row["grid_ref"] == "SU1234"

        # Update the existing occurrence
        updated_occurrence_df = occurrence_df.copy()

        updated_occurrence_df["grid_ref"] = "SU5678"
        updated_occurrence_df["content_hash"] = "hash-updated"

        update_records(
            updated_occurrence_df,
            connection,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT content_hash, grid_ref
                FROM occurrence_public
                WHERE record_id = %s
                """,
                (999999,),
            )

            row = cursor.fetchone()

        assert row["content_hash"] == "hash-updated"
        assert row["grid_ref"] == "SU5678"

        # Delete the occurrence
        delete_records(
            {999999},
            connection,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM occurrence_public
                WHERE record_id = %s
                """,
                (999999,),
            )

            row = cursor.fetchone()

        assert row["count"] == 0