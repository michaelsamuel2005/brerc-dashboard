from pydantic import BaseModel, ConfigDict, HttpUrl
from typing import Literal, Optional

# creating new shape called health, follows Pydantic rules BaseModel
# translation of .strict() - any fields not listed is forbidden
# translation of status
# translation of version
class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]
    version: str

class SpeciesListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speciesId: str
    scientificName: str
    commonName: Optional[str] = None
    group: str
    recordCount: int
    firstYear: Optional[int] = None
    lastYear: Optional[int] = None
    hasImage: bool

class SpeciesListPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SpeciesListItem]
    page: int
    pageSize: int
    total: int

class SpeciesImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    author: str
    licence: str
    licenceUrl: HttpUrl
    sourceUrl: HttpUrl
    alt: str

class SpeciesDetailStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recordCount: int
    yearRange: tuple[int, int]
    verifiedCount: int

class SpeciesDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speciesId: str
    scientificName: str
    commonName: Optional[str]
    group: str
    description: Optional[str] = None
    image: Optional[SpeciesImage] = None
    stats: SpeciesDetailStats

class RecordRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str 
    scientificName: str 
    commonName: Optional[str] 
    gridRef: str 
    precisionMetres: int 
    place: Optional[str]
    year: int 
    abundance: Optional[str]
    recordType: Optional[str]
    verified: str 
    source: str 

class RecordPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[RecordRow]
    page: int 
    pageSize: int
    total: int

class GridCellProps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cellId: str 
    precisionMetres: int
    recordCount: int 
    verifiedCount: Optional[int] = None

class GridCellGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]

class GridCellFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Feature"]
    geometry: GridCellGeometry
    properties: "GridCellProps"

class CellCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["FeatureCollection"]
    features: list[GridCellFeature]

class YearRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: int
    max: int

class RecordsByYearItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int
    count: int

class TopGroupItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group: str
    count: int

class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    totalRecords: int
    totalSpecies: int
    yearRange: YearRange
    recordsByYear: list[RecordsByYearItem]
    topGroups: list[TopGroupItem]
    coverageCaveat: str

class SensitivityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generalisationTiersMetres: list[int]
    appliesToProtectedTaxa: Literal[True]
    note: str

class Attribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    url: HttpUrl
    licence: str

class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lastUpdated: str
    recordTotal: int
    sources: list[str]
    coverageCaveats: list[str]
    sensitivityPolicy: SensitivityPolicy
    attributions: list[Attribution]