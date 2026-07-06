"""Shared test fixtures."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services import species_info


@pytest.fixture
def settings() -> Settings:
    """Settings with the default commercial-safe licence allow-list."""
    return Settings(
        PUBLIC_DATABASE_URL="postgresql://brerc_readonly:x@localhost:5432/brerc",
        ALLOWED_IMAGE_LICENCES="cc0,cc-by,public-domain",
    )


@pytest.fixture(autouse=True)
def _clear_species_cache() -> None:
    """Keep the in-process species-info cache from leaking between tests."""
    species_info.clear_cache()
    yield
    species_info.clear_cache()
