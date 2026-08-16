"""Unit tests for the SQLite-backed ETL run-history log."""

import sqlite3

import pytest

from etl import run_history


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Points run_history at a throwaway database so tests never touch the real log."""
    monkeypatch.setattr(run_history, "DB_PATH", tmp_path / "test_run_history.db")


def _fetch_all_rows():
    connection = sqlite3.connect(run_history.DB_PATH)
    try:
        connection.row_factory = sqlite3.Row
        return connection.execute("SELECT * FROM runs").fetchall()
    finally:
        connection.close()


def test_start_run_creates_a_running_row():
    run_number = run_history.start_run(job_type="incremental")

    rows = _fetch_all_rows()
    assert len(rows) == 1

    row = rows[0]
    assert row["run_number"] == run_number
    assert row["job_name"] == run_history.JOB_NAME
    assert row["job_type"] == "incremental"
    assert row["status"] == "running"
    assert row["load_no"] is None
    assert row["date"]  # populated with today's date
    assert row["started_at"]  # populated so duration can be computed later
    assert row["duration_seconds"] is None  # not known until the run finishes


def test_mark_run_successful_updates_the_same_row_in_place():
    run_number = run_history.start_run(job_type="initial")

    run_history.mark_run_successful(
        run_number, load_no="2026-08-14T12:00:00", inserts=12, updates=3, deletes=1
    )

    rows = _fetch_all_rows()
    assert len(rows) == 1  # updated in place, not appended

    row = rows[0]
    assert row["run_number"] == run_number
    assert row["status"] == "successful"
    assert row["load_no"] == "2026-08-14T12:00:00"
    assert row["duration_seconds"] is not None
    assert row["duration_seconds"] >= 0
    assert row["inserts"] == 12
    assert row["updates"] == 3
    assert row["deletes"] == 1


def test_mark_run_successful_without_counts_leaves_them_null():
    run_number = run_history.start_run(job_type="initial")

    run_history.mark_run_successful(run_number, load_no="2026-08-14T12:00:00")

    row = _fetch_all_rows()[0]
    assert row["inserts"] is None
    assert row["updates"] is None
    assert row["deletes"] is None


def test_mark_run_failed_updates_the_same_row_in_place():
    run_number = run_history.start_run(job_type="incremental")

    run_history.mark_run_failed(
        run_number,
        # error_message is just the exception's type name by convention (see
        # etl/job.py) — never the full message, which can carry fragments of
        # source data. This storage layer itself stores whatever it's given.
        error_message="ValueError",
        error_summary="A problem was found in the source data (e.g. an unrecognised species code).",
    )

    rows = _fetch_all_rows()
    assert len(rows) == 1

    row = rows[0]
    assert row["run_number"] == run_number
    assert row["status"] == "failed"
    assert row["load_no"] is None
    assert row["duration_seconds"] is not None
    assert row["duration_seconds"] >= 0
    assert row["error_message"] == "ValueError"
    assert row["error_summary"] == (
        "A problem was found in the source data (e.g. an unrecognised species code)."
    )


def test_mark_run_failed_without_error_details_leaves_them_null():
    run_number = run_history.start_run(job_type="incremental")

    run_history.mark_run_failed(run_number)

    row = _fetch_all_rows()[0]
    assert row["status"] == "failed"
    assert row["error_message"] is None
    assert row["error_summary"] is None
    assert row["inserts"] is None
    assert row["updates"] is None
    assert row["deletes"] is None


def test_mark_run_successful_leaves_error_details_null():
    run_number = run_history.start_run(job_type="initial")

    run_history.mark_run_successful(run_number, load_no="2026-08-14T12:00:00")

    row = _fetch_all_rows()[0]
    assert row["error_message"] is None
    assert row["error_summary"] is None


def test_successive_runs_get_increasing_run_numbers():
    first_run = run_history.start_run(job_type="initial")
    second_run = run_history.start_run(job_type="incremental")

    assert second_run > first_run
    assert len(_fetch_all_rows()) == 2


def test_connect_migrates_a_pre_existing_table_missing_new_columns():
    # Simulates a database file written before started_at/duration_seconds/
    # error_message/error_summary/inserts/updates/deletes existed, to confirm
    # old run history rows survive the upgrade rather than breaking on the
    # next start_run()/mark_run_*() call.
    connection = sqlite3.connect(run_history.DB_PATH)
    connection.execute(
        """
        CREATE TABLE runs (
            run_number INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name   TEXT NOT NULL,
            job_type   TEXT NOT NULL,
            date       TEXT NOT NULL,
            load_no    TEXT,
            status     TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO runs (job_name, job_type, date, load_no, status) VALUES (?, ?, ?, ?, ?)",
        (run_history.JOB_NAME, "incremental", "2026-01-01", None, "successful"),
    )
    connection.commit()
    connection.close()

    new_run_number = run_history.start_run(job_type="initial")
    run_history.mark_run_successful(new_run_number, load_no="2026-08-14T00:00:00")

    rows = _fetch_all_rows()
    assert len(rows) == 2  # pre-existing row preserved, new row added

    pre_existing_row = next(row for row in rows if row["run_number"] != new_run_number)
    assert pre_existing_row["status"] == "successful"
    assert pre_existing_row["duration_seconds"] is None  # never recorded for this old row
    assert pre_existing_row["error_message"] is None  # never recorded for this old row
    assert pre_existing_row["error_summary"] is None  # never recorded for this old row
    assert pre_existing_row["inserts"] is None  # never recorded for this old row
