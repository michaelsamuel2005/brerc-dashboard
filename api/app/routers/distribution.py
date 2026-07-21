"""
GET /api/distribution/cells — grid cells as GeoJSON (WGS84 / EPSG:4326).

This is the non-tile, accessible-equivalent view of the map data (also useful
for the WCAG data-table equivalent). The .mvt tiles themselves come from Martin
(B7), not from this endpoint.

STUB: one fake cell in the contract shape. Swap for real query in B8.
Every cell carries precisionMetres so the front end never implies more accuracy
than the (generalised) data actually has.
"""

from fastapi import APIRouter, Query

from app.models import (
    GeoJSONFeatureCollection,
    GeoJSONFeature,
    CellProperties,
)

router = APIRouter(prefix="/api", tags=["distribution"])


@router.get("/distribution/cells", response_model=GeoJSONFeatureCollection)
def distribution_cells(
    speciesId: int | None = Query(None),
) -> GeoJSONFeatureCollection:
    # A single fake 1 km cell near Bristol, as a GeoJSON polygon.
    fake_cell = GeoJSONFeature(
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [-2.60, 51.45],
                [-2.585, 51.45],
                [-2.585, 51.46],
                [-2.60, 51.46],
                [-2.60, 51.45],
            ]],
        },
        properties=CellProperties(
            cellId="ST5872",
            precisionMetres=1000,
            recordCount=57,
            verifiedCount=54,
        ),
    )
    return GeoJSONFeatureCollection(features=[fake_cell])
