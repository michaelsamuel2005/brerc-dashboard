-- =============================================================================
-- B7 — Vector tiles: a PostGIS "function source" for Martin
-- =============================================================================
-- Martin (the tile server) looks for a function shaped like
--   name(z integer, x integer, y integer, query_params json) RETURNS bytea
-- and exposes it at  /<name>/{z}/{x}/{y}.mvt . This one, `cells_tile`, builds a
-- Mapbox Vector Tile from the SAFE public_cells view — so, exactly like the
-- GeoJSON endpoint, a tile can only ever contain generalised cells + safe
-- fields. Precise points physically cannot enter a tile.
--
-- Load AFTER db/b6_schema.sql (+ b6_sample_data.sql to see output). Run in
-- pgAdmin, or the same python loader used for the other db/ files.
--
-- Optional filter: request .../{z}/{x}/{y}.mvt?speciesId=100001 to get one
-- species' distribution; omit it to get all species combined.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.cells_tile(
    z integer,
    x integer,
    y integer,
    query_params json DEFAULT '{}'::json
)
RETURNS bytea
LANGUAGE plpgsql
STABLE            -- same inputs -> same output (lets Postgres/Martin cache)
PARALLEL SAFE
AS $$
DECLARE
    mvt bytea;
    -- Optional ?speciesId= filter pulled from the tile request.
    species_filter bigint := NULLIF(query_params->>'speciesId', '')::bigint;
BEGIN
    SELECT ST_AsMVT(tile, 'cells', 4096, 'geom')
    INTO mvt
    FROM (
        SELECT
            -- Clip + encode the cell polygon into tile space. Input is
            -- transformed to Web Mercator (3857) to match the tile envelope.
            ST_AsMVTGeom(
                ST_Transform(c.geom, 3857),
                ST_TileEnvelope(z, x, y),
                4096,   -- tile extent
                64,     -- buffer (avoids clipped edges between tiles)
                true    -- clip geometry to the tile
            ) AS geom,
            c.cell_id,
            MAX(c.precision_metres) AS precision_metres,
            SUM(c.record_count)     AS record_count,
            SUM(c.verified_count)   AS verified_count
        FROM public_cells AS c
        -- Only cells that fall in this tile (uses the GiST index on the base
        -- table's geom). Compare in 4326 since public_cells.geom is 4326.
        WHERE c.geom && ST_Transform(ST_TileEnvelope(z, x, y), 4326)
          AND (species_filter IS NULL OR c.species_id = species_filter)
        GROUP BY c.cell_id, c.geom
    ) AS tile
    WHERE tile.geom IS NOT NULL;

    -- Return an empty tile (not NULL) when nothing is in view.
    RETURN COALESCE(mvt, ''::bytea);
END;
$$;

-- The read-only API/tile role must be allowed to EXECUTE this function.
GRANT EXECUTE ON FUNCTION public.cells_tile(integer, integer, integer, json)
    TO brerc_api_ro;
