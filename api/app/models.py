"""
Pydantic models = the exact SHAPE of each API response (the contract, §10).

These field names and types must match Michael's front-end Zod schemas EXACTLY.
If a name here differs from what the front end expects, its validation fails and
the app breaks — so treat these as the locked contract. When the real data is
wired in (B8), it must be shaped into these same models.

Every public response deliberately EXCLUDES: Recorder1, BLISS, Eastings,
Northings, Comments, and any sensitivity marker. Those never leave the backend.
"""

from pydantic import BaseModel


# ---- /api/health -----------------------------------------------------------
class Health(BaseModel):
    status: str
    version: str


# ---- /api/summary ----------------------------------------------------------
class YearCount(BaseModel):
    year: int
    count: int


class TopGroup(BaseModel):
    group: str
    count: int


class Summary(BaseModel):
    totalRecords: int
    totalSpecies: int
    yearRange: list[int]  # [minYear, maxYear]
    recordsByYear: list[YearCount]
    topGroups: list[TopGroup]
    coverageCaveat: str


# ---- /api/species and /api/species/{id} ------------------------------------
# NOTE ON IDs: speciesId and recordId are STRINGS, not numbers.
# Real BRERC SPECIES_NO / unique_No values are not always numeric (e.g.
# "NBNSYS0000008319"), which is why species_id and record_id are TEXT in the
# database. Typed as int, Pydantic quietly accepts numeric-looking ids and then
# raises a ValidationError — a 500 — on the first genuinely non-numeric one.
# Michael's Zod schema also expects a string, so this is the shape all three
# sides of the project agree on.
class SpeciesListItem(BaseModel):
    speciesId: str
    scientificName: str
    commonName: str | None
    group: str
    recordCount: int
    firstYear: int
    lastYear: int
    hasImage: bool


class SpeciesList(BaseModel):
    items: list[SpeciesListItem]
    total: int
    page: int
    pageSize: int


class SpeciesImage(BaseModel):
    url: str
    licence: str
    attribution: str


class SpeciesDetail(BaseModel):
    speciesId: str          # TEXT — see the note above SpeciesListItem
    scientificName: str
    commonName: str | None
    group: str
    recordCount: int
    firstYear: int
    lastYear: int
    image: SpeciesImage | None  # None when no licensed image (fail-closed)
    description: str | None


# ---- /api/distribution/cells (GeoJSON) -------------------------------------
class CellProperties(BaseModel):
    cellId: str
    precisionMetres: int
    recordCount: int
    verifiedCount: int


class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: dict  # GeoJSON Polygon (WGS84 / EPSG:4326)
    properties: CellProperties


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJSONFeature]


# ---- /api/records ----------------------------------------------------------
class RecordItem(BaseModel):
    recordId: str           # TEXT — see the note above SpeciesListItem
    scientificName: str
    commonName: str | None
    year: int
    gridRef: str  # precision = precisionMetres (generalised)
    precisionMetres: int
    place: str | None  # COARSE locality only — never precise
    verified: bool


class RecordList(BaseModel):
    items: list[RecordItem]
    total: int
    page: int
    pageSize: int


# ---- /api/meta/provenance --------------------------------------------------
class Provenance(BaseModel):
    sources: list[str]
    caveats: list[str]
    lastUpdated: str  # ISO date
    sensitivityPolicySummary: str
