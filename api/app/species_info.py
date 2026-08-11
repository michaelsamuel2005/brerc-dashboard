"""
Species image + description proxy (B8, second half).

WHAT THIS IS FOR
A species detail page looks dead without a picture, but BRERC does not hold
photographs. So we borrow them from public natural-history APIs. The catch is
legal, not technical: a photo is somebody's copyrighted work, and we may only
show it if its licence permits reuse AND we credit the photographer. This module
is the single gate that decides "may we show this image, yes or no".

THE RULES IT ENFORCES (Data_Governance_and_Compliance.md section 4)
  1. Try each source in order until a usable image is found:
         iNaturalist default_photo  ->  GBIF occurrence media  ->  Wikipedia
  2. FAIL CLOSED. If we cannot confirm a reusable licence *and* an attribution
     for a given photo, we return no image at all. A missing picture is a
     cosmetic problem; an unlicensed picture is a legal one. "Licence not
     stated" is therefore treated exactly like "all rights reserved".
  3. Only the licences in SPECIES_IMAGE_ALLOWED_LICENCES are accepted. The
     default is CC0 / public domain / CC BY, because the dashboard is public and
     may become commercial, which rules out the NonCommercial (NC) licences.
  4. Cache every answer (url + licence + attribution + when we fetched it) so we
     never hot-call a third party on each page view.

WHAT LEAVES OUR SERVER
Only the scientific name of a species, which is public taxonomy. No records, no
locations, no grid references, no recorder names — nothing from BRERC's data
ever reaches a third party. That is the hard project rule and this module keeps
to it by construction: the name is the only argument it takes.

OFF BY DEFAULT
The proxy stays switched off until BOTH SPECIES_INFO_ENABLED=true and
SPECIES_INFO_CONTACT are set (see api/.env.example). The contact is required
because these APIs ask callers to send a real User-Agent saying who they are and
how to reach them. Until then every endpoint simply reports "no image" — which
is the safe, working, fail-closed state.
"""

import re
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import httpx

from app import config
from app.models import SpeciesImage

# Imported as a MODULE (`from app import config`) rather than by value, so tests
# can override a setting at run time and this code sees the new value.


# =============================================================================
# 1. The result type
# =============================================================================

@dataclass(frozen=True)
class SpeciesInfo:
    """
    Everything this module can tell you about a species. Both fields are
    optional and default to None — that is the fail-closed state.
    """

    image: SpeciesImage | None = None
    description: str | None = None

    @property
    def is_empty(self) -> bool:
        """True when we found nothing usable (used to pick a shorter cache life)."""
        return self.image is None and self.description is None


EMPTY = SpeciesInfo()


# =============================================================================
# 2. The licence gate — the legally load-bearing part
# =============================================================================

# Each source words its licence differently: iNaturalist sends a short code
# ("cc-by-nc"), GBIF sends a URL ("http://creativecommons.org/licenses/by/4.0/"),
# Wikimedia Commons sends a human label ("CC BY-SA 4.0"). We flatten all three
# into one canonical token so there is a single set of rules to reason about.
_CANONICAL_LABELS = {
    "cc0": "CC0",
    "pd": "Public domain",
    "cc-by": "CC BY",
    "cc-by-sa": "CC BY-SA",
    "cc-by-nc": "CC BY-NC",
    "cc-by-nd": "CC BY-ND",
    "cc-by-nc-sa": "CC BY-NC-SA",
    "cc-by-nc-nd": "CC BY-NC-ND",
}


