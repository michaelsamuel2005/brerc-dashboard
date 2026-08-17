"""The approved species-assets registry — what lets a species page show a photograph.

WHERE THIS FITS
The web contract (web/src/lib/api/schemas.ts) publishes species media under an
``imagePublication`` mode: ``fallback-only`` forbids an image, ``approved-assets``
requires one, and every published image or description source must carry an
``approvalReference`` — a human sign-off, recorded, that says who approved this
exact asset for public display.  That rules out serving whatever a third-party
API answers at request time.  Instead:

    curation CLI (api/curation) -> candidates file -> HUMAN REVIEW -> approved
    assets file -> this module validates and serves it

The serving path therefore makes NO outbound calls, ever.  A deployment without
an assets file behaves exactly as before this module existed: every species is
``fallback-only`` and the front end shows its labelled placeholder.

FAIL LOUD, NOT HALF-OPEN
The assets file is an approved artefact.  If it is malformed — an http URL, a
licence off the allow-list, a missing attribution or approval reference — the
correct response is to refuse to start, naming the entry, rather than silently
dropping some species and serving others.  Silent partial service would make a
review mistake invisible; refusing makes it a deploy failure someone must fix.
(Data_Governance_and_Compliance.md: image licensing fails closed.)

The one lenient case is the file being absent or the setting unset: that is the
ordinary "no assets approved yet" state, and the registry is simply inactive.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app import config

# Canonical licence tokens the dashboard may display, and the deed each label
# links to.  The serving side re-checks the licence against the allow-list even
# though curation already did: approval cannot override the legal position.
# Versioned labels are listed explicitly because an attribution must link the
# deed that actually covers the work, not the nearest modern one.
LICENCE_URLS: dict[str, str] = {
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public domain": "https://creativecommons.org/publicdomain/mark/1.0/",
    "CC BY": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC BY 2.5": "https://creativecommons.org/licenses/by/2.5/",
    "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
    "CC BY-SA": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-SA 3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
    "CC BY-SA 2.0": "https://creativecommons.org/licenses/by-sa/2.0/",
}

#: Label -> allow-list token ("CC BY 4.0" -> "cc-by").  Built from the labels
#: above so the two tables cannot drift apart.
_LABEL_TOKENS: dict[str, str] = {
    label: (
        "cc0"
        if label == "CC0"
        else "pd"
        if label == "Public domain"
        else re.sub(r"\s+\d+\.\d+$", "", label).lower().replace(" ", "-").replace("cc-", "cc-", 1)
    )
    for label in LICENCE_URLS
}
# The comprehension above yields e.g. "cc-by" / "cc-by-sa"; make that explicit
# for the two specials so a reader does not have to run it in their head.
_LABEL_TOKENS["CC0"] = "cc0"
_LABEL_TOKENS["Public domain"] = "pd"


class SpeciesAssetsError(ValueError):
    """A malformed approved-assets file.  Raised at load, aborts startup."""


@dataclass(frozen=True)
class ApprovedImage:
    url: str
    attributionText: str
    licence: str
    licenceUrl: str
    sourceUrl: str
    approvalReference: str
    alt: str


@dataclass(frozen=True)
class ApprovedDescriptionSource:
    label: str
    approvalReference: str
    sourceUrl: str | None = None
    licence: str | None = None
    licenceUrl: str | None = None


@dataclass(frozen=True)
class ApprovedAssets:
    scientificName: str
    image: ApprovedImage | None
    description: str | None
    descriptionSource: ApprovedDescriptionSource | None


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def _require_text(entry_name: str, obj: dict, field: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SpeciesAssetsError(f"species asset '{entry_name}': '{field}' must be non-empty text")
    return value.strip()


def _require_https(entry_name: str, obj: dict, field: str) -> str:
    value = _require_text(entry_name, obj, field)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': '{field}' must be an absolute https URL"
        )
    return value


def _parse_image(entry_name: str, obj: dict) -> ApprovedImage:
    unknown = set(obj) - {
        "url",
        "attributionText",
        "licence",
        "licenceUrl",
        "sourceUrl",
        "approvalReference",
        "alt",
    }
    if unknown:
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': unknown image field(s) {sorted(unknown)}"
        )
    licence = _require_text(entry_name, obj, "licence")
    token = _LABEL_TOKENS.get(licence)
    if token is None:
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': licence '{licence}' is not a recognised label; "
            f"recognised: {sorted(LICENCE_URLS)}"
        )
    if token not in config.SPECIES_IMAGE_ALLOWED_LICENCES:
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': licence '{licence}' is not on the allowed list "
            f"({sorted(config.SPECIES_IMAGE_ALLOWED_LICENCES)}). Approval cannot override "
            "the licence policy; change SPECIES_IMAGE_ALLOWED_LICENCES deliberately if the "
            "legal position has changed."
        )
    return ApprovedImage(
        url=_require_https(entry_name, obj, "url"),
        attributionText=_require_text(entry_name, obj, "attributionText"),
        licence=licence,
        licenceUrl=_require_https(entry_name, obj, "licenceUrl"),
        sourceUrl=_require_https(entry_name, obj, "sourceUrl"),
        approvalReference=_require_text(entry_name, obj, "approvalReference"),
        alt=_require_text(entry_name, obj, "alt"),
    )


def _parse_description_source(entry_name: str, obj: dict) -> ApprovedDescriptionSource:
    unknown = set(obj) - {"label", "sourceUrl", "licence", "licenceUrl", "approvalReference"}
    if unknown:
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': unknown descriptionSource field(s) {sorted(unknown)}"
        )
    licence = obj.get("licence")
    licence_url = obj.get("licenceUrl")
    if licence_url is not None and licence is None:
        # Mirrors the web contract's rule: a licence URL without licence text
        # would render a bare link with nothing to call it.
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': descriptionSource.licenceUrl requires "
            "descriptionSource.licence"
        )
    return ApprovedDescriptionSource(
        label=_require_text(entry_name, obj, "label"),
        approvalReference=_require_text(entry_name, obj, "approvalReference"),
        sourceUrl=_require_https(entry_name, obj, "sourceUrl") if "sourceUrl" in obj else None,
        licence=_require_text(entry_name, obj, "licence") if licence is not None else None,
        licenceUrl=_require_https(entry_name, obj, "licenceUrl")
        if licence_url is not None
        else None,
    )


def _parse_entry(obj: object) -> ApprovedAssets:
    if not isinstance(obj, dict):
        raise SpeciesAssetsError("every species asset entry must be an object")
    name = obj.get("scientificName")
    if not isinstance(name, str) or not name.strip():
        raise SpeciesAssetsError("species asset entry without a scientificName")
    entry_name = name.strip()
    # curatorNotes is written by the curation CLI for the reviewer's benefit
    # (licence-version assumptions, generated alt text).  It is tolerated and
    # ignored here so an approved file need not be stripped of its audit trail.
    unknown = set(obj) - {
        "scientificName",
        "image",
        "description",
        "descriptionSource",
        "curatorNotes",
    }
    if unknown:
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': unknown field(s) {sorted(unknown)}"
        )

    description = obj.get("description")
    if description is not None and (not isinstance(description, str) or not description.strip()):
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': description must be non-empty text when present"
        )
    source = obj.get("descriptionSource")
    # The web contract publishes these strictly together; hold the file to the
    # same rule so an entry cannot pass here and fail in every browser.
    if (description is None) != (source is None):
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': description and descriptionSource must be "
            "provided together"
        )

    image_obj = obj.get("image")
    image = _parse_image(entry_name, image_obj) if image_obj is not None else None
    parsed_source = _parse_description_source(entry_name, source) if source is not None else None
    if image is None and description is None:
        raise SpeciesAssetsError(
            f"species asset '{entry_name}': entry carries neither an image nor a description"
        )
    return ApprovedAssets(
        scientificName=entry_name,
        image=image,
        description=description.strip() if description else None,
        descriptionSource=parsed_source,
    )


class SpeciesAssetsRegistry:
    """All approved assets, keyed by normalised scientific name."""

    def __init__(self, entries: dict[str, ApprovedAssets]):
        self._entries = entries

    @property
    def active(self) -> bool:
        return bool(self._entries)

    def for_name(self, scientific_name: str) -> ApprovedAssets | None:
        return self._entries.get(_key(scientific_name))

    def has_image(self, scientific_name: str) -> bool:
        assets = self.for_name(scientific_name)
        return assets is not None and assets.image is not None


INACTIVE = SpeciesAssetsRegistry({})


def load_registry(path: str | None) -> SpeciesAssetsRegistry:
    """Parse and validate an approved-assets file.

    Absent path or file -> the inactive registry (the ordinary state).
    Present but malformed -> SpeciesAssetsError, which must abort startup.
    """
    if not path or not path.strip():
        return INACTIVE
    file_path = Path(path.strip())
    if not file_path.exists():
        return INACTIVE
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SpeciesAssetsError(f"cannot read species assets file {file_path}: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("species"), list):
        raise SpeciesAssetsError('species assets file must be an object with a "species" array')
    if payload.get("approved") is not True:
        # The curation CLI writes candidates with approved=false.  Serving a
        # candidates file directly would skip the human step entirely.
        raise SpeciesAssetsError(
            'species assets file is not marked "approved": true — a candidates file '
            "must be reviewed and approved before it can be served"
        )
    entries: dict[str, ApprovedAssets] = {}
    for item in payload["species"]:
        parsed = _parse_entry(item)
        key = _key(parsed.scientificName)
        if key in entries:
            raise SpeciesAssetsError(f"species asset '{parsed.scientificName}': duplicate entry")
        entries[key] = parsed
    return SpeciesAssetsRegistry(entries)


_lock = threading.Lock()
_registry: SpeciesAssetsRegistry | None = None


def registry() -> SpeciesAssetsRegistry:
    """The process-wide registry, loaded once from config.SPECIES_ASSETS_FILE."""
    global _registry
    with _lock:
        if _registry is None:
            _registry = load_registry(config.SPECIES_ASSETS_FILE)
        return _registry


def reset_registry() -> None:
    """Testing seam: forget the cached registry so a test can point elsewhere."""
    global _registry
    with _lock:
        _registry = None
