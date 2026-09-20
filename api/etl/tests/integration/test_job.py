from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from etl.job import (
    LegacyNightlyJobBlocked,
    _assert_legacy_nightly_job_allowed,
    describe_failure,
    get_current_ui_map,
    load_source_data,
    load_species_dictionary,
    nightly_job,
)

# --- load_source_data tests ---


@patch("etl.job.pd.read_csv")
def test_load_source_data_csv_mode_without_watermark(mock_read_csv):
    # Confirms source data is loaded from CSV when source mode is csv
    # and safely injects the missing modification column for downstream ETL compatibility.
    mock_df = pd.DataFrame(
        {
            "col": [1, 2],
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
    assert "col" in result.columns
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
    # Confirms incremental database queries use the real BRERC
    # date_mdb_modified column and map it to the ETL's modified_date column.
    mock_conn = MagicMock()

    mock_read_sql.return_value = pd.DataFrame(
        {
            "unique_no": [1],
            "date_mdb_modified": ["2026-01-01"],
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

    assert "WHERE date_mdb_modified >= %(watermark_date)s" in called_query

    # The real database column should be present in the returned data.
    assert "date_mdb_modified" in result.columns

    # The source database column should also be mapped to
    # the ETL's internal modification-date column.
    assert "modified_date" in result.columns

    assert result["modified_date"].equals(result["date_mdb_modified"])


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


def test_nightly_job_is_blocked_by_default_before_any_side_effect():
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("etl.job.get_config") as mock_get_config,
        patch("etl.job.get_destination_connection") as mock_get_destination,
        patch("etl.job.start_run") as mock_start_run,
        pytest.raises(LegacyNightlyJobBlocked, match="brerc-load refresh"),
    ):
        nightly_job()

    mock_get_config.assert_not_called()
    mock_get_destination.assert_not_called()
    mock_start_run.assert_not_called()


@pytest.mark.parametrize("environment", ("dev", "test"))
def test_legacy_nightly_guard_requires_explicit_test_or_development_opt_in(environment):
    with patch.dict(
        "os.environ",
        {
            "APP_ENV": environment,
            "BRERC_ENABLE_LEGACY_NIGHTLY_JOB_FOR_TESTS": "1",
        },
        clear=True,
    ):
        _assert_legacy_nightly_job_allowed()


def test_nightly_job_cannot_be_enabled_in_production():
    with (
        patch.dict(
            "os.environ",
            {
                "APP_ENV": "prod",
                "BRERC_ENABLE_LEGACY_NIGHTLY_JOB_FOR_TESTS": "1",
            },
            clear=True,
        ),
        patch("etl.job.get_config") as mock_get_config,
        patch("etl.job.get_destination_connection") as mock_get_destination,
        patch("etl.job.start_run") as mock_start_run,
        pytest.raises(LegacyNightlyJobBlocked, match="brerc-load refresh"),
    ):
        nightly_job()

    mock_get_config.assert_not_called()
    mock_get_destination.assert_not_called()
    mock_start_run.assert_not_called()


@patch("etl.job.mark_run_successful")
@patch("etl.job.start_run", return_value=1)
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
    mock_start_run,
    mock_mark_successful,
):
    # Confirms nightly_job orchestrates an incremental run when the
    # destination table exists and already contains rows.
    mock_conn_ctx = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn_ctx

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
                },
                "destination": {
                    "table": "occurrence_public",
                },
                "load": {
                    "incremental_check": True,
                },
            },
        ),
    ):
        nightly_job()

    mock_run_pipeline.assert_called_once()

    args = mock_run_pipeline.call_args[0]

    assert args[4] == "incremental"

    # Confirms the run history row is opened as "running" (job_type =
    # the resolved load_mode) before the pipeline runs, and updated in
    # place to "successful" once it completes.
    mock_start_run.assert_called_once_with(job_type="incremental")
    mock_mark_successful.assert_called_once()
    assert mock_mark_successful.call_args[0][0] == 1

    # run_pipeline's mocked "reconciliation" summary has no real inserts/
    # updates/deletes lists, so the counts recorded alongside the run are 0.
    assert mock_mark_successful.call_args.kwargs["inserts"] == 0
    assert mock_mark_successful.call_args.kwargs["updates"] == 0
    assert mock_mark_successful.call_args.kwargs["deletes"] == 0


@patch("etl.job.mark_run_failed")
@patch("etl.job.start_run", return_value=7)
@patch("etl.job.check_table_exists", return_value=True)
@patch("etl.job.check_table_has_rows", return_value=True)
@patch("etl.job.should_run_initial_load", return_value=False)
@patch("etl.job.get_last_load_date", return_value="2026-01-01")
@patch("etl.job.load_source_data", return_value=pd.DataFrame())
@patch("etl.job.load_species_dictionary", return_value=pd.DataFrame())
@patch("etl.job.get_current_ui_map", return_value={})
@patch("etl.job.run_pipeline", side_effect=RuntimeError("boom"))
@patch("etl.job.get_destination_connection")
def test_nightly_job_marks_run_failed_on_exception(
    mock_get_conn,
    mock_run_pipeline,
    mock_ui_map,
    mock_dict,
    mock_source,
    mock_last_date,
    mock_initial_check,
    mock_has_rows,
    mock_exists,
    mock_start_run,
    mock_mark_failed,
):
    # Confirms that when the pipeline raises, the run history row started
    # for this run is updated in place to "failed" and the exception still
    # propagates to the caller.
    mock_conn_ctx = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn_ctx

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
                },
                "destination": {
                    "table": "occurrence_public",
                },
                "load": {
                    "incremental_check": True,
                },
            },
        ),
    ):
        with pytest.raises(RuntimeError):
            nightly_job()

    mock_mark_failed.assert_called_once_with(
        7,
        error_message="RuntimeError",
        error_summary="An unexpected error occurred during the update.",
    )


# --- describe_failure tests ---
# describe_failure() turns a raised exception into the plain-English summary
# shown to BRERC staff on the run-history dashboard. Only the exception's
# type name is stored alongside it (as error_message) — never its message,
# which can carry fragments of source data. The full error and traceback go
# to the server logs via logger.exception() instead.


def test_describe_failure_database_mismatch():
    from etl.load.reload import DatabaseMismatchError

    assert describe_failure(DatabaseMismatchError("targets differ")) == (
        "A safety check blocked a full database reset because the settings "
        "pointed at two different databases. No data was changed — check the "
        "database configuration."
    )


def test_describe_failure_missing_file():
    assert describe_failure(FileNotFoundError("no such file")) == (
        "A required data file could not be found."
    )


def test_describe_failure_connection_problem():
    # FileNotFoundError is itself an OSError, so this also confirms the more
    # specific case above is checked first.
    assert describe_failure(ConnectionRefusedError("connection refused")) == (
        "Couldn't connect to the database — it may be down or unreachable."
    )


def test_describe_failure_bad_source_data():
    assert describe_failure(ValueError("unknown species code 'XYZ'")) == (
        "A problem was found in the source data (e.g. an unrecognised species code)."
    )


def test_describe_failure_missing_column():
    assert describe_failure(KeyError("species_no")) == (
        "The source data was missing an expected column."
    )


def test_describe_failure_database_error():
    import psycopg

    assert describe_failure(psycopg.OperationalError("connection lost")) == (
        "A database error occurred while saving records."
    )


def test_describe_failure_unrecognised_exception_falls_back_to_generic_message():
    assert describe_failure(RuntimeError("boom")) == (
        "An unexpected error occurred during the update."
    )