def normalise_licence(raw: str | None) -> str | None:
    """
    Turn whatever a source sent us into one canonical token, or None if we
    cannot tell what the licence is.

    None is the important return value: an unrecognised licence string, an empty
    one, or a missing one all collapse to None, and None is always rejected. We
    never guess that something is open.

    >>> normalise_licence("cc-by-nc")
    'cc-by-nc'
    >>> normalise_licence("http://creativecommons.org/licenses/by/4.0/")
    'cc-by'
    >>> normalise_licence("All rights reserved") is None
    True
    """
    if not raw or not isinstance(raw, str):
        return None

    # Flatten punctuation to single dashes: "CC BY-SA 4.0" -> "cc-by-sa-4-0",
    # ".../licenses/by-nc/4.0/" -> "http-creativecommons-org-licenses-by-nc-4-0".
    flat = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not flat:
        return None

    # CC0 first: its URL (/publicdomain/zero/1.0/) also contains "publicdomain",
    # so the more specific test has to run before the generic one.
    if "cc0" in flat or "publicdomain-zero" in flat:
        return "cc0"
    if "publicdomain" in flat or "public-domain" in flat or "no-known-copyright" in flat:
        return "pd"

    # Any Creative Commons licence with attribution. The word must stand alone as
    # its own token, so a host like "birdsby-org" cannot masquerade as CC BY.
    if re.search(r"(^|-)by(-|$)", flat):
        token = "cc-by"
        # NonCommercial / NoDerivatives / ShareAlike modifiers, in CC's own order.
        if re.search(r"(^|-)nc(-|$)", flat):
            token += "-nc"
        if re.search(r"(^|-)nd(-|$)", flat):
            token += "-nd"
        if re.search(r"(^|-)sa(-|$)", flat):
            token += "-sa"
        return token if token in _CANONICAL_LABELS else None

    return None


def licence_is_allowed(raw: str | None) -> bool:
    """True only if `raw` is a licence we are permitted to display."""
    token = normalise_licence(raw)
    return token is not None and token in config.SPECIES_IMAGE_ALLOWED_LICENCES


def vet_image(
    url: str | None,
    raw_licence: str | None,
    attribution: str | None,
) -> SpeciesImage | None:
    """
    The gate. Returns a SpeciesImage only if ALL of the following hold, and None
    (no image) otherwise:

      * the licence is on the allowed list  — we may legally reuse it
      * an attribution string is present    — we can credit the photographer
      * the url is an absolute HTTPS url    — a plain-http image would be
                                              blocked as mixed content anyway

    Every caller in this module funnels through here, so there is exactly one
    place to audit and exactly one place to change if BRERC's legal position on
    licences changes.
    """
    if not licence_is_allowed(raw_licence):
        return None

    credit = _clean_text(attribution)
    if not credit:
        return None

    if not url or not isinstance(url, str):
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return None

    token = normalise_licence(raw_licence)
    return SpeciesImage(
        url=url.strip(),
        licence=_CANONICAL_LABELS[token],
        attribution=credit,
    )


# =============================================================================
# 3. Small text helpers
# =============================================================================

def _clean_text(value: str | None) -> str:
    """Strip HTML tags and collapse whitespace (Commons sends HTML in `Artist`)."""
    if not value or not isinstance(value, str):
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", without_tags).strip()


def _names_match(candidate: str | None, wanted: str) -> bool:
    """
    True if a source's taxon name is the one we asked for.

    Worth having: a search endpoint happily returns near-misses, and showing a
    photo of the wrong animal is a data-quality bug the licence check would not
    catch.
    """
    if not candidate:
        return False
    tidy = lambda s: re.sub(r"\s+", " ", s).strip().casefold()
    return tidy(candidate) == tidy(wanted)


