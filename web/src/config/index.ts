/**
 * Env-driven front-end config.
 *
 * Everything here is PUBLIC — it is compiled into the browser bundle. Never put
 * secrets, DB credentials, or API tokens here (CLAUDE.md §3, R6). The only thing
 * the client knows is a set of non-secret URLs; the dev -> prod swap is a change
 * of these environment values, never a change of code.
 */
const env = import.meta.env;

export const config = {
  /** Base URL of the backend API. In dev, MSW intercepts requests to it. */
  apiBaseUrl: env.VITE_API_BASE_URL ?? '/api',
  /** Public MapLibre basemap style JSON (no provider key). */
  mapStyleUrl: env.VITE_MAP_STYLE_URL ?? 'https://demotiles.maplibre.org/style.json',
  /** Vector-tile template for server-aggregated distribution grid cells. */
  tileUrl: env.VITE_TILE_URL ?? '/api/distribution/tiles/{z}/{x}/{y}.mvt',
} as const;

export type AppConfig = typeof config;
