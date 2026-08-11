"""
GET /api/distribution/cells — grid cells as GeoJSON (WGS84 / EPSG:4326).

NOW READS REAL DATA (B8) from the public_cells view. This is the non-tile,
accessible-equivalent view of the map data (also useful for the WCAG data-table
equivalent). The .mvt tiles themselves come from Martin (B7), not this endpoint.

Cells are aggregated by cell (summing across years), optionally filtered to one
species. Every cell carries precisionMetres so the front end never implies more
accuracy than the (generalised) data actually has.
"""

import json

from fastapi import APIRouter, Query

from app import config
from app.db import get_connection
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
    # Optional species filter — fixed WHERE text, value passed as a parameter.
    where_sql = ""
    params: list = []
    if speciesId is not None:
        where_sql = "WHERE species_id = %s"
        params.append(speciesId)

    # One feature per cell: sum the counts across years, and let PostGIS turn the
    # cell polygon straight into a GeoJSON string with ST_AsGeoJSON.
    #
    # The LIMIT is a server-side cap (MAX_CELLS in app/config.py). Without it,
    # asking for every species at once would build one enormous response — slow
    # for the browser, and effectively a bulk download of the whole grid. The
    # map itself doesn't rely on this endpoint for wide views; it uses Martin's
    # vector tiles (B7), which only ever send the squares actually on screen.
    sql = f"""
        SELECT
            cell_id,
            MAX(precision_metres) AS precision_metres,
            SUM(record_count)     AS record_count,
            SUM(verified_count)   AS verified_count,
            ST_AsGeoJSON(geom)    AS geojson
        FROM public_cells
        {where_sql}
        GROUP BY cell_id, geom
        ORDER BY cell_id
        LIMIT %s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params + [config.MAX_CELLS])
            rows = cur.fetchall()

    features = [
        GeoJSONFeature(
            geometry=json.loads(row["geojson"]),   # GeoJSON string -> dict
            properties=CellProperties(
                cellId=row["cell_id"],
                precisionMetres=row["precision_metres"],
                recordCount=int(row["record_count"]),
                verifiedCount=int(row["verified_count"]),
            ),
        )
        for row in rows
    ]

    return GeoJSONFeatureCollection(features=features)