def _truncate(text: str, limit: int) -> str:
    """Shorten to `limit` characters, preferring a sentence then a word boundary."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence_end = window.rfind(". ")
    if sentence_end >= limit // 2:
        return window[: sentence_end + 1]
    space = window.rfind(" ")
    return (window[:space] if space > 0 else window).rstrip(" ,;:") + "…"


# =============================================================================
# 4. Outbound HTTP — timeouts, a real User-Agent, and a politeness throttle
# =============================================================================

_throttle_lock = threading.Lock()
_last_call_at = 0.0


def _throttle() -> None:
    """
    Keep at least SPECIES_INFO_MIN_INTERVAL_SECONDS between outbound calls.

    iNaturalist asks callers to stay under about one request a second sustained.
    We are nowhere near that in normal use, but a crawler walking every species
    page at once could be, and being throttled or blocked would take the feature
    down for everyone.
    """
    global _last_call_at
    interval = config.SPECIES_INFO_MIN_INTERVAL_SECONDS
    if interval <= 0:
        return
    with _throttle_lock:
        wait = interval - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _user_agent() -> str:
    return f"BRERC-Dashboard/0.1 (+{config.SPECIES_INFO_CONTACT.strip()})"


def _new_client() -> httpx.Client:
    """
    Build the HTTP client. Tests replace this function so the suite never touches
    the network.
    """
    return httpx.Client(
        headers={"User-Agent": _user_agent(), "Accept": "application/json"},
        timeout=httpx.Timeout(config.SPECIES_INFO_TIMEOUT_SECONDS),
        follow_redirects=True,
    )


def _get_json(client: httpx.Client, url: str, params: dict | None = None) -> dict:
    """GET some JSON. Any non-200, or anything unparseable, becomes {}."""
    _throttle()
    response = client.get(url, params=params)
    if response.status_code != 200:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


# =============================================================================
# 5. The three sources, tried in order
# =============================================================================

def _image_from_inaturalist(client: httpx.Client, name: str) -> SpeciesImage | None:
    """
    iNaturalist. Its `default_photo` carries `license_code` and `attribution`
    directly, which makes it the cleanest source — so it goes first.
    A null `license_code` means all rights reserved, and is rejected.
    """
    # per_page is generous because `q` is a fuzzy text search: "Bufo bufo" really
    # returns ~500 hits, with the exact match not necessarily first (the top hit
    # for that query is an American toad). We take one page and pick out the exact
    # name ourselves rather than trusting the ranking.
    payload = _get_json(
        client,
        "https://api.inaturalist.org/v1/taxa",
        params={"q": name, "rank": "species", "is_active": "true", "per_page": 30},
    )
    for result in payload.get("results") or []:
        if not _names_match(result.get("name"), name):
            continue
        photo = result.get("default_photo") or {}
        image = vet_image(
            photo.get("medium_url") or photo.get("url"),
            photo.get("license_code"),
            photo.get("attribution"),
        )
        if image:
            return image
    return None


def _image_from_gbif(client: httpx.Client, name: str) -> SpeciesImage | None:
    """
    GBIF. Two calls: resolve the name to a taxon key, then look for occurrences
    that have a still image. `strict=true` means GBIF answers EXACT or nothing,
    so we cannot silently end up on a different taxon.
    """
    match = _get_json(
        client,
        "https://api.gbif.org/v1/species/match",
        params={"name": name, "strict": "true"},
    )
    if match.get("matchType") != "EXACT":
        return None
    taxon_key = match.get("usageKey")
    if not taxon_key:
        return None

    search = _get_json(
        client,
        "https://api.gbif.org/v1/occurrence/search",
        params={"taxonKey": taxon_key, "mediaType": "StillImage", "limit": 20},
    )
    for occurrence in search.get("results") or []:
        for media in occurrence.get("media") or []:
            if (media.get("type") or "StillImage") != "StillImage":
                continue
            image = vet_image(
                media.get("identifier"),
                media.get("license") or occurrence.get("license"),
                media.get("rightsHolder")
                or media.get("creator")
                or occurrence.get("rightsHolder")
                or occurrence.get("publisher"),
            )
            if image:
                return image
    return None


def _wikipedia_summary(client: httpx.Client, name: str) -> dict:
    """
    Wikipedia's REST summary for a scientific name. Used for the description and,
    as a last resort, the image. `type == "standard"` filters out disambiguation
    and "no such page" responses.
    """
    payload = _get_json(
        client,
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(name.replace(' ', '_'))}",
        params={"redirect": "true"},
    )
    return payload if payload.get("type") == "standard" else {}


def _commons_file_title(image_url: str) -> str | None:
    """
    Recover the Commons file name from an upload.wikimedia.org url, because the
    licence lives on the *file*, not on the article.

      .../commons/a/a5/Robin.jpg                       -> Robin.jpg
      .../commons/thumb/a/a5/Robin.jpg/640px-Robin.jpg  -> Robin.jpg
    """
    segments = [s for s in urlparse(image_url).path.split("/") if s]
    if not segments:
        return None
    # For a thumbnail the real file name is the segment before the "640px-..." one.
    name = segments[-2] if "thumb" in segments and len(segments) >= 2 else segments[-1]
    return unquote(name) or None


def _image_from_wikipedia(
    client: httpx.Client, summary: dict
) -> SpeciesImage | None:
    """
    Wikipedia's lead image. Note that the article text and the lead image have
    DIFFERENT licences — the article is CC BY-SA, the photo is whatever the
    photographer chose — so we must resolve the file's own licence on Commons
    before we may display it. Many Commons photos are CC BY-SA, which the default
    allow-list excludes, so this source legitimately returns None a lot.
    """
    original = (summary.get("originalimage") or {}).get("source")
    thumbnail = (summary.get("thumbnail") or {}).get("source")
    if not (original or thumbnail):
        return None

    file_title = _commons_file_title(original or thumbnail)
    if not file_title:
        return None

    metadata = _get_json(
        client,
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "imageinfo",
            "iiprop": "extmetadata",
            "titles": f"File:{file_title}",
        },
    )
    for page in (metadata.get("query") or {}).get("pages") or []:
        for info in page.get("imageinfo") or []:
            extra = info.get("extmetadata") or {}
            licence = (extra.get("LicenseShortName") or {}).get("value")
            attribution = _clean_text(
                (extra.get("Attribution") or {}).get("value")
                or (extra.get("Artist") or {}).get("value")
            )
            # Serve the thumbnail when we have one: it is the same file under the
            # same licence, but kilobytes instead of megabytes.
            image = vet_image(thumbnail or original, licence, attribution)
            if image:
                return image
    return None


def _description_from_wikipedia(summary: dict) -> str | None:
    """
    A short plain-text description.

    Wikipedia text is CC BY-SA, which requires attribution and a link back. The
    agreed API contract has no separate field for that, so the credit is appended
    to the sentence itself — visible to the reader, which is what the licence
    actually asks for. (If Michael can add a `descriptionSource` field later,
    move it there; see the note in api/README.md.)
    """
    extract = _clean_text(summary.get("extract"))
    page_url = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page")
    if not extract or not page_url:
        # No link back means we cannot satisfy the licence — so, no description.
        return None
    text = _truncate(extract, config.SPECIES_INFO_DESCRIPTION_MAX_CHARS)
    return f"{text} (Wikipedia, CC BY-SA 4.0 — {page_url})"


def _fetch(name: str) -> SpeciesInfo:
    """
    Run the cascade once for one species. Called only on a cache miss.

    Worst case is five outbound calls (iNaturalist, two for GBIF, Wikipedia
    summary, Commons file info) and it stops as early as it can.
    """
    with _new_client() as client:
        image = _image_from_inaturalist(client, name)
        if image is None:
            image = _image_from_gbif(client, name)

        # Wikipedia is fetched either way, because the description comes from it.
        summary = _wikipedia_summary(client, name)
        if image is None and summary:
            image = _image_from_wikipedia(client, summary)

        description = _description_from_wikipedia(summary) if summary else None

    return SpeciesInfo(image=image, description=description)


# =============================================================================
# 6. Cache — in memory, backed by a small SQLite file
# =============================================================================
# Two layers because the API runs as a READ-ONLY database role and so cannot
# cache anything in PostgreSQL:
#   * memory  — instant, but per worker process and lost on restart
#   * sqlite  — shared by every worker and survives a restart, which is what
#               "never hot-call third parties uncached" really requires
# If the SQLite file cannot be opened (read-only filesystem, say) we log nothing
# and quietly carry on with memory only: a slower cache is not worth a 500.

_MEMORY_MAX_ENTRIES = 2000
_memory_lock = threading.Lock()
_memory: "OrderedDict[str, tuple[float, SpeciesInfo]]" = OrderedDict()

_sqlite_lock = threading.Lock()
_sqlite_unavailable = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS species_info (
    scientific_name   TEXT PRIMARY KEY,
    image_url         TEXT,
    image_licence     TEXT,
    image_attribution TEXT,
    description       TEXT,
    fetched_at        REAL NOT NULL
);
"""


