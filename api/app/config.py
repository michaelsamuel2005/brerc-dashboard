"""
Central configuration for the API (B9).

Everything that changes between your laptop (dev) and BRERC's server (prod) lives
here and is read from environment variables (loaded from the git-ignored api/.env).
Dev -> prod is then just different env values, no code change (decision D-005).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load api/.env (if present) BEFORE reading any setting below.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# "dev" (default) or "prod". Controls whether /docs is exposed and how strict
# CORS is. Set APP_ENV=prod in the production .env.
APP_ENV = os.getenv("APP_ENV", "dev").lower()
IS_PROD = APP_ENV == "prod"

# Database connection. The dev fallback holds no real secret; the real one lives
# in api/.env. In production this is the READ-ONLY role's connection string.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/brerc_ui",
)

# Which browser origins may call the API.
#   * prod: ONLY the sites listed in ALLOWED_ORIGINS (comma-separated) — e.g.
#           the BRERC/council domain the dashboard is embedded in.
#   * dev:  the local front-end dev servers, for convenience.
_origins_env = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = (
    [origin.strip() for origin in _origins_env.split(",") if origin.strip()]
    if IS_PROD
    else ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
)

# Safety valve: the maximum time (milliseconds) any single SQL query may run
# before PostgreSQL cancels it, so a heavy/runaway query can't hang the API.
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "5000"))
