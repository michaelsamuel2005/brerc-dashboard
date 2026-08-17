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

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class GridCell(StrictModel):
    """One map square.

    Deliberately carries no geometry.  The client derives the polygon from the
    validated ``cellId``, so the shape drawn always matches the identifier it
    was drawn for — a precise polygon cannot be mislabelled as a coarse cell,
    which is the failure that would undo generalisation at the last step.

    ``verifiedCount`` is present exactly when the release publishes verification.
    """

    cellId: str
    precisionMetres: int
    recordCount: int
    verifiedCount: int | None = None


class CellDistribution(StrictModel):
    verificationAvailable: bool
    cells: list[GridCell]


class YearCount(StrictModel):
    year: int
    count: int


class TopGroup(StrictModel):
    group: str
    count: int


class YearRange(StrictModel):
    min: int
    max: int


class Summary(StrictModel):
    totalRecords: int
    totalSpecies: int
    yearRange: YearRange | None
    recordsByYear: list[YearCount]
    topGroups: list[TopGroup]
    coverageCaveat: str


class SpeciesGroupFacet(StrictModel):
    value: str
    label: str
    speciesCount: int


class SpeciesListItem(StrictModel):
    """One row of the species directory.

    ``group`` is nullable because a release may publish no taxonomic grouping,
    or may hold a source value outside the reviewed vocabulary.  Both cases must
    render as ungrouped: hiding the species would lose data, and substituting a
    placeholder would put an unapproved taxonomic claim on a public page.

    ``firstYear``/``lastYear`` are null exactly when ``recordCount`` is zero.
    """

    speciesId: str
    slug: str
    scientificName: str
    commonName: str | None
    group: str | None
    recordCount: int
    firstYear: int | None
    lastYear: int | None
    hasImage: bool


class SpeciesFacets(StrictModel):
    groups: list[SpeciesGroupFacet]


class SpeciesListPage(StrictModel):
    items: list[SpeciesListItem]
    page: int
    pageSize: int
    total: int
    facets: SpeciesFacets


class SpeciesStats(StrictModel):
    """``yearRange`` is a two-element tuple here, unlike the summary's object.

    ``verifiedCount`` is null exactly when verification is unavailable, which
    the contract checks both ways — a zero would assert "none verified" where
    the truth is "not published".
    """

    recordCount: int
    yearRange: tuple[int, int] | None
    verificationAvailable: bool
    verifiedCount: int | None


class SpeciesImage(StrictModel):
    """A photograph the dashboard is licensed to show, with its full provenance.

    Every field is required, matching the web contract: an image without an
    attribution, a licence deed link, a source link, an approval reference or
    alt text is not publishable, so there is no optional field to forget.
    """

    url: str
    attributionText: str
    licence: str
    licenceUrl: str
    sourceUrl: str
    approvalReference: str
    alt: str


class DescriptionSource(StrictModel):
    """Who wrote the description text and under what terms.

    ``licenceUrl`` requires ``licence`` (the web contract's rule): a bare deed
    link with no licence name would render as an unlabelled hyperlink.
    """

    label: str
    approvalReference: str
    sourceUrl: str | None = Field(default=None)
    licence: str | None = Field(default=None)
    licenceUrl: str | None = Field(default=None)

    @model_validator(mode="after")
    def _licence_url_requires_licence(self) -> DescriptionSource:
        if self.licenceUrl is not None and self.licence is None:
            raise ValueError("licenceUrl requires licence")
        return self


class SpeciesDetail(StrictModel):
    """The species page.  ``imagePublication`` is per-response, decided by the
    approved-assets registry: ``approved-assets`` when this species has an
    approved image (which is then required), ``fallback-only`` otherwise (an
    image is then forbidden).  ``description``/``descriptionSource`` travel
    strictly together.  All three rules are asserted here so a router bug
    becomes a 500 in our logs rather than a rejected response in the browser.
    """

    speciesId: str
    slug: str
    scientificName: str
    commonName: str | None
    group: str | None
    imagePublication: str
    stats: SpeciesStats
    description: str | None = Field(default=None)
    descriptionSource: DescriptionSource | None = Field(default=None)
    image: SpeciesImage | None = Field(default=None)

    @model_validator(mode="after")
    def _media_contract(self) -> SpeciesDetail:
        if (self.description is None) != (self.descriptionSource is None):
            raise ValueError("description and descriptionSource must be published together")
        if self.imagePublication == "fallback-only" and self.image is not None:
            raise ValueError("fallback-only publication cannot expose a species image")
        if self.imagePublication == "approved-assets" and self.image is None:
            raise ValueError("approved-assets publication requires an approved image")
        return self