def _cache_key(name: str) -> str:
    """
    The cache key includes the allowed-licence list, not just the species name.

    That matters: a cached "no usable image" is only true *for the licence rules
    in force when we looked*. Without the licence list in the key, adding
    cc-by-sa to SPECIES_IMAGE_ALLOWED_LICENCES would appear to do nothing for a
    month, because every species would still be answered from a cache built under
    the stricter rule. Folding the rules into the key makes a policy change
    re-fetch automatically.
    """
    tidy_name = re.sub(r"\s+", " ", name).strip().casefold()
    policy = ",".join(sorted(config.SPECIES_IMAGE_ALLOWED_LICENCES))
    return f"{policy}|{tidy_name}"


def _entry_is_fresh(fetched_at: float, info: SpeciesInfo) -> bool:
    """
    Is a cached answer still usable?

    A found answer is kept for a long time (photos rarely change). An empty one —
    nothing usable found, or the source was down — is kept only briefly, so a
    species does not stay picture-less for a month because of one bad afternoon.
    """
    age = time.time() - fetched_at
    if info.is_empty:
        return age < config.SPECIES_INFO_MISS_TTL_MINUTES * 60
    return age < config.SPECIES_INFO_CACHE_TTL_DAYS * 86400


def _sqlite_connect() -> sqlite3.Connection | None:
    global _sqlite_unavailable
    if _sqlite_unavailable:
        return None
    try:
        path = Path(config.SPECIES_INFO_CACHE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=2.0)
        connection.execute(_SCHEMA)
        return connection
    except Exception:
        # One failure is enough — stop retrying on every request.
        _sqlite_unavailable = True
        return None


