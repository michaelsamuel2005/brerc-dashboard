import pandas as pd

from etl.aggregation.persist import persist_aggregation_outputs


def test_persist_aggregation_outputs_inserts_species_and_cells(connection):
    """
    Ensures aggregation outputs are written into:
        - species
        - distribution_cell

    Also checks that ETL metadata fields are populated.
    """

    species_index = pd.DataFrame(
        {
            "species_id": ["123"],
            "scientific_name": ["Test species"],
            "common_name": ["Test bird"],
            "species_group": ["Bird"],
            "record_count": [5],
            "first_year": [2020],
            "last_year": [2025],
            "has_image": [False],
        }
    )

    suppressed_counts = pd.DataFrame(
        {
            "grid_cell": ["ST61"],
            "species_no": ["123"],
            "year": [2025],
            "record_count": [5],
            "verified_count": [5],
            "cell_sw_easting": [360000],
            "cell_sw_northing": [170000],
        }
    )

    persist_aggregation_outputs(
        connection,
        species_index,
        suppressed_counts,
        cell_size_m=1000,
        load_number=1,
    )

    with connection.cursor() as cur:

        cur.execute(
            """
            SELECT
                species_id,
                scientific_name,
                load_number,
                date_of_load
            FROM species
            WHERE species_id = '123'
            """
        )

        species_row = cur.fetchone()

        assert species_row is not None
        assert species_row["species_id"] == "123"
        assert species_row["scientific_name"] == "Test species"
        assert species_row["load_number"] == 1
        assert species_row["date_of_load"] is not None


        cur.execute(
            """
            SELECT
                cell_id,
                species_id,
                record_year,
                record_count,
                verified_count,
                load_number,
                date_of_load
            FROM distribution_cell
            WHERE species_id = '123'
            """
        )

        cell_row = cur.fetchone()

        assert cell_row is not None
        assert cell_row["species_id"] == "123"
        assert cell_row["record_year"] == 2025
        assert cell_row["record_count"] == 5
        assert cell_row["verified_count"] == 5
        assert cell_row["load_number"] == 1
        assert cell_row["date_of_load"] is not None



def test_persist_aggregation_outputs_replaces_previous_data(connection):
    """
    Ensures derived tables are rebuilt each ETL run.

    Old aggregation data should disappear after
    a new rebuild.
    """

    first_species = pd.DataFrame(
        {
            "species_id": ["111"],
            "scientific_name": ["Old species"],
            "common_name": ["Old"],
            "species_group": ["Bird"],
            "record_count": [2],
            "first_year": [2020],
            "last_year": [2020],
            "has_image": [False],
        }
    )

    first_counts = pd.DataFrame(
        {
            "grid_cell": ["ST11"],
            "species_no": ["111"],
            "year": [2020],
            "record_count": [2],
            "verified_count": [2],
            "cell_sw_easting": [300000],
            "cell_sw_northing": [100000],
        }
    )

    persist_aggregation_outputs(
        connection,
        first_species,
        first_counts,
        cell_size_m=1000,
        load_number=1,
    )


    second_species = pd.DataFrame(
        {
            "species_id": ["222"],
            "scientific_name": ["New species"],
            "common_name": ["New"],
            "species_group": ["Plant"],
            "record_count": [10],
            "first_year": [2025],
            "last_year": [2025],
            "has_image": [False],
        }
    )

    second_counts = pd.DataFrame(
        {
            "grid_cell": ["ST22"],
            "species_no": ["222"],
            "year": [2025],
            "record_count": [10],
            "verified_count": [10],
            "cell_sw_easting": [400000],
            "cell_sw_northing": [200000],
        }
    )

    persist_aggregation_outputs(
        connection,
        second_species,
        second_counts,
        cell_size_m=1000,
        load_number=2,
    )


    with connection.cursor() as cur:

        cur.execute(
            """
            SELECT COUNT(*)
            FROM species
            WHERE species_id = '111'
            """
        )

        old_species_count = cur.fetchone()["count"]
        assert old_species_count == 0


        cur.execute(
            """
            SELECT COUNT(*)
            FROM species
            WHERE species_id = '222'
            """
        )

        new_species_count = cur.fetchone()["count"]
        assert new_species_count == 1