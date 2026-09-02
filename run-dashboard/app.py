"""
Standalone read-only viewer for the authoritative ETL run-history view.

Reads ``serve.etl_job_status`` as a dedicated ``brerc_monitor`` login and
serves it as JSON plus a small static HTML page. Deliberately kept separate
from api/app (the public dashboard API) because this is an authenticated
internal operations surface.

Gated behind a single shared login (DASHBOARD_USERNAME / DASHBOARD_PASSWORD
in .env — see .env.example) backed by a signed session cookie, so only
people with the shared credentials can see the run history.

Run locally:
    uvicorn app:app --reload --port 8100
Then open http://127.0.0.1:8100/
"""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from store import (
    RunHistoryConfigurationError,
    RunHistoryUnavailable,
    fetch_runs,
    validated_dashboard_environment,
)

load_dotenv(Path(__file__).resolve().parent / ".env")

STATIC_DIR = Path(__file__).resolve().parent / "static"

try:
    DASHBOARD_ENV = validated_dashboard_environment()
except RunHistoryConfigurationError as error:
    raise RuntimeError(str(error)) from None

DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "").strip()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "").strip()

# Fail closed: no default credentials, no implicit deployment mode, and no
# ephemeral signing key in production. Local/test processes may use a random
# per-process key, which deliberately invalidates sessions on restart.
if not DASHBOARD_USERNAME or not DASHBOARD_PASSWORD:
    raise RuntimeError(
        "DASHBOARD_USERNAME and DASHBOARD_PASSWORD must both be set in "
        "run-dashboard/.env (see .env.example) — there is no default login."
    )

if DASHBOARD_ENV == "prod" and (
    DASHBOARD_PASSWORD == "CHANGE_ME" or len(DASHBOARD_SECRET_KEY) < 32
):
    raise RuntimeError(
        "production requires a changed dashboard password and a persistent "
        "DASHBOARD_SECRET_KEY of at least 32 characters"
    )

SECRET_KEY = DASHBOARD_SECRET_KEY or secrets.token_hex(32)
IS_PROD = DASHBOARD_ENV == "prod"

app = FastAPI(title="BRERC ETL Run History")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=IS_PROD,
    max_age=12 * 60 * 60,  # 12 hours — re-login once a working day, not "forever"
)


@app.middleware("http")
async def prevent_operational_response_caching(request: Request, call_next):
    """Keep authenticated job metadata out of browser and proxy caches."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/login")
def login_submit(
    request: Request, username: str = Form(...), password: str = Form(...)
):
    valid = secrets.compare_digest(
        username, DASHBOARD_USERNAME
    ) and secrets.compare_digest(password, DASHBOARD_PASSWORD)

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
    try:
        return fetch_runs()
    except (RunHistoryConfigurationError, RunHistoryUnavailable):
        return JSONResponse(
            {"detail": "Authoritative ETL run history is unavailable"}, status_code=503
        )


@app.get("/")
def index(request: Request):
    if not _is_authenticated(request):
        return RedirectResponse("/login")

    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
