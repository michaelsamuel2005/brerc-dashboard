"""
High-performance database persistence module using temporary staging tables 
and PostgreSQL's fast COPY command for bulk upserts and deletes.
"""

import csv
import io
import logging
import pandas as pd

from etl.load.metadata import add_load_metadata

logger = logging.getLogger(__name__)


def _copy_dataframe(
    cursor, df: pd.DataFrame, columns: list, temp_table: str, column_defs: str
):
    """
    Bulk-loads a dataframe into a temporary table via PostgreSQL's COPY command 
    by converting the dataframe into an in-memory CSV buffer. Significantly faster 
    than row-by-row executemany() for large datasets (millions of rows).
    """
    cursor.execute(
        f"""
        CREATE TEMP TABLE {temp_table} (
            {column_defs}
        )
        ON COMMIT DROP
        """
    )

    # Creates in memory CSV
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    # Comverts Dataframe into CSV rows
    writer.writerows(
        df[columns].astype(object)
        # Comverts pd.NA to NULL
        .where(pd.notna(df[columns]), None)
        # Comverts rows into tuples
        .itertuples(index=False, name=None)
    )
    # Moves cursor back to the beginning
    buffer.seek(0)

    # Quote every column name to safely support mixed-case identifiers (e.g. "Load")
    quoted_columns = ", ".join(f'"{c}"' for c in columns)

    # Bulk load everything into the staging table in one high-speed operation
    with cursor.copy(
        f"COPY {temp_table} ({quoted_columns}) FROM STDIN WITH CSV"
    ) as copy:
        copy.write(buffer.getvalue())


def upsert_species(
    species_df: pd.DataFrame,
    connection,
    load_mode: str,
    load_timestamp,
) -> None:
    """
    Upserts unique species summaries into the database 'species' table 
    using a staging table and ON CONFLICT conflict resolution.
    """
    if species_df.empty:
        return

    # Converts pandas missing value into python None
    # Since psycopgs can't adapt pd.NA as null
    species_df = species_df.astype(object).where(pd.notna(species_df), None)
    species_df["species_id"] = species_df["species_id"].astype(str).str.strip()

    required = {
        "species_id",
        "scientific_name",
        "common_name",
        "species_group",
        "record_count",
        "first_year",
        "last_year",
        "has_image",
    }

    missing = required - set(species_df.columns)

    if missing:
        raise KeyError(f"species_df missing required columns: {sorted(missing)}")

    # Ensure species_ids are valid text identifiers
    valid_species_id = species_df["species_id"].notna() & (
        species_df["species_id"].astype(str).str.strip() != ""
    )

    invalid_count = (~valid_species_id).sum()

    if invalid_count > 0:
        logger.warning(
            "%s species_index rows have a missing species_id "
            "and will be excluded from the species table write",
            invalid_count,
        )

    species_df = species_df.loc[valid_species_id].copy()

    if species_df.empty:
        return

    # Stamp audit metadata columns
    species_df = add_load_metadata(species_df, load_mode, load_timestamp)

    # Defines the column order
    columns = [
        "species_id",
        "scientific_name",
        "common_name",
        "species_group",
        "record_count",
        "first_year",
        "last_year",
        "has_image",
        "Load",
        "Load_date",
    ]

    with connection.cursor() as cursor:
        # Bulk-load into a temp staging table via COPY (fast at scale),
        # then a single INSERT ... ON CONFLICT does the actual upsert -
        # if species_id already exists, update the existing row with
        # the latest values from the incoming ETL data
        _copy_dataframe(
            cursor,
            species_df,
            columns,
            temp_table="species_staging",
            column_defs="""
                species_id      TEXT,
                scientific_name TEXT,
                common_name     TEXT,
                species_group   TEXT,
                record_count    INTEGER,
                first_year      INTEGER,
                last_year       INTEGER,
                has_image       BOOLEAN,
                "Load"          TEXT,
                "Load_date"     TIMESTAMPTZ
            """,
        )

        cursor.execute(
            """
            INSERT INTO species (
                species_id,
                scientific_name,
                common_name,
                species_group,
                record_count,
                first_year,
                last_year,
                has_image,
                "Load",
                "Load_date"
            )
            SELECT
                species_id,
                scientific_name,
                common_name,
                species_group,
                record_count,
                first_year,
                last_year,
                has_image,
                "Load",
                "Load_date"
            FROM species_staging
            ON CONFLICT (species_id) DO UPDATE SET
                scientific_name = EXCLUDED.scientific_name,
                common_name     = EXCLUDED.common_name,
                species_group   = EXCLUDED.species_group,
                record_count    = EXCLUDED.record_count,
                first_year      = EXCLUDED.first_year,
                last_year       = EXCLUDED.last_year,
                has_image       = EXCLUDED.has_image,
                "Load"          = EXCLUDED."Load",
                "Load_date"     = EXCLUDED."Load_date"
            """
        )

    connection.commit()


