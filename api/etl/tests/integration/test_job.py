import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from etl.job import (
    load_source_data,
    load_species_dictionary,
    get_current_ui_map,
    nightly_job,
)


# --- load_source_data tests ---


@patch("etl.job.pd.read_csv")
def test_load_source_data_csv_mode_without_watermark(mock_read_csv):
    # Confirms source data is loaded from CSV when source mode is csv.
    # The real database source provides the modification date column;
    # the CSV fixture mocks that production field for local testing.
    mock_df = pd.DataFrame(
        {
            "col": [1, 2],
            "modified_date": ["2026-01-01", "2026-01-02"],
        }
    )
    mock_read_csv.return_value = mock_df

    with patch(
        "etl.job.get_config",
        return_value={
            "source": {
                "mode": "csv",
                "records_path": "dummy.csv",
            },
            "columns": {
                "modified_date": "date_mdb_modified",
            },
        },
    ):
        result = load_source_data()

    mock_read_csv.assert_called_once_with("dummy.csv")
    assert len(result) == 2
    assert "date_mdb_modified" in result.columns


def test_load_source_data_database_mode_raises_valueerror_without_connection():
    # Confirms database mode enforces the presence of a source connection.
    # Expects a ValueError if source_connection is None.
    with patch(
        "etl.job.get_config",
        return_value={
            "source": {
                "mode": "database",
            },
            "columns": {
                "modified_date": "date_mdb_modified",
            },
        },
    ):
        with pytest.raises(ValueError) as exc_info:
            load_source_data(source_connection=None)

    assert "source_connection is required" in str(exc_info.value)


@patch("etl.job.pd.read_sql")
def test_load_source_data_database_mode_incremental(mock_read_sql):
    # Confirms incremental database queries are wrapped with a watermark
    # filter and that the source modification column is mapped correctly.
    mock_conn = MagicMock()

    mock_read_sql.return_value = pd.DataFrame(
        {
            "unique_no": [1],
            "modified_date": ["2026-01-01"],
        }
    )

    config = {
        "source": {
            "mode": "database",
            "records_query": "SELECT * FROM records",
        },
        "columns": {
            "modified_date": "date_mdb_modified",
        },
    }

    with patch("etl.job.get_config", return_value=config):
        result = load_source_data(
            source_connection=mock_conn,
            watermark_date="2026-01-01",
        )

    mock_read_sql.assert_called_once()

    called_query = mock_read_sql.call_args[0][0]

    assert "WHERE modified_date >= %(watermark_date)s" in called_query
    assert "date_mdb_modified" in result.columns


# --- load_species_dictionary tests ---


@patch("etl.job.pd.read_csv")
def test_load_species_dictionary_csv_mode(mock_read_csv):
    # Confirms the species dictionary is loaded from CSV in csv mode.
    # Expects pd.read_csv to be invoked with the configured dictionary path.
    mock_read_csv.return_value = pd.DataFrame(
        {
            "species": ["Robin"],
        }
    )

    with patch(
        "etl.job.get_config",
        return_value={
            "source": {
                "mode": "csv",
                "dictionary_path": "dummy_dict.csv",
            },
        },
    ):
        result = load_species_dictionary()

    mock_read_csv.assert_called_once_with("dummy_dict.csv")
    assert "species" in result.columns


def test_load_species_dictionary_database_mode_raises_missing_connection():
    # Confirms species dictionary loading enforces a database connection
    # when database mode is configured.
    with patch(
        "etl.job.get_config",
        return_value={
            "source": {
                "mode": "database",
            },
        },
    ):
        with pytest.raises(ValueError) as exc_info:
            load_species_dictionary(source_connection=None)

    assert "source_connection is required" in str(exc_info.value)


# --- get_current_ui_map tests ---


@patch("etl.job.get_ui_map")
def test_get_current_ui_map_calls_ui_map_getter(mock_get_ui_map):
    # Confirms get_current_ui_map delegates to get_ui_map.
    mock_get_ui_map.return_value = {
        "1": "2026-01-01 12:00:00",
    }

    conn = MagicMock()

    result = get_current_ui_map(conn)

    mock_get_ui_map.assert_called_once_with(conn)
    assert result == {
        "1": "2026-01-01 12:00:00",
    }


# --- nightly_job tests ---


@patch("etl.job.check_table_exists", return_value=True)
@patch("etl.job.check_table_has_rows", return_value=True)
@patch("etl.job.should_run_initial_load", return_value=False)
@patch("etl.job.get_last_load_date", return_value="2026-01-01")
@patch("etl.job.load_source_data", return_value=pd.DataFrame())
@patch("etl.job.load_species_dictionary", return_value=pd.DataFrame())
@patch("etl.job.get_current_ui_map", return_value={})
@patch("etl.job.run_pipeline")
@patch("etl.job.get_destination_connection")
def test_nightly_job_incremental_flow(
    mock_get_conn,
    mock_run_pipeline,
    mock_ui_map,
    mock_dict,
    mock_source,
    mock_last_date,
    mock_initial_check,
    mock_has_rows,
    mock_exists,
):
    # Confirms nightly_job orchestrates an incremental run when the
    # destination table exists and already contains rows.
    mock_conn_ctx = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn_ctx

    with patch(
        "etl.job.get_config",
        return_value={
            "source": {
                "mode": "csv",
            },
            "destination": {
                "table": "occurrence_public",
            },
            "load": {
                "incremental_check": True,
            },
        },
    ):
        nightly_job()

    mock_run_pipeline.assert_called_once()

    args = mock_run_pipeline.call_args[0]

    assert args[4] == "incremental"