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


# ---------------------------------------------------------------------------
# ROW CAPS — the most rows any single request may ever receive
# ---------------------------------------------------------------------------
# FOR THE MAINTAINER: these are the limits that stop one request from pulling
# the whole database out through the API. Every endpoint that returns a list
# applies one of them, in SQL, on the server. A caller can ask for less, but
# never for more — asking for 10,000 rows still gets you at most the cap.
#
# This matters for two reasons:
#   1. Performance — one huge query can't tie up the database for everyone.
#   2. Policy — the public dashboard is for looking things up, not for
#      downloading BRERC's dataset. There is deliberately no bulk export.
#
# Raise a number here if the dashboard genuinely needs more; that is the only
# place to change it.

# Biggest page any list endpoint will return (/api/species, /api/records).
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "100"))

# Biggest number of map squares /api/distribution/cells will return at once.
# Higher than a page size because the map legitimately draws many squares.
MAX_CELLS = int(os.getenv("MAX_CELLS", "5000"))

# Caps on the two grouped lists inside /api/summary. Bristol's records span
# roughly a century, and there are a few dozen species groups, so these are
# generous — they exist to bound the response, not to trim real data.
MAX_YEAR_BUCKETS = int(os.getenv("MAX_YEAR_BUCKETS", "300"))
MAX_GROUPS = int(os.getenv("MAX_GROUPS", "50"))


# ---------------------------------------------------------------------------
# Species image + description proxy (B8). See app/species_info.py.
# ---------------------------------------------------------------------------

def _env_flag(name: str, default: bool = False) -> bool:
    """Read a true/false environment variable ("true", "1", "yes" all mean true)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


# OFF by default. Fetching pictures from third parties is the one thing this API
# does that reaches outside BRERC's own systems, so it has to be switched on
# deliberately rather than by accident.
SPECIES_INFO_ENABLED = _env_flag("SPECIES_INFO_ENABLED", False)

# Who to contact about our API traffic — an email address or project url. These
# APIs ask callers to identify themselves in the User-Agent header, and the proxy
# refuses to run without it.
SPECIES_INFO_CONTACT = os.getenv("SPECIES_INFO_CONTACT", "")

# Which image licences we may display, as canonical tokens (see
# species_info.normalise_licence). The default is deliberately strict:
#   cc0    public-domain dedication      — no conditions
#   pd     public domain / no copyright  — no conditions
#   cc-by  attribution only              — fine for a site that may go commercial
# NOT included by default: anything NonCommercial (nc) or NoDerivatives (nd), and
# cc-by-sa. Add "cc-by-sa" here if BRERC's legal position allows share-alike
# images — that one line is the whole change.
SPECIES_IMAGE_ALLOWED_LICENCES = {
    token.strip().lower()
    for token in os.getenv("SPECIES_IMAGE_ALLOWED_LICENCES", "cc0,pd,cc-by").split(",")
    if token.strip()
}

# How long to wait on any single third-party request before giving up.
SPECIES_INFO_TIMEOUT_SECONDS = float(os.getenv("SPECIES_INFO_TIMEOUT_SECONDS", "4"))

# Cache lifetimes: a long one for answers we found, a short one for "found
# nothing" so an outage or a newly-uploaded photo isn't missed for a month.
SPECIES_INFO_CACHE_TTL_DAYS = float(os.getenv("SPECIES_INFO_CACHE_TTL_DAYS", "30"))
SPECIES_INFO_MISS_TTL_MINUTES = float(os.getenv("SPECIES_INFO_MISS_TTL_MINUTES", "360"))

# Where the cache file lives. Defaults to api/.cache/ (git-ignored); in Docker
# this resolves to /app/.cache, which docker-compose keeps on a named volume so
# the cache survives a restart.
SPECIES_INFO_CACHE_PATH = os.getenv(
    "SPECIES_INFO_CACHE_PATH",
    str(Path(__file__).resolve().parent.parent / ".cache" / "species_info.sqlite3"),
)

# Minimum gap between outbound calls, so we stay a polite API client.
SPECIES_INFO_MIN_INTERVAL_SECONDS = float(
    os.getenv("SPECIES_INFO_MIN_INTERVAL_SECONDS", "0.25")
)

# Cap on the description length (it is a teaser, not an article).
SPECIES_INFO_DESCRIPTION_MAX_CHARS = int(
    os.getenv("SPECIES_INFO_DESCRIPTION_MAX_CHARS", "600")
)
