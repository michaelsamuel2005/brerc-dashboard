from unittest.mock import patch

import pandas as pd

from etl.job import nightly_job
from etl.tests.conftest import needs_db


@needs_db
@patch("etl.job.load_source_data")
@patch("etl.job.load_species_dictionary")
@patch("etl.nightly_pipeline.resolve_species_numbers")
@patch("etl.job.force_full_reload")
def test_nightly_job_end_to_end(
    mock_force_reload,
    mock_resolve_species,
    mock_load_dict,
    mock_load_source,
    connection,
):
    """
    End-to-end integration test for the nightly ETL job.

    Uses a real PostgreSQL database while mocking the external source,
    dictionary, and species-resolution lookup.

    Verifies that:
        1. the nightly job completes;
        2. the source occurrence is reconciled as an insert;
        3. the species is included in the aggregation/species layer;
        4. the occurrence is persisted to occurrence_public;
        5. the occurrence references the correct species.
    """

    # ------------------------------------------------------------------
    # Do not clear the shared staging database here.
    #
    # The B0 integration tests rely on the sample data already present
    # in brerc_ui. Clearing the database would remove those records and
    # cause tests that expect the three sample species to fail.
    #
    # This test uses unique test IDs and removes only those records again
    # at the end of the test.
    # ------------------------------------------------------------------

    mock_force_reload.return_value = None

    # Use IDs that should not collide with the shared B0 sample data.
    #
    # species_id is stored as TEXT in the database, so keep this as a
    # string rather than an integer.
    test_record_id = "99999"
    test_species_id = "99999"

    # ------------------------------------------------------------------
    # Mock source records.
    #
    # "Accepted" is intentional: the safety/verified filtering stage
    # only allows accepted records into the public output.
    #
    # The real CSV does not contain date_mdb_modified, so the integration
    # test supplies the production database field explicitly.
    # ------------------------------------------------------------------
    sample_records = pd.DataFrame(
        {
            "unique_no": [test_record_id],
            "species_no": [test_species_id],
            "scientific_name": ["Erithacus rubecula"],
            "common_name": ["Robin"],
            "abundance": ["Common"],
            "sex_stage": ["Adult"],
            "record_type": ["Observation"],
            "vitality": ["Alive"],
            "date_of_record": ["15/06/2026"],
            "date_mdb_modified": ["2026-06-15 12:00:00+00"],
            "coarse_locality": ["Bristol"],
            "effective_resolution_m": [1000],
            "is_legacy": [False],
            "eastings": [558200],
            "northings": [172500],
            "verified": ["Accepted"],
            "species_unresolved": [False],
            "taxanb": ["TAX001"],
        }
    )

    # ------------------------------------------------------------------
    # Mock species dictionary.
    # ------------------------------------------------------------------
    sample_dictionary = pd.DataFrame(
        {
            "species_no": [test_species_id],
            "scientific_name": ["Erithacus rubecula"],
            "scientific": ["Erithacus rubecula"],
            "scientific_key": ["erithacus rubecula"],
            "nbn_number": ["NHMSYS0000530488"],
            "common_nam": ["Robin"],
            "taxanb": ["TAX001"],
            "common_name": ["Robin"],
            "species_group": ["Bird"],
            "record_count": [1],
            "first_year": [2026],
            "last_year": [2026],
            "has_image": [False],
        }
    )

    mock_load_source.return_value = sample_records
    mock_load_dict.return_value = sample_dictionary

    # ------------------------------------------------------------------
    # Mock species resolution.
    #
    # run_pipeline() imports resolve_species_numbers into etl.nightly_pipeline,
    # so this patch is applied at the location where the function is used.
    # ------------------------------------------------------------------
    resolved_records = sample_records.copy()
    resolved_records["species_unresolved"] = False
    resolved_records["taxanb"] = "TAX001"
    resolved_records["species_no"] = test_species_id

    mock_resolve_species.return_value = resolved_records

    # ------------------------------------------------------------------
    # Configuration used by nightly_job().
    # ------------------------------------------------------------------
    with (
        patch.dict(
            "os.environ",
            {
                "APP_ENV": "test",
                "BRERC_ENABLE_LEGACY_NIGHTLY_JOB_FOR_TESTS": "1",
            },
            clear=False,
        ),
        patch(
            "etl.job.get_config",
            return_value={
                "source": {
                    "mode": "csv",
                    "records_path": "dummy.csv",
                    "dictionary_path": "dummy_dict.csv",
                },
                "destination": {
                    "table": "occurrence_public",
                },
                "load": {
                    "incremental_check": False,
                },
                "aggregation": {
                    "cell_size_m": 1000,
                },
                "columns": {
                    "verified": "verified",
                    "eastings": "eastings",
                    "northings": "northings",
                    "record_date": "date_of_record",
                    "modified_date": "date_mdb_modified",
                },
                "reconciliation": {
                    "hash_columns": [
                        "scientific_name",
                        "abundance",
                        "sex_stage",
                        "record_type",
                        "vitality",
                        "verified",
                        "eastings",
                        "northings",
                    ]
                },
            },
        ),
    ):
        try:
            result = nightly_job()

            # ------------------------------------------------------------------
            # Verify the pipeline completed.
            # ------------------------------------------------------------------
            assert result is not None
            assert "reconciliation" in result
            assert "aggregation" in result

            # ------------------------------------------------------------------
            # Verify reconciliation detected the source record as an insert.
            # ------------------------------------------------------------------
            reconciliation = result["reconciliation"]

            assert test_record_id in reconciliation["inserts"]
            assert reconciliation["updates"] == set()
            assert test_record_id not in reconciliation["deletes"]

            # ------------------------------------------------------------------
            # Verify aggregation produced a species entry.
            # ------------------------------------------------------------------
            species_index = result["aggregation"]["species_index"]

            assert not species_index.empty
            assert test_species_id in (species_index["species_id"].astype(str).tolist())

            # ------------------------------------------------------------------
            # Verify the occurrence was actually persisted.
            # ------------------------------------------------------------------
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT record_id, species_id, date_mdb_modified
                    FROM occurrence_public
                    WHERE record_id = %s
                    """,
                    (test_record_id,),
                )

                row = cursor.fetchone()

            assert row is not None
            assert str(row["record_id"]) == test_record_id
            assert str(row["species_id"]) == test_species_id
            assert row["date_mdb_modified"] is not None

        finally:
            # ---------------------------------------------------------------
            # Restore the shared staging database so this integration test
            # does not affect other tests that rely on the sample data.
            #
            # Delete the dependent records first, then the species row.
            # ---------------------------------------------------------------
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM occurrence_public
                    WHERE record_id = %s;
                    """,
                    (test_record_id,),
                )

                cursor.execute(
                    """
                    DELETE FROM distribution_cell
                    WHERE species_id = %s;
                    """,
                    (test_species_id,),
                )

                cursor.execute(
                    """
                    DELETE FROM species
                    WHERE species_id = %s;
                    """,
                    (test_species_id,),
                )

            connection.commit()