def _row_to_info(row: tuple) -> SpeciesInfo:
    url, licence, attribution, description = row
    image = None
    if url and licence and attribution:
        image = SpeciesImage(url=url, licence=licence, attribution=attribution)
    return SpeciesInfo(image=image, description=description)


def _cache_get(name: str) -> SpeciesInfo | None:
    """Look in memory, then in SQLite. None means "not cached, or stale"."""
    key = _cache_key(name)

    with _memory_lock:
        hit = _memory.get(key)
        if hit is not None:
            fetched_at, info = hit
            if _entry_is_fresh(fetched_at, info):
                _memory.move_to_end(key)
                return info
            del _memory[key]

    connection = _sqlite_connect()
    if connection is None:
        return None
    try:
        with _sqlite_lock, connection:
            row = connection.execute(
                """
                SELECT image_url, image_licence, image_attribution, description,
                       fetched_at
                FROM species_info WHERE scientific_name = ?;
                """,
                (key,),
            ).fetchone()
    except Exception:
        return None
    finally:
        connection.close()

    if row is None:
        return None
    info = _row_to_info(row[:4])
    if not _entry_is_fresh(row[4], info):
        return None
    _memory_put(key, time.time(), info)
    return info


def _memory_put(key: str, fetched_at: float, info: SpeciesInfo) -> None:
    with _memory_lock:
        _memory[key] = (fetched_at, info)
        _memory.move_to_end(key)
        while len(_memory) > _MEMORY_MAX_ENTRIES:
            _memory.popitem(last=False)  # evict the least recently used


def _cache_put(name: str, info: SpeciesInfo) -> None:
    key = _cache_key(name)
    now = time.time()
    _memory_put(key, now, info)

    connection = _sqlite_connect()
    if connection is None:
        return
    try:
        with _sqlite_lock, connection:
            connection.execute(
                """
                INSERT INTO species_info (scientific_name, image_url,
                    image_licence, image_attribution, description, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scientific_name) DO UPDATE SET
                    image_url = excluded.image_url,
                    image_licence = excluded.image_licence,
                    image_attribution = excluded.image_attribution,
                    description = excluded.description,
                    fetched_at = excluded.fetched_at;
                """,
                (
                    key,
                    info.image.url if info.image else None,
                    info.image.licence if info.image else None,
                    info.image.attribution if info.image else None,
                    info.description,
                    now,
                ),
            )
    except Exception:
        pass
    finally:
        connection.close()


