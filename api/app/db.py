"""PostgreSQL access — a thin, read-only asyncpg pool.

Every query in this service is parameterised and runs read-only. Two independent
layers enforce that: the database role ``brerc_readonly`` (which is read-only and
cannot see the precise ``occurrences`` table at all), and this module (which
opens read-only transactions and applies a statement timeout). No ORM: the read
paths are explicit SQL so they can be audited at a glance.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from .config import Settings


class Database:
    """Owns the asyncpg connection pool for the app's lifetime."""

    def __init__(
        self,
        settings: Settings,
        dsn: str | None = None,
        *,
        app_name: str = "brerc-dashboard-api",
    ) -> None:
        self._settings = settings
        # Defaults to the public read-only URL; the internal dashboard passes its
        # own (internal-role) DSN. Both connect read-only.
        self._dsn = dsn or settings.public_database_url
        self._app_name = app_name
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return

        async def _init(conn: asyncpg.Connection) -> None:
            # Belt-and-braces: make every session read-only even if the role
            # were ever misconfigured. The precise table is already unreachable
            # to the public role; the internal role is read-only by grant too.
            await conn.execute("SET default_transaction_read_only = on")

        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._settings.db_pool_min_size,
            max_size=self._settings.db_pool_max_size,
            init=_init,
            server_settings={"application_name": self._app_name},
        )

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database pool is not initialised")
        return self._pool

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args, timeout=self._settings.statement_timeout_s)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args, timeout=self._settings.statement_timeout_s)

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args, timeout=self._settings.statement_timeout_s)


# A module-level handle wired up in the app lifespan (see main.py). Using a
# simple holder keeps the FastAPI dependency trivial and testable.
class _DatabaseHolder:
    instance: Database | None = None


def set_database(db: Database) -> None:
    _DatabaseHolder.instance = db


def get_database() -> Database:
    """FastAPI dependency returning the live public Database."""
    if _DatabaseHolder.instance is None:
        raise RuntimeError("Database is not configured")
    return _DatabaseHolder.instance


# Separate holder for the INTERNAL dashboard pool (internal role; may read precise
# data). Only wired up when the internal dashboard is explicitly enabled.
class _InternalDatabaseHolder:
    instance: Database | None = None


def set_internal_database(db: Database | None) -> None:
    _InternalDatabaseHolder.instance = db


def get_internal_database() -> Database:
    """FastAPI dependency returning the live internal Database."""
    if _InternalDatabaseHolder.instance is None:
        raise RuntimeError("Internal database is not configured")
    return _InternalDatabaseHolder.instance
