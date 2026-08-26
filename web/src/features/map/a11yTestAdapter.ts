import type { Map as MapLibreMap } from 'maplibre-gl';

/**
 * Exposes the map internals the accessibility suite needs, only while the dedicated
 * accessibility-test mode is enabled.
 *
 * Why this exists: `mapRef` is private to the component, so Playwright cannot reach the
 * MapLibre instance to project canonical cell polygons or assert that a pan button
 * actually moves the camera. Without it, SC 2.5.8 for the WebGL cells and SC 2.5.7 for
 * the pan controls can only be guessed at from the DOM.
 *
 * The application call site is compile-time guarded by both `DEV` and
 * `VITE_A11Y_TEST_MODE`. Keeping environment access out of this module also makes its
 * data-only types safe to import from Node-side tests.
 */

export interface CanonicalCellExport {
  /** The generalised grid identifier, e.g. "ST5872". Never a precise coordinate. */
  readonly cellId: string;
  /** Closed ring of [lng, lat] pairs describing the generalised cell. */
  readonly ring: readonly (readonly [number, number])[];
}

export interface A11yAdapterConfig {
  readonly map: MapLibreMap | undefined;
  readonly canonicalCells: readonly CanonicalCellExport[];
  readonly selectableLayers: readonly string[];
}

declare global {
  interface Window {
    __brercMap?: MapLibreMap;
    __brercCanonicalCells?: readonly CanonicalCellExport[];
    __brercSelectableLayers?: readonly string[];
    __brercA11yBridgeReady?: true;
  }
}

export function installA11yTestAdapter(
  config: A11yAdapterConfig,
  enabled: boolean,
): void {
  if (!enabled) return;
  if (!config.map) return;
  window.__brercMap = config.map;
  window.__brercCanonicalCells = config.canonicalCells;
  window.__brercSelectableLayers = config.selectableLayers;
  window.__brercA11yBridgeReady = true;
}

export function removeA11yTestAdapter(): void {
  delete window.__brercMap;
  delete window.__brercCanonicalCells;
  delete window.__brercSelectableLayers;
  delete window.__brercA11yBridgeReady;
}
