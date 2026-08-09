import csv
from datetime import datetime
from pathlib import Path

# This will create a 'logs' folder at the root of your project
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
    error_message: str = ""
):
    """
    Appends the results of an ETL run to a CSV file so non-developers
    can easily monitor pipeline health via Excel/CSV viewer.
    """
    # Ensure the logs directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if we need to write the CSV headers
    file_exists = LOG_FILE.exists()

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        
        if not file_exists:
            writer.writerow([
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
                "Error Details"
            ])

        duration = (end_time - start_time).total_seconds()
        
        writer.writerow([
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
            error_message
        ])