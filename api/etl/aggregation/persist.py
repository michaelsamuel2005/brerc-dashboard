# etl/aggregation/persist.py

from datetime import datetime, timezone
import pandas as pd

from etl.aggregation.geometry import cell_polygon_wkt


def to_python_none(value):
    """
    Convert pandas missing values (pd.NA, NaN) into Python None
    so psycopg can insert them as SQL NULL.
    """
    if pd.isna(value):
        return None
    return value


def persist_aggregation_outputs(
    connection,
    species_index,
    suppressed_counts,
    cell_size_m,
    load_number,
):
    now = datetime.now(timezone.utc)

    species_rows = [
        (
            to_python_none(row.species_id),
            to_python_none(row.scientific_name),
            to_python_none(row.common_name),
            to_python_none(row.species_group),
            int(row.record_count),
            to_python_none(row.first_year),
            to_python_none(row.last_year),
            bool(row.has_image),
            load_number,
            now,
        )
        for row in species_index.itertuples(index=False)
    ]

    cell_rows = [
        (
            row.grid_cell,
            row.species_no,
            int(row.year),
            cell_size_m,
            int(row.record_count),
            int(row.verified_count),
            cell_polygon_wkt(
                row.cell_sw_easting,
                row.cell_sw_northing,
                cell_size_m,
            ),
            load_number,
            now,
        )
        for row in suppressed_counts.itertuples(index=False)
    ]

    with connection.cursor() as cur:
        # distribution_cell is safe to truncate outright - nothing else
        # has a foreign key into it, so this can't cascade anywhere.
        cur.execute("TRUNCATE TABLE distribution_cell;")

        # species CANNOT be truncated, even without CASCADE:
        # occurrence_public.species_id has a foreign key into species,
        # so Postgres refuses TRUNCATE on species outright as long as
        # that constraint exists (this is what caused the original bug -
        # TRUNCATE ... CASCADE was cascading the delete into
        # occurrence_public and wiping reconciliation's inserts).
        #
        # Instead: upsert. Every species_id in this run's species_index
        # gets inserted if new, or has all its columns refreshed if it
        # already exists. This still achieves "recompute fully each
        # run" for every species that appears in the current data -
        # it just can't remove a species_id that no longer appears,
        # since that would require a DELETE, not an INSERT.
        #
        # (If a species drops to zero records, its row will linger with
        # stale counts rather than disappearing. Safe to add a cleanup
        # DELETE later, guarded by "AND species_id NOT IN (SELECT
        # species_id FROM occurrence_public)" so it's protected by the
        # same FK relationship rather than able to delete anything
        # still actually referenced.)
        cur.executemany(
            """
            INSERT INTO species
                (species_id, scientific_name, common_name, species_group,
                 record_count, first_year, last_year, has_image,
                 load_number, date_of_load)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (species_id) DO UPDATE SET
                scientific_name = EXCLUDED.scientific_name,
                common_name     = EXCLUDED.common_name,
                species_group   = EXCLUDED.species_group,
                record_count    = EXCLUDED.record_count,
                first_year      = EXCLUDED.first_year,
                last_year       = EXCLUDED.last_year,
                has_image       = EXCLUDED.has_image,
                load_number     = EXCLUDED.load_number,
                date_of_load    = EXCLUDED.date_of_load
            """,
            species_rows,
        )

        # distribution_cell.species_id references species, so this
        # insert must run after the species upsert above - otherwise
        # a cell for a brand-new species would violate the FK.
        cur.executemany(
            """
            INSERT INTO distribution_cell
                (cell_id, species_id, record_year, precision_metres,
                 record_count, verified_count, geom,
                 load_number, date_of_load)
            VALUES (%s,%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326),%s,%s)
            """,
            cell_rows,
        )

    connection.commit()