def _upsert_occurrences(records_df: pd.DataFrame, connection) -> None:
    """Helper function to bulk-load and upsert public occurrence records into PostgreSQL."""
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
        "date_mdb_modified",
        "Load",
        "Load_date",
    }

    missing = required - set(records_df.columns)

    if missing:
        raise KeyError(
            "records_df is missing columns required to write to "
            f"occurrence_public: {sorted(missing)}"
        )

    columns = [
        "record_id",
        "species_id",
        "record_year",
        "grid_ref",
        "precision_metres",
        "locality",
        "verified",
        "content_hash",
        "date_mdb_modified",
        "Load",
        "Load_date",
    ]

    with connection.cursor() as cursor:
        # Cursor used to execute SQL commands.
        # records_df: occurrence records to be written to the database.
        # columns: list of columns copied from dataframe into the staging table.
        # temp_table: temporary table used for bulk loading before insertion.
        # column_defs: defines the schema and data types of the temporary table.
        # All rows are first copied into this staging table before being
        # inserted/upserted into occurrence_public.
        _copy_dataframe(
            cursor,
            records_df,
            columns,
            temp_table="occurrence_staging",
            column_defs="""
                record_id        VARCHAR,
                species_id       TEXT,
                record_year      INTEGER,
                grid_ref         TEXT,
                precision_metres INTEGER,
                locality         TEXT,
                verified         BOOLEAN,
                content_hash     TEXT,
                date_mdb_modified TIMESTAMPTZ,
                "Load"           TEXT,
                "Load_date"      TIMESTAMPTZ
            """,
        )

        cursor.execute(
            """
            INSERT INTO occurrence_public (
                record_id, species_id, record_year, grid_ref,
                precision_metres, locality, verified, content_hash,
                date_mdb_modified, "Load", "Load_date"
            )
            SELECT
                record_id, species_id, record_year, grid_ref,
                precision_metres, locality, verified, content_hash,
                date_mdb_modified, "Load", "Load_date"
            FROM occurrence_staging

            -- If the record already exists, update the existing row instead
            -- of inserting a duplicate.
            ON CONFLICT (record_id) DO UPDATE SET
                species_id        = EXCLUDED.species_id,
                record_year       = EXCLUDED.record_year,
                grid_ref          = EXCLUDED.grid_ref,
                precision_metres  = EXCLUDED.precision_metres,
                locality          = EXCLUDED.locality,
                verified          = EXCLUDED.verified,
                content_hash      = EXCLUDED.content_hash,
                date_mdb_modified = EXCLUDED.date_mdb_modified,
                "Load"            = EXCLUDED."Load",
                "Load_date"       = EXCLUDED."Load_date"
            """
        )

    connection.commit()


def insert_records(records_df: pd.DataFrame, connection) -> None:
    """Inserts new occurrence records identified during reconciliation."""
    _upsert_occurrences(records_df, connection)


def update_records(records_df: pd.DataFrame, connection) -> None:
    """Updates existing occurrence records whose modification dates have changed."""
    _upsert_occurrences(records_df, connection)


def delete_records(record_ids: set, connection) -> None:
    """Removes obsolete records from the database that no longer appear in the source data."""
    if not record_ids:
        return

    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM occurrence_public
            WHERE record_id = ANY(%s)
            """,
            # Convert Python set of IDs into a list so it can be
            # passed to PostgreSQL as an array for the ANY() check.
            (list(record_ids),),
        )

    connection.commit()
