"""Stable, URL-safe species slugs.

The contract requires a kebab-case slug that is unique within a page, and the
front end routes on it, so it must also be stable: a slug that changes between
releases breaks every link anyone saved.

The slug is therefore derived only from the scientific name, which is stable,
and disambiguated by species id only where a name genuinely maps to more than
one species in the release.  Disambiguating everything would give every species
an ugly permanent suffix; disambiguating nothing would produce duplicate slugs
and two species that resolve to each other.
"""

from __future__ import annotations

import re

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
#: Mirrors the speciesSlug pattern in schemas.ts.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(value: str) -> str:
    """Lowercase, collapse anything non-alphanumeric to single hyphens."""
    return _NON_ALPHANUMERIC.sub("-", value.casefold()).strip("-")


def species_slug(scientific_name: str, species_id: str, *, ambiguous: bool) -> str:
    """Build the slug, falling back to the id when the name cannot carry one.

    A scientific name of only punctuation would slugify to an empty string,
    which is not a valid slug — so the species id is used instead.  If neither
    yields anything usable the caller gets an empty string and the response
    fails validation here rather than shipping an unroutable row.
    """
    base = slugify(scientific_name)
    suffix = slugify(species_id)
    if not base:
        return suffix
    if ambiguous and suffix:
        return f"{base}-{suffix}"
    return base
