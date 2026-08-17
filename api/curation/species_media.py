"""Licence-gated species media curation — the fetch-and-vet half of the pipeline.

WHERE THIS CAME FROM
Ported from ``main``'s ``app/species_info.py`` (the B8 proxy), whose licence
gate, source cascade and fail-closed rules are kept intact.  What changed is
WHEN it runs.  The original answered web requests and cached the result; this
codebase's public contract requires every published image to carry an
``approvalReference`` — a recorded human sign-off — so the same machinery now
runs OFFLINE, before deployment:

    python -m curation --contact you@example.org --out candidates.json \
        "Anguis fragilis" "Erithacus rubecula" ...

It writes a CANDIDATES file: entries shaped exactly like the serving contract
(app/species_assets.py) but marked ``"approved": false`` with every
``approvalReference`` empty.  A human reviews each candidate — follows the
sourceUrl, confirms the licence really covers the file, improves the alt text —
fills in the approval references, flips ``approved`` to true, and only then can
the API serve it.  The serving path never calls a third party.

THE RULES (Data_Governance_and_Compliance.md — unchanged from the original)
  1. Sources in order: iNaturalist default photo -> GBIF occurrence media ->
     Wikipedia lead image.  First image to pass the gate wins.
  2. FAIL CLOSED.  No confirmed reusable licence + attribution => no image.
     "Licence not stated" is treated exactly like "all rights reserved".
  3. Only licences in config.SPECIES_IMAGE_ALLOWED_LICENCES are accepted
     (default cc0 / public domain / CC BY — never NonCommercial).
  4. Only the scientific name ever leaves our systems.  No records, locations,
     grid references or recorder names — the name is the only argument.

WHAT THE PORT ADDS (the serving contract asks for more than the original had)
  * licenceUrl — the deed the attribution links to.  Derived from the licence
    version when the source states one; when it does not, the 4.0 deed is used
    and the candidate is flagged ``"licenceUrlAssumed": true`` in curatorNotes
    so the reviewer confirms it against the source before approving.
  * sourceUrl — the page a reader can follow to the original.
  * alt — generated as "Photograph of <name>"; flagged for the reviewer to
    replace with something genuinely descriptive.
  * descriptions are no longer credited inline.  The original appended
    "(Wikipedia, CC BY-SA 4.0 — url)" to the text because its contract had no
    field for the credit; this contract has ``descriptionSource``, so the text
    is clean and the credit is structured.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlparse

# httpx is imported lazily (inside _new_client) so that importing this package
# never requires it — the built wheel is imported by CI without curation's
# dependencies installed, and the serving API never needs it at all.

DEFAULT_TIMEOUT_SECONDS = 4.0
DEFAULT_MIN_INTERVAL_SECONDS = 0.25
DESCRIPTION_MAX_CHARS = 500

#: Canonical token -> base display label.  Versions are appended when known.
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

#: Tokens that never carry a version suffix.
_UNVERSIONED = {"cc0", "pd"}

_VERSIONS = ("1.0", "2.0", "2.5", "3.0", "4.0")


@dataclass(frozen=True)
class CandidateImage:
    url: str
    attributionText: str
    licence: str
    licenceUrl: str
    sourceUrl: str
    alt: str
    licence_url_assumed: bool = False


@dataclass(frozen=True)
class CandidateInfo:
    """Everything curation found for one species.  Empty fields = found nothing
    usable, which is the fail-closed state, exactly as in the original."""

    image: CandidateImage | None = None
    description: str | None = None
    description_source: dict | None = None
    notes: list[str] = field(default_factory=list)


EMPTY = CandidateInfo()


# =============================================================================
# The licence gate — ported verbatim, plus version capture for the deed URL
# =============================================================================


def normalise_licence(raw: str | None) -> str | None:
    """Collapse a source's licence wording into one canonical token, or None.

    None is the load-bearing return value: unrecognised, empty and missing all
    collapse to None, and None is always rejected.  We never guess open.
    """
    if not raw or not isinstance(raw, str):
        return None
    flat = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if not flat:
        return None
    if "cc0" in flat or "publicdomain-zero" in flat:
        return "cc0"
    if "publicdomain" in flat or "public-domain" in flat or "no-known-copyright" in flat:
        return "pd"
    if re.search(r"(^|-)by(-|$)", flat):
        token = "cc-by"  # noqa: S105 - a licence token, not a credential
        if re.search(r"(^|-)nc(-|$)", flat):
            token += "-nc"
        if re.search(r"(^|-)nd(-|$)", flat):
            token += "-nd"
        if re.search(r"(^|-)sa(-|$)", flat):
            token += "-sa"
        return token if token in _CANONICAL_LABELS else None
    return None


def licence_version(raw: str | None) -> str | None:
    """The licence version the source itself stated, or None."""
    if not raw or not isinstance(raw, str):
        return None
    flat = re.sub(r"[^a-z0-9.]+", "-", raw.strip().lower())
    for version in _VERSIONS:
        if re.search(rf"(^|-){re.escape(version)}(-|$)", flat.replace("/", "-")):
            return version
        if version.replace(".", "-") in flat:
            return version
    return None


def licence_is_allowed(raw: str | None, allowed: frozenset[str]) -> bool:
    token = normalise_licence(raw)
    return token is not None and token in allowed


def licence_label_and_url(raw: str) -> tuple[str, str, bool]:
    """(display label, deed URL, assumed?) for a licence that passed the gate.

    A versioned deed is used when the source stated a version.  When it did not,
    the 4.0 deed is used and the third element is True so the CLI can flag the
    candidate for the reviewer — an attribution must link the deed that covers
    the work, and only a human following the sourceUrl can confirm that.
    """
    token = normalise_licence(raw)
    if token is None:
        raise ValueError("licence_label_and_url() called for a licence that failed the gate")
    if token == "cc0":  # noqa: S105 - a licence token, not a credential
        return "CC0", "https://creativecommons.org/publicdomain/zero/1.0/", False
    if token == "pd":  # noqa: S105 - a licence token, not a credential
        return "Public domain", "https://creativecommons.org/publicdomain/mark/1.0/", False
    base = _CANONICAL_LABELS[token]
    path = token.removeprefix("cc-")
    version = licence_version(raw)
    if version is not None:
        return f"{base} {version}", f"https://creativecommons.org/licenses/{path}/{version}/", False
    return base, f"https://creativecommons.org/licenses/{path}/4.0/", True


def vet_image(
    url: str | None,
    raw_licence: str | None,
    attribution: str | None,
    *,
    source_url: str | None,
    species_name: str,
    allowed: frozenset[str],
) -> CandidateImage | None:
    """The gate.  A CandidateImage only if ALL hold, else None (no image):

      * the licence is on the allowed list — we may legally reuse it
      * an attribution string is present   — we can credit the photographer
      * url and sourceUrl are absolute https — anything else fails the contract

    Every source funnels through here: one place to audit, one place to change
    if BRERC's legal position changes.  Unchanged from the original except that
    the serving contract's extra fields (licenceUrl, sourceUrl, alt) are built
    here too, so nothing downstream can construct an image another way.
    """
    if not licence_is_allowed(raw_licence, allowed):
        return None
    credit = clean_text(attribution)
    if not credit:
        return None
    for candidate_url in (url, source_url):
        if not candidate_url or not isinstance(candidate_url, str):
            return None
        parsed = urlparse(candidate_url.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            return None
    label, deed, assumed = licence_label_and_url(raw_licence or "")
    return CandidateImage(
        url=url.strip(),
        attributionText=credit,
        licence=label,
        licenceUrl=deed,
        sourceUrl=source_url.strip(),
        alt=f"Photograph of {species_name}",
        licence_url_assumed=assumed,
    )


# =============================================================================
# Text helpers — ported verbatim
# =============================================================================


def clean_text(value: str | None) -> str:
    """Strip HTML tags and collapse whitespace (Commons sends HTML in Artist)."""
    if not value or not isinstance(value, str):
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", without_tags).strip()


def names_match(candidate: str | None, wanted: str) -> bool:
    """True if a source's taxon name is the one we asked for — a search endpoint
    happily returns near-misses, and a photo of the wrong animal is a
    data-quality bug the licence check would not catch."""
    if not candidate:
        return False

    def tidy(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    return tidy(candidate) == tidy(wanted)


def truncate(text: str, limit: int) -> str:
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
# Outbound HTTP — timeouts, a real User-Agent, and a politeness throttle
# =============================================================================

_throttle_lock = threading.Lock()
_last_call_at = 0.0


class Curator:
    """One curation session: contact details, licence policy, HTTP plumbing.

    ``_new_client`` is the single seam the tests replace, exactly as in the
    original, so the suite never touches the network.
    """

    def __init__(
        self,
        *,
        contact: str,
        allowed_licences: frozenset[str],
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        description_max_chars: int = DESCRIPTION_MAX_CHARS,
    ):
        if not contact or not contact.strip():
            # The upstream APIs ask callers to say who they are and how to be
            # reached; running without that is impolite and gets keys blocked.
            raise ValueError(
                "curation requires a contact (email or project URL) for the User-Agent"
            )
        self.contact = contact.strip()
        self.allowed = allowed_licences
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.description_max_chars = description_max_chars

    # -- plumbing -------------------------------------------------------------

    def _user_agent(self) -> str:
        return f"BRERC-Dashboard-Curation/0.1 (+{self.contact})"

    def _new_client(self):
        import httpx  # lazy: the serving API and the built wheel never need it

        return httpx.Client(
            headers={"User-Agent": self._user_agent(), "Accept": "application/json"},
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
        )

    def _throttle(self) -> None:
        """Keep a polite gap between outbound calls (iNaturalist asks callers to
        stay under about one request a second sustained)."""
        global _last_call_at
        if self.min_interval_seconds <= 0:
            return
        with _throttle_lock:
            wait = self.min_interval_seconds - (time.monotonic() - _last_call_at)
            if wait > 0:
                time.sleep(wait)
            _last_call_at = time.monotonic()

    def _get_json(self, client, url: str, params: dict | None = None) -> dict:
        """GET some JSON.  Any non-200, or anything unparseable, becomes {}."""
        self._throttle()
        response = client.get(url, params=params)
        if response.status_code != 200:
            return {}
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    # -- the three sources, tried in order ------------------------------------

    def _image_from_inaturalist(self, client, name: str) -> CandidateImage | None:
        """iNaturalist: `default_photo` carries `license_code` and `attribution`
        directly, the cleanest source, so it goes first.  A null license_code
        means all rights reserved and is rejected by the gate."""
        payload = self._get_json(
            client,
            "https://api.inaturalist.org/v1/taxa",
            params={"q": name, "rank": "species", "is_active": "true", "per_page": 30},
        )
        for result in payload.get("results") or []:
            if not names_match(result.get("name"), name):
                continue
            photo = result.get("default_photo") or {}
            taxon_id = result.get("id")
            image = vet_image(
                photo.get("medium_url") or photo.get("url"),
                photo.get("license_code"),
                photo.get("attribution"),
                source_url=f"https://www.inaturalist.org/taxa/{taxon_id}" if taxon_id else None,
                species_name=name,
                allowed=self.allowed,
            )
            if image:
                return image
        return None

    def _image_from_gbif(self, client, name: str) -> CandidateImage | None:
        """GBIF: resolve the name strictly (EXACT or nothing), then look for
        occurrences carrying a still image."""
        match = self._get_json(
            client,
            "https://api.gbif.org/v1/species/match",
            params={"name": name, "strict": "true"},
        )
        if match.get("matchType") != "EXACT":
            return None
        taxon_key = match.get("usageKey")
        if not taxon_key:
            return None
        search = self._get_json(
            client,
            "https://api.gbif.org/v1/occurrence/search",
            params={"taxonKey": taxon_key, "mediaType": "StillImage", "limit": 20},
        )
        for occurrence in search.get("results") or []:
            occurrence_key = occurrence.get("key")
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
                    source_url=(
                        f"https://www.gbif.org/occurrence/{occurrence_key}"
                        if occurrence_key
                        else None
                    ),
                    species_name=name,
                    allowed=self.allowed,
                )
                if image:
                    return image
        return None

    def _wikipedia_summary(self, client, name: str) -> dict:
        payload = self._get_json(
            client,
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(name.replace(" ", "_")),
            params={"redirect": "true"},
        )
        return payload if payload.get("type") == "standard" else {}

    @staticmethod
    def _commons_file_title(image_url: str) -> str | None:
        """Recover the Commons file name from an upload.wikimedia.org URL — the
        licence lives on the FILE, not the article."""
        segments = [s for s in urlparse(image_url).path.split("/") if s]
        if not segments:
            return None
        name = segments[-2] if "thumb" in segments and len(segments) >= 2 else segments[-1]
        return unquote(name) or None

    def _image_from_wikipedia(self, client, summary: dict, name: str) -> CandidateImage | None:
        """Wikipedia's lead image.  The article text and the lead image have
        DIFFERENT licences — the article is CC BY-SA, the photo is whatever the
        photographer chose — so the file's own licence is resolved on Commons
        first.  Many Commons photos are CC BY-SA, which the default allow-list
        excludes, so this source legitimately returns None a lot."""
        original = (summary.get("originalimage") or {}).get("source")
        thumbnail = (summary.get("thumbnail") or {}).get("source")
        if not (original or thumbnail):
            return None
        file_title = self._commons_file_title(original or thumbnail)
        if not file_title:
            return None
        page_url = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page")
        metadata = self._get_json(
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
                attribution = clean_text(
                    (extra.get("Attribution") or {}).get("value")
                    or (extra.get("Artist") or {}).get("value")
                )
                # Serve the thumbnail when there is one: same file, same
                # licence, kilobytes instead of megabytes.
                image = vet_image(
                    thumbnail or original,
                    licence,
                    attribution,
                    source_url=page_url,
                    species_name=name,
                    allowed=self.allowed,
                )
                if image:
                    return image
        return None

    def _description_from_wikipedia(self, summary: dict) -> tuple[str, dict] | None:
        """Description text plus its STRUCTURED credit.

        The original appended "(Wikipedia, CC BY-SA 4.0 — url)" to the text
        because its contract had nowhere else to put the credit.  This contract
        has ``descriptionSource``, so the text stays clean and the licence's
        attribution-and-link-back requirement is met by the rendered source
        line.  No link back still means no description — fail closed.
        """
        extract = clean_text(summary.get("extract"))
        page_url = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page")
        if not extract or not page_url:
            return None
        text = truncate(extract, self.description_max_chars)
        return text, {
            "label": "Wikipedia",
            "sourceUrl": page_url,
            "licence": "CC BY-SA 4.0",
            "licenceUrl": "https://creativecommons.org/licenses/by-sa/4.0/",
            "approvalReference": "",
        }

    # -- the cascade ----------------------------------------------------------

    def fetch(self, name: str) -> CandidateInfo:
        """Run the cascade once for one species.

        Worst case is five outbound calls (iNaturalist, two for GBIF, the
        Wikipedia summary, the Commons file info) and it stops as early as it
        can.  Any network failure yields EMPTY — a missing candidate is a
        cosmetic problem; this tool must never fabricate one.
        """
        if not name or not name.strip():
            return EMPTY
        name = name.strip()
        notes: list[str] = []
        try:
            with self._new_client() as client:
                image = self._image_from_inaturalist(client, name)
                if image is None:
                    image = self._image_from_gbif(client, name)
                summary = self._wikipedia_summary(client, name)
                if image is None and summary:
                    image = self._image_from_wikipedia(client, summary, name)
                described = self._description_from_wikipedia(summary) if summary else None
        # Deliberately broad: one species failing to fetch must cost one
        # candidate entry with a note, never the whole run.
        except Exception as error:
            return CandidateInfo(notes=[f"fetch failed: {type(error).__name__}: {error}"])

        if image is not None and image.licence_url_assumed:
            notes.append(
                "licenceUrl assumed 4.0 (source did not state a version) — confirm "
                "against sourceUrl before approving"
            )
        if image is not None:
            notes.append("alt text is generated — replace with a real description")
        description, source = described if described else (None, None)
        return CandidateInfo(
            image=image, description=description, description_source=source, notes=notes
        )
