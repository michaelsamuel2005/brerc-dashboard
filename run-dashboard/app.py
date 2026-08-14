"""
Standalone read-only viewer for the ETL run-history log.

Reads the SQLite database written by api/etl/run_history.py and serves it as
JSON plus a small static HTML page. Deliberately kept separate from api/app
(the public, read-only dashboard API) — this is an internal ops tool with no
front-end or database dependency of its own.

Gated behind a single shared login (DASHBOARD_USERNAME / DASHBOARD_PASSWORD
in .env — see .env.example) backed by a signed session cookie, so only
people with the shared credentials can see the run history.

Run locally:
    uvicorn app:app --reload --port 8100
Then open http://127.0.0.1:8100/
"""

import os
import secrets
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

load_dotenv(Path(__file__).resolve().parent / ".env")

# Same path convention as api/etl/run_history.py: <repo root>/logs/etl_run_history.db
DB_PATH = Path(__file__).resolve().parent.parent / "logs" / "etl_run_history.db"

STATIC_DIR = Path(__file__).resolve().parent / "static"

DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin")

# Falls back to a fresh random key each process start if not set — sessions
# just won't survive a restart, which is fine for this tool and avoids a
# hardcoded fallback secret living in source control.
SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY") or secrets.token_hex(32)

app = FastAPI(title="BRERC ETL Run History")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def _fetch_runs() -> list[dict]:
    """Reads all run-history rows, most recent first. Empty if the job has never run."""
    if not DB_PATH.exists():
        return []

    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row

        # duration_seconds was added after this table's initial release. This
        # connection is read-only (can't ALTER TABLE to migrate it), so fall
        # back to NULL for any older database file that predates the column.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        duration_column = "duration_seconds" if "duration_seconds" in columns else "NULL AS duration_seconds"

        rows = connection.execute(
            f"SELECT run_number, job_name, job_type, date, load_no, status, {duration_column} "
            "FROM runs ORDER BY run_number DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    valid = secrets.compare_digest(username, DASHBOARD_USERNAME) and secrets.compare_digest(
        password, DASHBOARD_PASSWORD
    )

    if not valid:
        return RedirectResponse("/login?error=1", status_code=303)

    request.session["authenticated"] = True
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login")


@app.get("/api/runs")
def list_runs(request: Request) -> list[dict]:
    if not _is_authenticated(request):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    return _fetch_runs()


@app.get("/")
def index(request: Request):
    if not _is_authenticated(request):
        return RedirectResponse("/login")

    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
