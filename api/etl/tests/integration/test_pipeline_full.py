import pandas as pd
import pytest
from unittest.mock import patch

from etl.job import nightly_job
from tests.conftest import needs_db


@needs_db
@patch("app.db.B6_PUBLIC_RELATIONS", {"occurrence_public", "species", "distribution_cell"})
@patch("etl.job.load_source_data")
@patch("etl.job.load_species_dictionary")
@patch("etl.matching.species.resolve_species_numbers")
@patch("etl.job.force_full_reload")
def test_nightly_job_end_to_end(
    mock_force_reload, 
    mock_resolve_species, 
    mock_load_dict, 
    mock_load_source, 
    connection
):
    # Confirms the entire ETL pipeline executes successfully end-to-end against a real database.
    # Expects source records to be cleaned, aggregated, generalised via PostGIS, and persisted, else fails.

    def side_effect_force_reload(conn):
        with conn.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE IF EXISTS provenance ADD COLUMN IF NOT EXISTS "Load" TEXT;
                ALTER TABLE IF EXISTS provenance ADD COLUMN IF NOT EXISTS "Load_date" TIMESTAMP;
                ALTER TABLE IF EXISTS provenance ALTER COLUMN load_number DROP NOT NULL;
                ALTER TABLE IF EXISTS provenance ALTER COLUMN load_number SET DEFAULT 1;
                ALTER TABLE IF EXISTS provenance ALTER COLUMN date_of_load DROP NOT NULL;
                ALTER TABLE IF EXISTS provenance ALTER COLUMN date_of_load SET DEFAULT CURRENT_TIMESTAMP;
                TRUNCATE TABLE occurrence_public, distribution_cell, species, provenance RESTART IDENTITY CASCADE;
                """
            )
        conn.commit()

    mock_force_reload.side_effect = side_effect_force_reload

    sample_records = pd.DataFrame({
        "unique_no": ["99999"],  # String type matching VARCHAR database column
        "species_no": [100],
        "scientific_name": ["Erithacus rubecula"],
        "common_name": ["Robin"],
        "abundance": ["Common"],
        "sex_stage": ["Adult"],
        "record_type": ["Observation"],
        "vitality": ["Alive"],
        "record_date": ["15/06/2026"],
        "date_of_record": ["2026-06-15"],
        "coarse_locality": ["Bristol"],
        "effective_resolution_m": [1000],
        "is_legacy": [False],
        "eastings": [558200],
        "northings": [172500],
        "verified": ["Yes"],
        "species_unresolved": [False],
        "taxanb": ["TAX001"],
    })

    sample_dictionary = pd.DataFrame({
        "species_no": [100],
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
    })

    mock_load_source.return_value = sample_records
    mock_load_dict.return_value = sample_dictionary
    
    # Mock species resolution to return the sample records successfully resolved
    resolved_records = sample_records.copy()
    resolved_records["species_unresolved"] = False
    resolved_records["taxanb"] = "TAX001"
    mock_resolve_species.return_value = resolved_records

    with patch("etl.job.CONFIG", {
        "source": {"mode": "csv", "records_path": "dummy.csv", "dictionary_path": "dummy_dict.csv"},
        "destination": {"table": "occurrence_public"},
        "load": {"incremental_check": False},
        "aggregation": {"cell_size_m": 1000},
        "columns": {
            "verified": "verified",
            "eastings": "eastings",
            "northings": "northings",
            "record_date": "date_of_record",
            "modified_date": "modified_date"
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
                "northings"
            ]
        }
    }):
        result = nightly_job()

    assert result is not None
    assert "reconciliation" in result
    assert "aggregation" in result

    with connection.cursor() as cursor:
        cursor.execute("SELECT record_id, species_id FROM occurrence_public WHERE record_id = '99999'")
        row = cursor.fetchone()
        
    assert row is not None
    assert str(row["record_id"]) == "99999"
    assert int(row["species_id"]) == 100