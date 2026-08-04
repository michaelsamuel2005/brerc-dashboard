# etl/aggregation/persist.py
from datetime import datetime, timezone
from psycopg.rows import dict_row

from etl.aggregation.geometry import cell_polygon_wkt


def persist_aggregation_outputs(connection, species_index, suppressed_counts, cell_size_m, load_number):
    now = datetime.now(timezone.utc)

    species_rows = [
        (
            row.species_id, row.scientific_name, row.common_name, row.species_group,
            int(row.record_count), row.first_year, row.last_year, bool(row.has_image),
            load_number, now,
        )
        for row in species_index.itertuples(index=False)
    ]

    cell_rows = [
        (
            row.grid_cell, row.species_no, int(row.year), cell_size_m,
            int(row.record_count), int(row.verified_count),
            cell_polygon_wkt(row.cell_sw_easting, row.cell_sw_northing, cell_size_m),
            load_number, now,
        )
        for row in suppressed_counts.itertuples(index=False)
    ]

    with connection.cursor() as cur:
        cur.execute("TRUNCATE TABLE distribution_cell;")
        cur.execute("TRUNCATE TABLE species CASCADE;")  # CASCADE: distribution_cell FKs into species

        cur.executemany(
            """
            INSERT INTO species
                (species_id, scientific_name, common_name, species_group,
                 record_count, first_year, last_year, has_image,
                 load_number, date_of_load)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            species_rows,
        )

        cur.executemany(
            """
            INSERT INTO distribution_cell
                (cell_id, species_id, record_year, precision_metres,
                 record_count, verified_count, geom,
                 load_number, date_of_load)
            VALUES (%s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, 4326), %s, %s)
            """,
            cell_rows,
        )

    connection.commit()