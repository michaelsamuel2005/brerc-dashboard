The aggregation module transforms cleaned, verified individual occurrence records into a public-facing statistical and spatial dataset. Instead of exposing exact sensitive locations, it groups data into standardized grid cells and summary tables ready for web mapping and public queries.

File-by-File Breakdown
Verification Filtering (etl/aggregation/cell_filtering.py)
- Retains only records with accepted or legacy verification statuses based on NBN standards, dropping unverified or rejected rows.

Spatial Binning & Geometry (etl/aggregation/geometry.py)
- Converts British National Grid (BNG) coordinates into grid cells using the cell size defined in safety.yaml and generates WGS84 WKT polygons (geom) for GIS mapping.

Counts & Privacy Suppression (etl/aggregation/ or main aggregation logic)
- Summarizes counts and verified counts grouped by species, grid cell, and year, and removes grid cells where record counts fall below the safety threshold to protect sensitive locations.

Species Indexing (etl/aggregation/species_index.py)
- Builds a summary table of unique species actively appearing in public data, tracking total records, names, and active year ranges.

Database Persistence (etl/aggregation/persist.py)
- Safely truncates and reloads the distribution_cell table each run while executing an upsert on the species table to protect foreign-key relationships with occurrence_public.