def reset_cache() -> None:
    """
    Forget everything cached — both layers, memory and the SQLite file.

    Used by the tests to keep each case isolated. Also the thing to call (or just
    delete the cache file) if you ever need to force a full re-fetch.
    """
    global _sqlite_unavailable
    with _memory_lock:
        _memory.clear()
    _sqlite_unavailable = False

    connection = _sqlite_connect()
    if connection is None:
        return
    try:
        with _sqlite_lock, connection:
            connection.execute("DELETE FROM species_info;")
    except Exception:
        pass
    finally:
        connection.close()


# =============================================================================
# 7. What the routers call
# =============================================================================

def inactive_reason() -> str | None:
    """
    Why the proxy is switched off, or None if it is on.

    Logged once at startup (see app/main.py) so a deployment that meant to serve
    images but is misconfigured says so in its logs, instead of quietly serving
    none. It is deliberately NOT part of /api/health: that response shape is
    locked by the front-end contract.
    """
    if not config.SPECIES_INFO_ENABLED:
        return "SPECIES_INFO_ENABLED is not true"
    if not config.SPECIES_INFO_CONTACT.strip():
        return "SPECIES_INFO_CONTACT is not set (these APIs require a real User-Agent)"
    if not config.SPECIES_IMAGE_ALLOWED_LICENCES:
        return "SPECIES_IMAGE_ALLOWED_LICENCES is empty, so no image could ever pass"
    return None


def get_species_info(scientific_name: str) -> SpeciesInfo:
    """
    Image + description for one species. Never raises and never blocks a page:
    if the proxy is off, the sources are down, or nothing passes the licence
    gate, you get empty fields and the endpoint still returns 200.
    """
    if not scientific_name or not scientific_name.strip():
        return EMPTY
    if inactive_reason() is not None:
        return EMPTY

    cached = _cache_get(scientific_name)
    if cached is not None:
        return cached

    try:
        info = _fetch(scientific_name)
    except Exception:
        # Network error, timeout, unexpected payload shape — all the same to a
        # caller. Cache the empty result briefly so one outage does not turn into
        # one outbound attempt per page view.
        info = EMPTY

    _cache_put(scientific_name, info)
    return info


def get_cached_species_info(scientific_name: str) -> SpeciesInfo | None:
    """Cache-only lookup. Never makes a network call. None means "not cached"."""
    if not scientific_name or inactive_reason() is not None:
        return None
    return _cache_get(scientific_name)


def names_with_cached_image(names: list[str]) -> set[str]:
    """
    Of these species, which already have a licensed image ready to serve?

    Used by the species LIST to answer `hasImage` honestly. It is cache-only and
    batched into one SQLite query on purpose: fetching twenty species from three
    external APIs to render one page of results would be unacceptable.
    Returns the names as they were passed in.
    """
    if not names or inactive_reason() is not None:
        return set()

    by_key = {_cache_key(name): name for name in names if name}
    found: set[str] = set()

    with _memory_lock:
        for key, original in by_key.items():
            hit = _memory.get(key)
            if hit and _entry_is_fresh(*hit) and hit[1].image is not None:
                found.add(original)

    remaining = [key for key in by_key if by_key[key] not in found]
    if not remaining:
        return found

    connection = _sqlite_connect()
    if connection is None:
        return found
    try:
        placeholders = ",".join("?" for _ in remaining)
        with _sqlite_lock, connection:
            rows = connection.execute(
                f"""
                SELECT scientific_name, image_url, image_licence,
                       image_attribution, description, fetched_at
                FROM species_info
                WHERE scientific_name IN ({placeholders})
                  AND image_url IS NOT NULL;
                """,
                remaining,
            ).fetchall()
    except Exception:
        return found
    finally:
        connection.close()

    for row in rows:
        info = _row_to_info(row[1:5])
        if info.image is not None and _entry_is_fresh(row[5], info):
            found.add(by_key[row[0]])
    return found
