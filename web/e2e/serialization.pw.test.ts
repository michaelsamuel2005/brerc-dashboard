import { test, expect } from '@playwright/test';
import { collectTargets } from '../src/lib/a11y/collectTargets';
import { collectMapCellGeometry } from '../src/lib/a11y/mapCellTargets';
import {
  collectProvenance, collectReflow, toggleDomTextSpacing,
  toggleSvgTextSpacing, collectDragAlternatives
} from '../src/lib/a11y/diagnostics';

/**
 * SERIALIZATION CONTRACT.
 *
 * Playwright serialises only a function's source into the page. Module bindings and
 * closures do not travel. Any collector that references a module-scope constant or helper
 * throws `ReferenceError` the moment it runs in a browser — even though it type-checks,
 * unit-tests green in Node, and looks correct on review.
 *
 * This exact defect shipped once: `collectMapCellGeometry` referenced module-level
 * `usableId` and `EMPTY_COUNTS`, and the spec called it through a wrapper arrow. Both
 * failed in Chromium with:
 *     ReferenceError: collectMapCellGeometry is not defined
 *     ReferenceError: usableId is not defined
 *
 * Unit tests cannot catch this — they run the function in Node, where the module scope
 * exists. Only executing it in a real browser can. Every collector therefore gets a case
 * here, and every new collector must be added.
 */

const MAP_STUB = `
  window.__brercMap = {
    getZoom: () => 8, getBearing: () => 0, getPitch: () => 0,
    getCenter: () => ({ lng: -2.6, lat: 51.45 }),
    getBounds: () => ({ getWest: () => -3, getSouth: () => 51, getEast: () => -2, getNorth: () => 52 }),
    getCanvas: () => ({ clientWidth: 390, clientHeight: 400 }),
    getStyle: () => ({ name: 'stub', sources: { cells: {} } }),
    isStyleLoaded: () => true,
    project: (c) => ({ x: c[0] * 10, y: c[1] * 10 }),
    queryRenderedFeatures: () => [{ properties: { cellId: 'ST5872' } }]
  };
  window.__brercCanonicalCells = [{ cellId: 'ST5872', ring: [[0,0],[1,0],[1,1],[0,1]] }];
`;

const MAP_CONFIG = {
  mapGlobal: '__brercMap', canonicalCellsGlobal: '__brercCanonicalCells',
  layers: ['cells'], cellIdProperty: 'cellId'
};

test.describe('browser serialization contract', () => {
  test.beforeEach(async ({ page }) => {
    await page.setContent(`
      <main>
        <h1>Serialization fixture</h1>
        <button aria-label="Zoom in">+</button>
        <button data-map-pan="north" aria-label="Pan north">↑</button>
        <table><tr><td>cell</td></tr></table>
        <svg width="100" height="40"><text x="5" y="20">1994</text></svg>
        <div class="maplibregl-canvas-container">
          <canvas class="maplibregl-canvas" tabindex="0" role="region" aria-label="Map"></canvas>
        </div>
      </main>`);
    await page.evaluate(MAP_STUB);
  });

  test('collectTargets runs in the page', async ({ page }) => {
    const targets = await page.evaluate(collectTargets);
    expect(Array.isArray(targets)).toBe(true);
    expect(targets.some(t => t.label === 'Zoom in')).toBe(true);
  });

  test('collectMapCellGeometry runs in the page — the one that regressed', async ({ page }) => {
    const collection = await page.evaluate(collectMapCellGeometry, MAP_CONFIG);
    expect(collection.status).toBe('collected');
    expect(collection.cells.map(c => c.cellId)).toEqual(['ST5872']);
    expect(collection.camera?.styleName).toBe('stub');
  });

  test('collectProvenance runs in the page', async ({ page }) => {
    const p = await page.evaluate(collectProvenance);
    expect(typeof p.userAgent).toBe('string');
    expect(p.innerWidth).toBeGreaterThan(0);
  });

  test('collectReflow runs in the page', async ({ page }) => {
    const r = await page.evaluate(collectReflow);
    expect(typeof r.rootOverflowSuppressed).toBe('boolean');
    expect(Array.isArray(r.candidates)).toBe(true);
  });

  test('collectDragAlternatives runs in the page', async ({ page }) => {
    const d = await page.evaluate(collectDragAlternatives);
    expect(d.declaredPanControls.map(p => p.direction)).toEqual(['north']);
    expect(d.canvasRole).toBe('region');
  });

  test('toggleDomTextSpacing runs in the page and is reversible', async ({ page }) => {
    expect((await page.evaluate(toggleDomTextSpacing)).applied).toBe(true);
    expect((await page.evaluate(toggleDomTextSpacing)).applied).toBe(false);
  });

  test('toggleSvgTextSpacing runs in the page and is reversible', async ({ page }) => {
    const on = await page.evaluate(toggleSvgTextSpacing);
    expect(on.applied).toBe(true);
    expect(on.svgTextCount).toBe(1);
    expect((await page.evaluate(toggleSvgTextSpacing)).applied).toBe(false);
  });

  test('a wrapper arrow around a collector FAILS — documents why we never use one', async ({ page }) => {
    // This is the pattern that shipped and broke. Asserted so the reason is executable,
    // not a comment someone can quietly contradict.
    await expect(
      page.evaluate(cfg => collectMapCellGeometry(cfg), MAP_CONFIG)
    ).rejects.toThrow(/collectMapCellGeometry is not defined/);
  });
});
