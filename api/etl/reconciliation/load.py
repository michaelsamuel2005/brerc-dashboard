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
    Bulk-loads a dataframe into a temp table via COPY,
    converts dataframe into in-memory CSV. Much faster
    than executemany() at scale (millions of rows).
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

    # Quote every column name for the COPY list. Harmless for ordinary
    # lowercase columns, but required for mixed-case columns like
    # "Load" - unquoted, Postgres would fold it to "load" and it
    # wouldn't match the (quoted) column_defs above.
    quoted_columns = ", ".join(f'"{c}"' for c in columns)

    # Copy (bulk loads) all rows into one operation
    with cursor.copy(
        f"COPY {temp_table} ({quoted_columns}) FROM STDIN WITH CSV"
    ) as copy:
        copy.write(buffer.getvalue())


# UPSERT: Try to insert record, if it already exists, update it instead
# As INSERT and UPDATE share identical SQL using PostgreSQL's


# Updates the species lookup table:
def upsert_species(
    species_df: pd.DataFrame,
    connection,
    load_mode: str,
    load_timestamp,
) -> None:

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

    # species_id comes from BRERC's SPECIES_NO field.
    # It is an identifier, not a number.
    # BRERC species numbers can contain letters (e.g. Axxxxx),
    # so they must remain as TEXT.
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

    # Stamp the ETL load audit columns, same as occurrence_public writes.
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


# Updates the actual biological records of species:
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
                "Load"           TEXT,
                "Load_date"      TIMESTAMPTZ
            """,
        )

        cursor.execute(
            """
            INSERT INTO occurrence_public (
                record_id, species_id, record_year, grid_ref,
                precision_metres, locality, verified, content_hash,
                "Load", "Load_date"
            )
            SELECT
                record_id, species_id, record_year, grid_ref,
                precision_metres, locality, verified, content_hash,
                "Load", "Load_date"
            FROM occurrence_staging

            -- If the record already exists, update the existing row instead
            -- of inserting a duplicate.
            ON CONFLICT (record_id) DO UPDATE SET
                species_id       = EXCLUDED.species_id,
                record_year      = EXCLUDED.record_year,
                grid_ref         = EXCLUDED.grid_ref,
                precision_metres = EXCLUDED.precision_metres,
                locality         = EXCLUDED.locality,
                verified         = EXCLUDED.verified,
                content_hash     = EXCLUDED.content_hash,
                "Load"           = EXCLUDED."Load",
                "Load_date"      = EXCLUDED."Load_date"
            """
        )

    connection.commit()


def insert_records(records_df: pd.DataFrame, connection) -> None:
    # New records identified during reconciliation are passed here.
    # The UPSERT function inserts them into occurrence_public.
    _upsert_occurrences(records_df, connection)


def update_records(records_df: pd.DataFrame, connection) -> None:
    # Existing records with changed content hashes are passed here.
    # The UPSERT function updates the existing occurrence_public row.
    _upsert_occurrences(records_df, connection)


def delete_records(record_ids: set, connection) -> None:
    # For records present in the UI database but missing from the latest
    # source dataset are removed during reconciliation
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
