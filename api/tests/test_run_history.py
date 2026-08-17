"""Tests for the SQLite-backed ETL run-history log (etl/run_history.py).

Ported with the module from main, where they ran under pytest
(api/etl/tests/test_run_history.py, author: Ting Ting). Converted to unittest
so they run in this branch's dependency-free test job; the behaviour asserted
is unchanged — one row per run, updated in place, with the schema migration
that keeps pre-existing history readable.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from etl import run_history


class RunHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        # Point the module at a throwaway database so tests never touch the
        # real log, restoring the original path whatever happens.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._original_db_path = run_history.DB_PATH
        run_history.DB_PATH = Path(self._tmp.name) / "test_run_history.db"
        self.addCleanup(self._restore_db_path)

    def _restore_db_path(self) -> None:
        run_history.DB_PATH = self._original_db_path

    def fetch_all_rows(self) -> list[sqlite3.Row]:
        connection = sqlite3.connect(run_history.DB_PATH)
        try:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM runs").fetchall()
        finally:
            connection.close()

    def test_start_run_creates_a_running_row(self) -> None:
        run_number = run_history.start_run(job_type="incremental")

        rows = self.fetch_all_rows()
        self.assertEqual(len(rows), 1)

        row = rows[0]
        self.assertEqual(row["run_number"], run_number)
        self.assertEqual(row["job_name"], run_history.JOB_NAME)
        self.assertEqual(row["job_type"], "incremental")
        self.assertEqual(row["status"], "running")
        self.assertIsNone(row["load_no"])
        self.assertTrue(row["date"])  # populated with today's date
        self.assertTrue(row["started_at"])  # populated so duration can be computed later
        self.assertIsNone(row["duration_seconds"])  # not known until the run finishes

    def test_mark_run_successful_updates_the_same_row_in_place(self) -> None:
        run_number = run_history.start_run(job_type="initial")

        run_history.mark_run_successful(
            run_number, load_no="2026-08-14T12:00:00", inserts=12, updates=3, deletes=1
        )

        rows = self.fetch_all_rows()
        self.assertEqual(len(rows), 1)  # updated in place, not appended

        row = rows[0]
        self.assertEqual(row["run_number"], run_number)
        self.assertEqual(row["status"], "successful")
        self.assertEqual(row["load_no"], "2026-08-14T12:00:00")
        self.assertIsNotNone(row["duration_seconds"])
        self.assertGreaterEqual(row["duration_seconds"], 0)
        self.assertEqual(row["inserts"], 12)
        self.assertEqual(row["updates"], 3)
        self.assertEqual(row["deletes"], 1)

    def test_mark_run_successful_without_counts_leaves_them_null(self) -> None:
        run_number = run_history.start_run(job_type="initial")

        run_history.mark_run_successful(run_number, load_no="2026-08-14T12:00:00")

        row = self.fetch_all_rows()[0]
        self.assertIsNone(row["inserts"])
        self.assertIsNone(row["updates"])
        self.assertIsNone(row["deletes"])

    def test_mark_run_failed_updates_the_same_row_in_place(self) -> None:
        run_number = run_history.start_run(job_type="incremental")

        run_history.mark_run_failed(
            run_number,
            # error_message is just the exception's type name by convention —
            # never the full message, which can carry fragments of source
            # data. This storage layer itself stores whatever it's given.
            error_message="ValueError",
            error_summary=(
                "A problem was found in the source data (e.g. an unrecognised species code)."
            ),
        )

        rows = self.fetch_all_rows()
        self.assertEqual(len(rows), 1)

        row = rows[0]
        self.assertEqual(row["run_number"], run_number)
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["load_no"])
        self.assertIsNotNone(row["duration_seconds"])
        self.assertGreaterEqual(row["duration_seconds"], 0)
        self.assertEqual(row["error_message"], "ValueError")
        self.assertEqual(
            row["error_summary"],
            "A problem was found in the source data (e.g. an unrecognised species code).",
        )

    def test_mark_run_failed_without_error_details_leaves_them_null(self) -> None:
        run_number = run_history.start_run(job_type="incremental")

        run_history.mark_run_failed(run_number)

        row = self.fetch_all_rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["error_message"])
        self.assertIsNone(row["error_summary"])
        self.assertIsNone(row["inserts"])
        self.assertIsNone(row["updates"])
        self.assertIsNone(row["deletes"])

    def test_mark_run_successful_leaves_error_details_null(self) -> None:
        run_number = run_history.start_run(job_type="initial")

        run_history.mark_run_successful(run_number, load_no="2026-08-14T12:00:00")

        row = self.fetch_all_rows()[0]
        self.assertIsNone(row["error_message"])
        self.assertIsNone(row["error_summary"])

    def test_successive_runs_get_increasing_run_numbers(self) -> None:
        first_run = run_history.start_run(job_type="initial")
        second_run = run_history.start_run(job_type="incremental")

        self.assertGreater(second_run, first_run)
        self.assertEqual(len(self.fetch_all_rows()), 2)

    def test_connect_migrates_a_pre_existing_table_missing_new_columns(self) -> None:
        # Simulates a database file written before started_at/duration_seconds/
        # error_message/error_summary/inserts/updates/deletes existed, to
        # confirm old run history rows survive the upgrade rather than
        # breaking on the next start_run()/mark_run_*() call.
        run_history.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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

        rows = self.fetch_all_rows()
        self.assertEqual(len(rows), 2)  # pre-existing row preserved, new row added

        pre_existing_row = next(row for row in rows if row["run_number"] != new_run_number)
        self.assertEqual(pre_existing_row["status"], "successful")
        # Never recorded for this old row — migration adds the columns as NULL.
        self.assertIsNone(pre_existing_row["duration_seconds"])
        self.assertIsNone(pre_existing_row["error_message"])
        self.assertIsNone(pre_existing_row["error_summary"])
        self.assertIsNone(pre_existing_row["inserts"])


if __name__ == "__main__":
    unittest.main()
