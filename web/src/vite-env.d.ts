/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the read-only FastAPI service. Empty = same-origin `/api`. */
  readonly VITE_API_BASE?: string;
  /** Base URL for the Martin tile server. Empty = same-origin `/tiles`. */
  readonly VITE_TILES_BASE?: string;
  /** "false" to hit the real API; anything else (default) uses mock data. */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
