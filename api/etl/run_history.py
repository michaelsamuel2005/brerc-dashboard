"""
ETL run-history logging. Tracks each pipeline run as a single row in a local
SQLite database, created as 'running' and updated in place to 'successful'
or 'failed' as the run progresses — so the history always shows one line per
run rather than a new line per status change.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

# Path to the persistent run history database, in the project's root 'logs' folder
DB_PATH = Path(__file__).resolve().parents[2] / "logs" / "etl_run_history.db"

JOB_NAME = "UI ETL RUN"

# Columns added after the table's initial release. Added via ALTER TABLE for
# any pre-existing database file, so older run history rows aren't lost.
_ADDED_COLUMNS = (
    ("started_at", "TEXT"),
    ("duration_seconds", "REAL"),
)


def _connect() -> sqlite3.Connection:
    """Opens a connection to the run history database, creating/migrating the table if needed."""
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

    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
    for column, sql_type in _ADDED_COLUMNS:
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE runs ADD COLUMN {column} {sql_type}")

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
            INSERT INTO runs (job_name, job_type, date, load_no, status, started_at, duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_name,
                job_type,
                date.today().isoformat(),
                None,
                "running",
                datetime.now().isoformat(),
                None,
            ),
        )
        connection.commit()

        return cursor.lastrowid
    finally:
        connection.close()


def _finish_run(run_number: int, status: str, load_no: str | None) -> None:
    """Shared by mark_run_successful/mark_run_failed: updates status, load_no,
    and the elapsed duration since start_run() was called for this row."""
    connection = _connect()

    try:
        row = connection.execute(
            "SELECT started_at FROM runs WHERE run_number = ?", (run_number,)
        ).fetchone()

        duration_seconds = None
        if row and row[0]:
            duration_seconds = (datetime.now() - datetime.fromisoformat(row[0])).total_seconds()

        connection.execute(
            "UPDATE runs SET status = ?, load_no = ?, duration_seconds = ? WHERE run_number = ?",
            (status, load_no, duration_seconds, run_number),
        )
        connection.commit()
    finally:
        connection.close()


def mark_run_successful(run_number: int, load_no: str | None) -> None:
    """Updates a run's row in place to 'successful', stamping its load_no and duration."""
    _finish_run(run_number, "successful", load_no)


def mark_run_failed(run_number: int, load_no: str | None = None) -> None:
    """Updates a run's row in place to 'failed', stamping its duration."""
    _finish_run(run_number, "failed", load_no)
