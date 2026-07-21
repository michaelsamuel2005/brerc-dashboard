from fastapi import FastAPI, Query, Response, HTTPException
from models import(
    Health, SpeciesListPage, SpeciesDetail, 
    CellCollection, RecordPage, Summary, Provenance
)

app = FastAPI(title="Biological Records API", version ="1.0.0")

@app.get("/api/health", response_model = Health)
def get_health():
    return {
        "status": "ok", 
        "version": "1.0.0"
    }

@app.get("/api/summary", response_model = Summary)
def get_summary():
    return {
        "totalRecords": 100000,
        "totalSpecies": 100,
        "yearRange": {"min": 1999, "max": 2026}
        "recordsByYear": [
            {"year": 2023, "count": 4000},
            {"year": 2024, "count": 2000},
            {"year": 2026, "count": 1000},
        ],
        "topGroups": [
            {"group": "Birds", "count": 10000 },
            {"group": "Plants", "count": 33810},
            {"group": "Animals", "count": 28900},
        ]
        "coverageCaveat": "AAAAAAAA"
    }

# Uses SpeciesListPageSchema: Wrapper for the page itself
# Paginated means one page sent at a time
@app.get(/"api/species", response_model=SpeciesListPage)
# Cap of 100 added for amount of pages
def list_species(
    page: int = 1, 
    pageSize: int = Query (25, le=100)
):
    sample_items = [
        {
            "speciesId": "sp-0001",
            "scientificName": "blank",
            "commonName": "blank"
            "group": "Birds"
            "recordCount": 842,
            "firstYear": 1999,
            "lastYear": 2026,
            "hasImage": True.
        },
          {
            "speciesId": "sp-0001",
            "scientificName": "blank",
            "commonName": "blank"
            "group": "Birds"
            "recordCount": 842,
            "firstYear": 1999,
            "lastYear": 2026,
            "hasImage": True.
        },
    ]
    return {
        "items": sample_items, 
        "page": page, 
        "pageSize": pageSize 
        "total": len(sample_items)
    }

@app.get("/api/species/{species_id}", response_model=SpeciesDetail)
def get_species_detail(species_id: str):
    if species_id != "sp-0001":
        raise HTTPException(
            status_code=404, 
            detail="Species not found",
        )
    return {
        "speciesId": "sp-0001",
        "scientificName": "Erithacus rubecula",
        "commonName": "European Robin",
        "group": "Birds",
        "description": "A common garden bird known for its red breast.",
        "image": {
            "url": "https://example.com/images/robin.jpg",
            "author": "Sample Author",
            "licence": "CC-BY 4.0",
            "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
            "sourceUrl": "https://example.com/source/robin",
            "alt": "A European Robin perched on a branch",
        },
        "stats": {"recordCount": 842, "yearRange": (1978, 2026), "verifiedCount": 790},
    }

@app.get("/api/distribution/cells", response_model=CellCollection)
def get_distribution_cells():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-0.71, 51.53], 
                            [-0.70, 51.53], 
                            [-0.70, 51.54], 
                            [-0.71, 51.54], 
                            [-0.71, 51.53]
                        ]
                    ],
                },
                "properties": {
                    "cellId": "TQ8085",
                    "precisionMetres": 1000,
                    "recordCount": 214,
                    "verifiedCount": 190,
                },
            }
        ],
    }

@app.get("/api/records", response_model=RecordPage)
def list_records(
    page: int = 1, 
    pageSize: int = Query(25, le=100)
):
    sample_items = [
        {
            "id": "rec-0001",
            "scientificName": "Erithacus rubecula",
            "commonName": "European Robin",
            "gridRef": "TQ8085",
            "precisionMetres": 1000,
            "place": "Southend-on-Sea area",
            "year": 2025,
            "abundance": "1",
            "recordType": "sighting",
            "verified": "accepted",
            "source": "BRERC",
        }
    ]
    return {
        "items": sample_items, 
        "page": page, 
        "pageSize": pageSize, 
        "total": len(sample_items)
    }
§
@app.get("/api/distribution/tiles/{z}/{x}/{y}.mvt")
def get_tile(z: int, x: int, y: int):
    return Response(
        content=b"", 
        media_type="application/vnd.mapbox-vector-tile",
    )

@app.get("/api/meta/provenance", response_model=Provenance)
def get_provenance():
    return {
        "lastUpdated": "2026-07-01",
        "recordTotal": 128400,
        "sources": [
            "BRERC record centre", 
            "iRecord", 
            "eBird"
        ],
        "coverageCaveats": [
            "Recording effort is not uniform across all areas."
        ],
        "sensitivityPolicy": {
            "generalisationTiersMetres": [
                100, 
                1000, 
                2000, 
                10000
            ],
            "appliesToProtectedTaxa": True,
            "note": (
                "Records of sensitive species are generalised to protect their locations."
            ),
        },
        "attributions": [
            {
                "label": "BRERC", 
                "url": "https://example.com/brerc", 
                "licence": "OGL"
            }
        ],
    }

