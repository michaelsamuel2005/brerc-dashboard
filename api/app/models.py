"""Response shapes, matched field-for-field to the front end's Zod schemas.

``web/src/lib/api/schemas.ts`` is the contract and every schema there is
``.strict()``, so an extra key is a rejected response rather than a tolerated
one.  These models therefore mirror it exactly; where the front end expects a
key to be absent unless a capability is enabled, the router omits it rather than
sending a placeholder.

Nothing here carries recorder identity, precise coordinates, eastings/northings,
free-text comments or any sensitivity marker.  Those never reach this layer:
the ``serve.*`` views do not expose them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Reject unknown fields on the way in as well as out."""

    model_config = ConfigDict(extra="forbid")


class Health(StrictModel):
    status: str
    version: str


class PublicationFields(StrictModel):
    """Mirrors the release's own capability flags, verbatim."""

    abundance: bool
    place: bool
    recordType: bool
    verification: bool


class RecordPublication(StrictModel):
    mode: str  # "aggregates-only" | "individual-records"
    fields: PublicationFields


class RecordRow(StrictModel):
    """One published record.

    ``abundance``, ``recordType`` and ``verified`` are omitted entirely when the
    release does not publish them — the front end treats a present key as a
    claim that the field is available.  ``verified`` is the raw source verdict as
    text, not a boolean: the client normalises it through the same four-way
    classifier as the ETL, and collapsing "rejected" and "not yet checked" into
    one false value was measured to produce false accepts.
    """

    id: str
    scientificName: str
    commonName: str | None
    gridRef: str
    precisionMetres: int
    place: str | None
    year: int
    source: str
    abundance: str | None = None
    recordType: str | None = None
    verified: str | None = None


class RecordPage(StrictModel):
    publication: RecordPublication
    items: list[RecordRow]
    page: int
    pageSize: int
    total: int


class Attribution(StrictModel):
    label: str
    url: str
    licence: str


class SensitivityPolicy(StrictModel):
    """``generalisationTiersMetres`` is measured from the released data.

    Publishing the tiers discloses which resolutions exist, not which taxon sits
    at which; the squares are already measurable on the map and generalisation is
    irreversible server-side.  Deriving them from what was actually published
    means this can never claim a tier the release did not use.
    """

    generalisationTiersMetres: list[int]
    appliesToProtectedTaxa: bool = Field(default=True)
    note: str


class Provenance(StrictModel):
    lastUpdated: str
    recordTotal: int
    sources: list[str]
    coverageCaveats: list[str]
    sensitivityPolicy: SensitivityPolicy
    attributions: list[Attribution]
