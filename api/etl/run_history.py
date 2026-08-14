"""
ETL run-history logging. Tracks each pipeline run as a single row in a local
SQLite database, created as 'running' and updated in place to 'successful'
or 'failed' as the run progresses — so the history always shows one line per
run rather than a new line per status change.
"""

import sqlite3
from datetime import date
from pathlib import Path

# Path to the persistent run history database, in the project's root 'logs' folder
DB_PATH = Path(__file__).resolve().parents[2] / "logs" / "etl_run_history.db"

JOB_NAME = "UI etl run"


def _connect() -> sqlite3.Connection:
    """Opens a connection to the run history database, creating the table if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_number INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name   TEXT NOT NULL,
            job_type   TEXT NOT NULL,
            date       TEXT NOT NULL,
            load_no    TEXT,
            status     TEXT NOT NULL
        )
        """
    )
    connection.commit()

    return connection


def start_run(job_type: str, job_name: str = JOB_NAME) -> int:
    """
    Records the start of an ETL run as a new 'running' row and returns its
    run_number, which identifies this run's row for later status updates.
    """
    connection = _connect()

    try:
        cursor = connection.execute(
            """
            INSERT INTO runs (job_name, job_type, date, load_no, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_name, job_type, date.today().isoformat(), None, "running"),
        )
        connection.commit()

        return cursor.lastrowid
    finally:
        connection.close()


def mark_run_successful(run_number: int, load_no: str | None) -> None:
    """Updates a run's row in place to 'successful', stamping its load_no."""
    connection = _connect()

    try:
        connection.execute(
            "UPDATE runs SET status = ?, load_no = ? WHERE run_number = ?",
            ("successful", load_no, run_number),
        )
        connection.commit()
    finally:
        connection.close()


def mark_run_failed(run_number: int, load_no: str | None = None) -> None:
    """Updates a run's row in place to 'failed'."""
    connection = _connect()

    try:
        connection.execute(
            "UPDATE runs SET status = ?, load_no = ? WHERE run_number = ?",
            ("failed", load_no, run_number),
        )
        connection.commit()
    finally:
        connection.close()
