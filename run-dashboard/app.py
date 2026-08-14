"""
Standalone read-only viewer for the ETL run-history log.

Reads the SQLite database written by api/etl/run_history.py and serves it as
JSON plus a small static HTML page. Deliberately kept separate from api/app
(the public, read-only dashboard API) — this is an internal ops tool with no
front-end or database dependency of its own.

Run locally:
    uvicorn app:app --reload --port 8100
Then open http://127.0.0.1:8100/
"""

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Same path convention as api/etl/run_history.py: <repo root>/logs/etl_run_history.db
DB_PATH = Path(__file__).resolve().parent.parent / "logs" / "etl_run_history.db"

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="BRERC ETL Run History")


def _fetch_runs() -> list[dict]:
    """Reads all run-history rows, most recent first. Empty if the job has never run."""
    if not DB_PATH.exists():
        return []

    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT run_number, job_name, job_type, date, load_no, status "
            "FROM runs ORDER BY run_number DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return _fetch_runs()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
