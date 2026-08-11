"""
ETL run history logging utility. Appends execution metrics, durations, 
and status details to a persistent CSV log file for auditing and monitoring.
"""

import csv
from datetime import datetime
from pathlib import Path

# Path to the persistent run history CSV file located in the project's root 'logs' folder
LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "etl_run_history.csv"


def log_etl_run(
    start_time: datetime,
    end_time: datetime,
    load_mode: str,
    status: str,
    inserts: int = 0,
    updates: int = 0,
    deletes: int = 0,
    rejected_rows: int = 0,
    error_message: str = "",
):
    """
    Appends the execution metrics, performance durations, and status results 
    of an ETL run to a persistent CSV history file for operational monitoring.
    """
    # Ensure the logs directory exists, creating parent folders if necessary
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Check whether the log file already exists to determine if headers are required
    file_exists = LOG_FILE.exists()

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        # Write header row if initializing a brand-new log file
        if not file_exists:
            writer.writerow(
                [
                    "Date",
                    "Start Time",
                    "End Time",
                    "Duration (seconds)",
                    "Load Mode",
                    "Status",
                    "Inserts",
                    "Updates",
                    "Deletes",
                    "Rejected Rows",
                    "Error Details",
                ]
            )

        duration = (end_time - start_time).total_seconds()

        # Write execution details for the current run
        writer.writerow(
            [
                start_time.strftime("%Y-%m-%d"),
                start_time.strftime("%H:%M:%S"),
                end_time.strftime("%H:%M:%S"),
                round(duration, 2),
                load_mode,
                status,
                inserts,
                updates,
                deletes,
                rejected_rows,
                error_message,
            ]
        )
