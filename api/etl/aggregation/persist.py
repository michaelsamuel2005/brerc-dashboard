"""
Saves the processed species and grid cell data into the database.

How this works:
- Grid cells (distribution_cell): We wipe them all out and reload them fresh 
  every single night, because nothing else depends on them.
- Species (species): We CANNOT just wipe this table because the individual 
  occurrence records link directly to it. If we delete it, PostgreSQL will block us.
  Instead, we update existing species, add new ones, and only delete old species 
  if they completely vanished from the data and aren't being used by any records.
"""
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
    load_mode,
):
    """
    Persists aggregated spatial cells and upserts the species index to the database,
    handling foreign key constraints and stale record cleanups.
    """
    now = datetime.now(timezone.utc)

    species_rows = [
        (
            None if pd.isna(row.species_id) else str(row.species_id),
            to_python_none(row.scientific_name),
            to_python_none(row.common_name),
            to_python_none(row.species_group),
            int(row.record_count),
            to_python_none(row.first_year),
            to_python_none(row.last_year),
            bool(row.has_image),
            load_mode,
            now,
        )
        for row in species_index.itertuples(index=False)
    ]

    # Full set of species_ids present in THIS run's species_index.
    # Used below to remove any species that no longer appear at all,
    # so the species table doesn't accumulate stale rows forever.
    current_species_ids = [
        str(row.species_id)
        for row in species_index.itertuples(index=False)
        if not pd.isna(row.species_id)
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
            load_mode,
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
        # already exists.
        cur.executemany(
            """
            INSERT INTO species
                (species_id, scientific_name, common_name, species_group,
                 record_count, first_year, last_year, has_image,
                 "Load", "Load_date")
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            """,
            species_rows,
        )

        # Remove species that no longer appear in the current data at
        # all, so the table doesn't silently accumulate stale entries
        # with outdated counts forever ("recompute fully each run").
        #
        # Only delete species that are not referenced by occurrence_public.
        # This prevents the foreign-key constraint from being violated if
        # reconciliation still contains an occurrence for a species that
        # is absent from this run's aggregation.
        cur.execute(
            """
            DELETE FROM species s
            WHERE s.species_id != ALL(%s)
            AND NOT EXISTS (
                SELECT 1
                FROM occurrence_public o
                WHERE o.species_id = s.species_id
            )
            """,
            (current_species_ids,),
        )

        # distribution_cell.species_id references species, so this
        # insert must run after the species upsert/delete above -
        # otherwise a cell for a brand-new species would violate the FK.
        cur.executemany(
            """
            INSERT INTO distribution_cell
                (cell_id, species_id, record_year, precision_metres,
                 record_count, verified_count, geom,
                 "Load", "Load_date")
            VALUES (%s,%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326),%s,%s)
            """,
            cell_rows,
        )

    connection.commit()
