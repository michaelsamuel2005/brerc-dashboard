"""Cached species image + description proxy (iNaturalist -> GBIF -> Wikipedia),
fail-closed on image licensing.  TODO (build this).

Learning Guide -> 04-the-api.md (section 5).
Answer Key: brerc-public-dashboard/api/app/services/species_info.py
"""
from __future__ import annotations

_CACHE: dict = {}


def clear_cache() -> None:
    """Empty the in-process cache (used by tests)."""
    _CACHE.clear()


async def get_species_info(*args, **kwargs):
    """TODO: resolve image + description for a species, cached and fail-closed."""
    raise NotImplementedError("TODO: implement get_species_info (Module 4)")
