"""Stable, URL-safe species slugs derived from approved public fields."""

from __future__ import annotations

import re

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(value: str) -> str:
    """Lowercase and collapse non-alphanumeric runs to one hyphen."""
    return _NON_ALPHANUMERIC.sub("-", value.casefold()).strip("-")


def species_slug(scientific_name: str, species_id: str, *, ambiguous: bool) -> str:
    """Derive a stable slug, adding the public species id only for collisions."""
    base = slugify(scientific_name)
    suffix = slugify(species_id)
    if not base:
        return suffix
    if ambiguous and suffix:
        return f"{base}-{suffix}"
    return base
