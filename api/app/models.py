"""Strict public response models for the active publication release.

Unknown keys are rejected. No model contains recorder identity, precise
coordinates, eastings/northings, comments, raw sensitivity markers or source
keys; the ``serve.*`` views do not expose them either.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseIdentity(StrictModel):
    """Identity carried by every response backed by an atomic release.

    A repeatable-read transaction makes each individual response coherent.
    Carrying the same identity on every public data response lets the browser
    extend that guarantee across the several requests needed to render a page.
    """

    releaseId: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    )
    datasetVersion: str = Field(min_length=1)


class Health(StrictModel):
    status: Literal["ok"]
    version: str


class PublicationFields(StrictModel):
    abundance: bool
    place: bool
    recordType: bool
    verification: bool


class RecordPublication(StrictModel):
    mode: Literal["aggregates-only", "individual-records"]
    fields: PublicationFields


class RecordRow(StrictModel):
    id: str = Field(min_length=1)
    scientificName: str = Field(min_length=1)
    commonName: str | None
    gridRef: str = Field(min_length=1)
    precisionMetres: Literal[100, 1000, 10000]
    place: str | None
    year: int = Field(ge=1500, le=2200)
    source: str = Field(min_length=1)
    abundance: str | None = None
    recordType: str | None = None
    verified: str | None = None


class RecordPage(ReleaseIdentity):
    publication: RecordPublication
    items: list[RecordRow]
    page: int = Field(gt=0)
    pageSize: int = Field(gt=0)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_publication_boundary(self) -> RecordPage:
        if self.publication.mode == "aggregates-only":
            if self.items or self.total:
                raise ValueError("aggregate-only releases cannot contain record rows")
            fields = self.publication.fields
            if fields.abundance or fields.place or fields.recordType or fields.verification:
                raise ValueError("aggregate-only releases cannot advertise record fields")
        if len(self.items) > self.pageSize or len(self.items) > self.total:
            raise ValueError("record page counts do not reconcile")
        return self


class Attribution(StrictModel):
    label: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    licence: str = Field(min_length=1)


class SensitivityPolicy(StrictModel):
    protectedRecordsMode: Literal["generalised", "withheld"]
    publishedLocationTiersMetres: list[Literal[100, 1000, 10000]]
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_tiers(self) -> SensitivityPolicy:
        if self.publishedLocationTiersMetres != sorted(set(self.publishedLocationTiersMetres)):
            raise ValueError("published location tiers must be sorted and unique")
        return self


class Provenance(ReleaseIdentity):
    lastUpdated: str
    recordTotal: int = Field(ge=0)
    sources: list[str]
    coverageCaveats: list[str]
    sensitivityPolicy: SensitivityPolicy
    attributions: list[Attribution]


class GridCell(StrictModel):
    cellId: str = Field(min_length=1)
    precisionMetres: Literal[100, 1000, 10000]
    recordCount: int = Field(gt=0)
    verifiedCount: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_verified_count(self) -> GridCell:
        if self.verifiedCount is not None and self.verifiedCount > self.recordCount:
            raise ValueError("verified count exceeds record count")
        return self


class CellDistribution(ReleaseIdentity):
    verificationAvailable: bool
    cells: list[GridCell]

    @model_validator(mode="after")
    def validate_verification_capability(self) -> CellDistribution:
        for cell in self.cells:
            present = "verifiedCount" in cell.model_fields_set
            if present != self.verificationAvailable:
                raise ValueError("cell verification fields disagree with release capability")
        return self


class YearCount(StrictModel):
    year: int = Field(ge=1500, le=2200)
    count: int = Field(gt=0)


class TopGroup(StrictModel):
    group: str = Field(min_length=1)
    count: int = Field(gt=0)


class YearRange(StrictModel):
    min: int = Field(ge=1500, le=2200)
    max: int = Field(ge=1500, le=2200)

    @model_validator(mode="after")
    def validate_order(self) -> YearRange:
        if self.min > self.max:
            raise ValueError("year range is reversed")
        return self


class Summary(ReleaseIdentity):
    totalRecords: int = Field(ge=0)
    totalSpecies: int = Field(ge=0)
    yearRange: YearRange | None
    recordsByYear: list[YearCount]
    topGroups: list[TopGroup]
    coverageCaveat: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_totals(self) -> Summary:
        if (self.totalRecords == 0) != (self.yearRange is None):
            raise ValueError("summary year range does not match total")
        if sum(bucket.count for bucket in self.recordsByYear) != self.totalRecords:
            raise ValueError("summary year buckets do not reconcile")
        years = [bucket.year for bucket in self.recordsByYear]
        if years != sorted(set(years)):
            raise ValueError("summary years must be sorted and unique")
        if self.yearRange is not None and (
            not years or self.yearRange.min != years[0] or self.yearRange.max != years[-1]
        ):
            raise ValueError("summary range does not match year buckets")
        return self


class SpeciesGroupFacet(StrictModel):
    value: str = Field(min_length=1)
    label: str = Field(min_length=1)
    speciesCount: int = Field(gt=0)


class SpeciesListItem(StrictModel):
    speciesId: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    scientificName: str = Field(min_length=1)
    commonName: str | None
    group: str | None
    recordCount: int = Field(ge=0)
    firstYear: int | None = Field(default=None, ge=1500, le=2200)
    lastYear: int | None = Field(default=None, ge=1500, le=2200)
    hasImage: Literal[False]

    @model_validator(mode="after")
    def validate_years(self) -> SpeciesListItem:
        years_present = self.firstYear is not None and self.lastYear is not None
        if (self.recordCount == 0) == years_present:
            raise ValueError("species year range does not match record count")
        if years_present and self.firstYear > self.lastYear:
            raise ValueError("species year range is reversed")
        return self


class SpeciesFacets(StrictModel):
    groups: list[SpeciesGroupFacet]


class SpeciesListPage(ReleaseIdentity):
    items: list[SpeciesListItem]
    page: int = Field(gt=0)
    pageSize: int = Field(gt=0)
    total: int = Field(ge=0)
    facets: SpeciesFacets


class SpeciesImage(StrictModel):
    """Legacy proxy cache value; never returned by the public API routers.

    ``species_info.py`` remains import-compatible for its existing isolated
    licence-gate tests, but ``app.main`` deliberately does not import or call
    that outbound proxy. Approved public media has a separate, richer browser
    contract and is not activated by this compatibility model.
    """

    url: str
    licence: str
    attribution: str


class SpeciesStats(StrictModel):
    recordCount: int = Field(ge=0)
    yearRange: tuple[int, int] | None
    verificationAvailable: bool
    verifiedCount: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_stats(self) -> SpeciesStats:
        if (self.verifiedCount is not None) != self.verificationAvailable:
            raise ValueError("verified count disagrees with release capability")
        if self.verifiedCount is not None and self.verifiedCount > self.recordCount:
            raise ValueError("verified count exceeds record count")
        if (self.recordCount == 0) != (self.yearRange is None):
            raise ValueError("species stats range does not match record count")
        if self.yearRange is not None:
            first, last = self.yearRange
            if not 1500 <= first <= last <= 2200:
                raise ValueError("species stats range is invalid")
        return self


class SpeciesDetail(ReleaseIdentity):
    speciesId: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    scientificName: str = Field(min_length=1)
    commonName: str | None
    group: str | None
    imagePublication: Literal["fallback-only"]
    stats: SpeciesStats
