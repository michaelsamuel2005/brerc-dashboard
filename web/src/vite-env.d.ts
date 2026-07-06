/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the read-only FastAPI service. Empty = same-origin `/api`. */
  readonly VITE_API_BASE?: string;
  /** Base URL for the Martin tile server. Empty = same-origin `/tiles`. */
  readonly VITE_TILES_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
