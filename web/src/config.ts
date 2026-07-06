// Runtime configuration for where the front end finds its data.
//
// Defaults are RELATIVE paths so the production build works unchanged behind the
// same-origin reverse proxy (Caddy serves the static app and proxies /api and
// /tiles). Override with VITE_API_BASE / VITE_TILES_BASE at build time only if
// you deploy the API or tiles on a different origin (which then also needs CORS).

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

/** Base path for the read-only FastAPI service (no trailing slash). */
export const API_BASE = trimTrailingSlash(import.meta.env.VITE_API_BASE ?? '/api');

/** Base path for the Martin tile server (no trailing slash). */
export const TILES_BASE = trimTrailingSlash(import.meta.env.VITE_TILES_BASE ?? '/tiles');

/**
 * The Martin source id and the ST_AsMVT layer name. Both are `public_occurrences`
 * — the tile function (db/migrations/0005) and its layer share that name. Keep
 * this in step with the database if either is renamed.
 */
export const TILE_SOURCE = 'public_occurrences';

/** Initial map view: the West of England (BRERC's area), WGS84. */
export const INITIAL_VIEW = {
  longitude: -2.6,
  latitude: 51.42,
  zoom: 8.5,
} as const;
