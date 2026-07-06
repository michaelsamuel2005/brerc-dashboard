"""FastAPI application factory for the BRERC public dashboard API.

Read-only by construction. The app opens a pool to the ``brerc_readonly`` role
(which cannot see precise data), serves GET-only endpoints, and reads exclusively
from the ``public_occurrences`` gate.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Settings, get_settings
from .db import Database, set_database, set_internal_database
from .routers import health, internal, occurrences, species, species_info
from .security import SecurityHeadersMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings)
        await database.connect()
        set_database(database)

        # The internal dashboard opens its OWN pool (internal role) only when
        # fully and safely configured. Off by default (fail-closed).
        internal_db: Database | None = None
        if settings.internal_ready:
            assert settings.internal_database_url is not None  # guaranteed by internal_ready
            internal_db = Database(
                settings,
                dsn=settings.internal_database_url,
                app_name="brerc-internal-api",
            )
            await internal_db.connect()
            set_internal_database(internal_db)

        try:
            yield
        finally:
            await database.disconnect()
            if internal_db is not None:
                await internal_db.disconnect()
                set_internal_database(None)

    app = FastAPI(
        title="BRERC Public Dashboard API",
        version=__version__,
        summary="Read-only species-distribution data for the public dashboard.",
        description=(
            "Serves search, filters, aggregated occurrence counts (the accessible "
            "table equivalent of the map), and cached species information. All data "
            "comes from the generalised, PII-free `public_occurrences` view."
        ),
        # Behind the reverse proxy the API is mounted under /api; set
        # API_ROOT_PATH=/api so the OpenAPI docs generate correct URLs.
        root_path=os.getenv("API_ROOT_PATH", ""),
        lifespan=lifespan,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    app.include_router(health.router)
    app.include_router(species.router)
    app.include_router(occurrences.router)
    app.include_router(species_info.router)

    # Mount the internal data-quality endpoints ONLY when internal mode is fully
    # configured. Each endpoint is additionally protected by an HTTP Basic gate,
    # and this router must never be exposed through the public reverse proxy.
    if settings.internal_ready:
        app.include_router(internal.router)

    return app


app = create_app()
