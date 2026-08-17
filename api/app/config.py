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
    else [
        # Both hostnames: a browser treats localhost and 127.0.0.1 as distinct
        # origins, so listing only one silently blocks half the dev setups.
        # 5173 is `vite dev`, 4173 is `vite preview` (the build with mocks off).
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
)

#: Caps applied in SQL, on the server.  A caller may ask for less, never more.
#: These bound one request; they are not a substitute for the publication policy.
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "100"))
#: Map squares returned in one distribution response.  Higher than a page size
#: because a map legitimately draws many squares at once.
MAX_CELLS = int(os.getenv("MAX_CELLS", "5000"))
#: Year buckets in the summary.  Bristol's records span roughly a century.
MAX_YEAR_BUCKETS = int(os.getenv("MAX_YEAR_BUCKETS", "300"))
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


# ---------------------------------------------------------------------------
# Approved species assets (photographs + descriptions).  See app/species_assets.py.
# ---------------------------------------------------------------------------

#: Path to the APPROVED assets file.  Unset (the default) means no assets are
#: approved yet: every species publishes as ``fallback-only`` and the front end
#: shows its labelled placeholder.  The file is produced by the curation CLI
#: (api/curation), reviewed by a human, and marked "approved": true — this API
#: never fetches media from third parties at request time.
SPECIES_ASSETS_FILE = os.getenv("SPECIES_ASSETS_FILE", "")

#: Which image licences we may display, as canonical tokens (see
#: curation/species_media.normalise_licence).  Deliberately strict by default:
#:   cc0    public-domain dedication      — no conditions
#:   pd     public domain / no copyright  — no conditions
#:   cc-by  attribution required          — fine for a public site
#: NonCommercial (nc) and NoDerivatives (nd) are never accepted here; add
#: "cc-by-sa" only if BRERC's legal position allows share-alike images.
#: The serving side re-checks this list when loading the approved file, so an
#: approval cannot quietly override the licence policy.
SPECIES_IMAGE_ALLOWED_LICENCES = {
    token.strip().lower()
    for token in os.getenv("SPECIES_IMAGE_ALLOWED_LICENCES", "cc0,pd,cc-by").split(",")
    if token.strip()
}
