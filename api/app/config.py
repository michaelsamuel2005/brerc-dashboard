"""Deployment configuration for the read-only public API.

Everything that differs between a developer's machine and BRERC's server is an
environment variable, so promoting dev to production is a credentials change and
nothing else (decision D-005).  No secret has a default here: an unset
``DATABASE_URL`` in production is a startup failure rather than a silent
fallback to a local database that happens to exist.
"""

from __future__ import annotations

import os

APP_ENV = os.getenv("APP_ENV", "dev").strip().lower()
IS_PROD = APP_ENV == "prod"

#: Read-only role connection string.  Deliberately has no default in production.
DATABASE_URL = os.getenv("DATABASE_URL", "")

#: Browser origins permitted to call the API.  In production this is explicit;
#: an empty list means no browser may call it, which is the safe failure.
_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [origin.strip() for origin in _origins.split(",") if origin.strip()]
    if IS_PROD
    else ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"]
)

#: Caps applied in SQL, on the server.  A caller may ask for less, never more.
#: These bound one request; they are not a substitute for the publication policy.
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "100"))
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "5000"))

#: Published alongside the data so a reader can see what generalisation means.
#: The tiers themselves are measured from the released data, never asserted here.
SENSITIVITY_POLICY_NOTE = os.getenv(
    "SENSITIVITY_POLICY_NOTE",
    "Locations of protected species are generalised before publication. "
    "Precise coordinates are never released.",
)


def require_database_url() -> str:
    """Return the connection string, or fail loudly rather than guessing one."""
    if DATABASE_URL:
        return DATABASE_URL
    if IS_PROD:
        raise RuntimeError("DATABASE_URL is not set; refusing to start in production")
    return "postgresql:///brerc_ui_integration"
