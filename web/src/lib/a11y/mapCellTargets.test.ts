import { describe, it, expect } from 'vitest';
import {
  collectMapCellGeometry, assessMapCells,
  type CellCollection, type CollectionCounts, type CollectedCell, type CameraState
} from './mapCellTargets';
import { first, at, countKind } from './testUtil';

/* ── Stub map + window for the in-page collector ─────────────────────────────── */

interface StubOpts {
  styleLoaded?: boolean;
  rendered?: Array<{ properties?: Record<string, unknown> }>;
  throwOnQuery?: boolean;
  throwOnProject?: boolean;
  throwOnCamera?: boolean;
  project?: (c: [number, number]) => { x: number; y: number };
  canvasRect?: { left: number; top: number; width: number; height: number };
}

const stubWindow = (canonical: unknown, o: StubOpts = {}): void => {
  const map = {
    getZoom: () => 8, getBearing: () => 0, getPitch: () => 0,
    getCenter: () => { if (o.throwOnCamera) throw new Error('no centre'); return { lng: -2.6, lat: 51.45 }; },
    getBounds: () => ({ getWest: () => -3, getSouth: () => 51, getEast: () => -2, getNorth: () => 52 }),
    getCanvas: () => ({
      clientWidth: o.canvasRect?.width ?? 390,
      clientHeight: o.canvasRect?.height ?? 500,
      getBoundingClientRect: () =>
        o.canvasRect ?? { left: 0, top: 0, width: 390, height: 500 }
    }),
    getStyle: () => ({ name: 'brerc-base', sources: { cells: {}, basemap: {} } }),
    isStyleLoaded: () => o.styleLoaded !== false,
    project: (c: [number, number]) => {
      if (o.throwOnProject) throw new Error('projection failed');
      return o.project ? o.project(c) : { x: c[0] * 10, y: c[1] * 10 };
    },
    queryRenderedFeatures: () => {
      if (o.throwOnQuery) throw new Error('boom');
      return o.rendered ?? [];
    }
  };
  (globalThis as unknown as Record<string, unknown>)['window'] = {
    __brercMap: map, __brercCanonicalCells: canonical,
    innerWidth: 390, innerHeight: 844, devicePixelRatio: 2
  };
};

const CONFIG = {
  mapGlobal: '__brercMap', canonicalCellsGlobal: '__brercCanonicalCells',
  layers: ['cells'], cellIdProperty: 'cellId'
};
const square = (cellId: string): { cellId: string; ring: number[][] } =>
  ({ cellId, ring: [[0, 0], [1, 0], [1, 1], [0, 1]] });

/* ── Fixtures for the Node-side assessor ─────────────────────────────────────── */

const counts = (o: Partial<CollectionCounts> = {}): CollectionCounts => ({
  canonicalSupplied: 0, collected: 0, skipped: 0, skipReasons: {},
  renderedQueried: 0, renderedNotInCanonical: [], ...o
});
const CAMERA: CameraState = {
  zoom: 8, bearing: 0, pitch: 0, centerLng: -2.6, centerLat: 51.45,
  boundsWest: -3, boundsSouth: 51, boundsEast: -2, boundsNorth: 52,
  mapWidthPx: 390, mapHeightPx: 500, viewportWidth: 390, viewportHeight: 844,
  devicePixelRatio: 2, styleName: 'brerc-base', sourceIds: 'basemap,cells'
};
const cell = (cellId: string, x: number, y: number, w: number, h = w, rendered = true): CollectedCell =>
  ({ cellId, rendered, corners: [{ x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h }] });
const coll = (cells: CollectedCell[], over: Partial<CellCollection> = {}): CellCollection => ({
  status: 'collected', reason: null, camera: CAMERA,
  counts: counts({ canonicalSupplied: cells.length, collected: cells.length }),
  cells, ...over
});

describe('collectMapCellGeometry — guard clauses', () => {
  it('errors when the map adapter is absent', () => {
    (globalThis as unknown as Record<string, unknown>)['window'] = { innerWidth: 390, devicePixelRatio: 1 };
    const r = collectMapCellGeometry(CONFIG);
    expect(r.status).toBe('error');
    expect(r.reason).toContain('No map adapter');
  });
  it('errors when the style has not loaded', () => {
    stubWindow([square('A')], { styleLoaded: false });
    expect(collectMapCellGeometry(CONFIG).reason).toContain('Style not loaded');
  });
  it('errors when no layer ids are supplied', () => {
    stubWindow([square('A')]);
    expect(collectMapCellGeometry({ ...CONFIG, layers: [] }).reason).toContain('No selectable layer ids');
  });
  it('errors when canonical cells are missing — rendered features are not proof of extent', () => {
    stubWindow(undefined);
    const r = collectMapCellGeometry(CONFIG);
    expect(r.status).toBe('error');
    expect(r.reason).toContain('canonical');
  });
  it('errors when canonical cells are not an array', () => {
    stubWindow({ nope: true });
    expect(collectMapCellGeometry(CONFIG).status).toBe('error');
  });
  it('errors, rather than crashing, when camera state cannot be read', () => {
    stubWindow([square('A')], { throwOnCamera: true });
    expect(collectMapCellGeometry(CONFIG).reason).toContain('camera state');
  });
  it('errors when queryRenderedFeatures throws', () => {
    stubWindow([square('A')], { throwOnQuery: true });
    expect(collectMapCellGeometry(CONFIG).reason).toContain('queryRenderedFeatures failed');
  });
  it('turns a projection exception into structured evidence, not a crash', () => {
    stubWindow([square('A')], { throwOnProject: true });
    const r = collectMapCellGeometry(CONFIG);
    expect(r.status).toBe('inconclusive');
    expect(r.counts.skipReasons['malformed-coordinates']).toBe(1);
  });
  it('is inconclusive when every canonical cell is skipped', () => {
    stubWindow([{ cellId: '', ring: [[0, 0], [1, 0], [1, 1], [0, 1]] }]);
    const r = collectMapCellGeometry(CONFIG);
    expect(r.status).toBe('inconclusive');
    expect(r.counts.skipped).toBe(1);
  });
});

describe('collectMapCellGeometry — skip reasons and boundaries', () => {
  it.each([
    ['a null entry', null, 'missing-cellId'],
    ['a non-string cellId', { cellId: {}, ring: [[0, 0], [1, 0], [1, 1], [0, 1]] }, 'missing-cellId'],
    ['an empty cellId', { cellId: '', ring: [[0, 0], [1, 0], [1, 1], [0, 1]] }, 'missing-cellId'],
    ['a non-array ring', { cellId: 'A', ring: 'nope' }, 'malformed-ring'],
    ['a 3-point ring', { cellId: 'A', ring: [[0, 0], [1, 0], [1, 1]] }, 'malformed-ring'],
    ['a 1-element pair', { cellId: 'A', ring: [[0], [1, 0], [1, 1], [0, 1]] }, 'malformed-coordinates'],
    ['a non-array coordinate', { cellId: 'A', ring: [5, [1, 0], [1, 1], [0, 1]] }, 'malformed-coordinates'],
    ['a NaN longitude', { cellId: 'A', ring: [[NaN, 0], [1, 0], [1, 1], [0, 1]] }, 'malformed-coordinates'],
    ['a NaN latitude', { cellId: 'A', ring: [[0, NaN], [1, 0], [1, 1], [0, 1]] }, 'malformed-coordinates']
  ])('skips %s as %s', (_label, bad, reason) => {
    stubWindow([bad, square('KEEP')]);
    const r = collectMapCellGeometry(CONFIG);
    expect(r.counts.skipReasons[reason as string]).toBe(1);
    expect(r.cells.map(c => c.cellId)).toEqual(['KEEP']);
  });
  it('accepts a numeric cellId', () => {
    stubWindow([{ cellId: 12345, ring: [[0, 0], [1, 0], [1, 1], [0, 1]] }]);
    expect(first(collectMapCellGeometry(CONFIG).cells).cellId).toBe('12345');
  });
  it('accepts a ring of exactly four points', () => {
    stubWindow([square('A')]);
    const r = collectMapCellGeometry(CONFIG);
    expect(r.status).toBe('collected');
    expect(r.counts.skipped).toBe(0);
  });
  it('accepts pairs with extra elements (elevation)', () => {
    stubWindow([{ cellId: 'A', ring: [[0, 0, 5], [1, 0, 5], [1, 1, 5], [0, 1, 5]] }]);
    expect(collectMapCellGeometry(CONFIG).counts.collected).toBe(1);
  });
  it('skips a duplicate cellId rather than double-counting it', () => {
    stubWindow([square('A'), square('A')]);
    const r = collectMapCellGeometry(CONFIG);
    expect(r.counts.skipReasons['duplicate-cellId']).toBe(1);
    expect(r.counts.collected).toBe(1);
  });
  it('skips a cell whose projection returns a non-finite point', () => {
    stubWindow([square('A')], {
      project: c => (c[0] === 0 && c[1] === 0 ? { x: NaN, y: 0 } : { x: c[0] * 10, y: c[1] * 10 })
    });
    expect(collectMapCellGeometry(CONFIG).counts.skipReasons['malformed-coordinates']).toBe(1);
  });
});

describe('collectMapCellGeometry — rendered flags, orphans and camera', () => {
  it('marks a cell rendered when queryRenderedFeatures reports it', () => {
    stubWindow([square('A'), square('B')], { rendered: [{ properties: { cellId: 'A' } }] });
    const r = collectMapCellGeometry(CONFIG);
    expect(r.cells.find(c => c.cellId === 'A')?.rendered).toBe(true);
    expect(r.cells.find(c => c.cellId === 'B')?.rendered).toBe(false);
    expect(r.counts.renderedQueried).toBe(1);
  });
  it.each([['undefined', undefined], ['null', null], ['empty string', ''], ['an object', {}]])(
    'ignores a rendered feature whose cellId is %s', (_l, id) => {
      stubWindow([square('A')], { rendered: [{ properties: { cellId: id } }] });
      expect(first(collectMapCellGeometry(CONFIG).cells).rendered).toBe(false);
    });
  it('ignores a rendered feature with no properties', () => {
    stubWindow([square('A')], { rendered: [{}] });
    const result = collectMapCellGeometry(CONFIG);
    expect(first(result.cells).rendered).toBe(false);
    expect(result.counts.renderedMissingCellId).toBe(1);
  });
  it('reports rendered ids that have no canonical polygon instead of ignoring them', () => {
    stubWindow([square('A')], { rendered: [{ properties: { cellId: 'A' } }, { properties: { cellId: 'GHOST' } }] });
    expect(collectMapCellGeometry(CONFIG).counts.renderedNotInCanonical).toEqual(['GHOST']);
  });
  it('captures full camera evidence including bounds, canvas size and style identity', () => {
    stubWindow([square('A')]);
    const cam = collectMapCellGeometry(CONFIG).camera;
    expect(cam).not.toBeNull();
    expect(cam?.centerLng).toBe(-2.6);
    expect(cam?.boundsNorth).toBe(52);
    expect(cam?.mapWidthPx).toBe(390);
    expect(cam?.mapHeightPx).toBe(500);
    expect(cam?.viewportHeight).toBe(844);
    expect(cam?.styleName).toBe('brerc-base');
    expect(cam?.sourceIds).toBe('basemap,cells');
  });
  it('translates map-relative projections into viewport coordinates', () => {
    stubWindow([square('A')], {
      canvasRect: { left: 80, top: 240, width: 390, height: 500 }
    });
    const result = collectMapCellGeometry(CONFIG);
    expect(first(first(result.cells).corners).x).toBe(80);
    expect(first(first(result.cells).corners).y).toBe(240);
    expect(result.camera?.mapLeftPx).toBe(80);
    expect(result.camera?.mapTopPx).toBe(240);
  });
  it('counts supplied, collected and skipped consistently', () => {
    stubWindow([square('A'), { cellId: '', ring: [] }, square('B')]);
    const r = collectMapCellGeometry(CONFIG);
    expect(r.counts.canonicalSupplied).toBe(3);
    expect(r.counts.collected).toBe(2);
    expect(r.counts.skipped).toBe(1);
  });
});

describe('assessMapCells', () => {
  it('validates its thresholds', () => {
    expect(() => assessMapCells(coll([cell('A', 0, 0, 50)]), NaN)).toThrow(RangeError);
    expect(() => assessMapCells(coll([cell('A', 0, 0, 50)]), 24, 0)).toThrow(RangeError);
  });
  it('treats zero cells as inconclusive and raises a finding', () => {
    const r = assessMapCells(coll([], { status: 'inconclusive', reason: 'No cells collected' }));
    expect(r.status).toBe('inconclusive');
    expect(countKind(r.findings, 'map-inconclusive')).toBe(1);
    expect(r.cellsMeasured).toBe(0);
  });
  it('surfaces a collection error as a finding', () => {
    const r = assessMapCells({ status: 'error', reason: 'No map adapter', camera: null,
                               counts: counts(), cells: [] });
    expect(r.status).toBe('error');
    expect(countKind(r.findings, 'map-error')).toBe(1);
  });
  it('is inconclusive when any cell was skipped', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 50)], {
      counts: counts({ canonicalSupplied: 3, collected: 1, skipped: 2,
                       skipReasons: { 'malformed-ring': 1, 'missing-cellId': 1 } })
    }));
    expect(r.status).toBe('inconclusive');
    expect(countKind(r.findings, 'map-collection-skipped')).toBe(1);
  });
  it('measures canonical polygons and keys findings by cellId', () => {
    const r = assessMapCells(coll([cell('ST5872', 0, 0, 10), cell('ST5972', 60, 0, 50)]));
    expect(r.cells.map(c => c.cellId).sort()).toEqual(['ST5872', 'ST5972']);
    // One WCAG finding for the 10px cell; the 44px project finding is now reported
    // separately rather than suppressed, so count by severity here.
    expect(r.findings.filter(f => f.severity === 'wcag-nonconformance')).toHaveLength(1);
  });
  it('preserves raw measurements — 23.96 is never reported as 24', () => {
    const r = assessMapCells(coll([cell('X', 0, 0, 23.96)]));
    expect(first(r.cells).widthPx).toBeCloseTo(23.96, 6);
    expect(first(r.cells).widthPx).not.toBe(24);
    expect(first(r.cells).verdictAA).toBe('fail');
  });
  it('never returns "pass" — an adequate bbox is manual review', () => {
    const r = assessMapCells(coll([cell('BIG', 0, 0, 100)]));
    expect(first(r.cells).verdictAA).toBe('manual-review');
    expect(countKind(r.findings, 'map-cell-manual-review')).toBe(1);
  });
  it('fails a cell undersized in one dimension only', () => {
    const r = assessMapCells(coll([cell('WIDE', 0, 0, 100, 10)]));
    expect(first(r.cells).verdictAA).toBe('fail');
  });
  it('reports each threshold separately', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 20), cell('B', 200, 0, 30)]));
    expect(r.cells.filter(c => c.verdictAA === 'fail').map(c => c.cellId)).toEqual(['A']);
    expect(r.cells.filter(c => c.verdictProject === 'fail').map(c => c.cellId).sort()).toEqual(['A', 'B']);
  });
  it('a cell of exactly 24px is manual review, not fail', () => {
    expect(first(assessMapCells(coll([cell('X', 0, 0, 24)])).cells).verdictAA).toBe('manual-review');
  });
  it('a cell of exactly 44px is manual review against the project rule', () => {
    expect(first(assessMapCells(coll([cell('X', 0, 0, 44)])).cells).verdictProject).toBe('manual-review');
  });
  it('reports cells that were not rendered', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 50), cell('B', 200, 0, 50, 50, false)]));
    expect(countKind(r.findings, 'map-cell-not-rendered')).toBe(1);
  });
  it('does not call a wholly off-canvas canonical cell a rendering failure', () => {
    const r = assessMapCells(coll([cell('OFF', 500, 600, 50, 50, false)]));
    expect(first(r.cells).intersectsCanvas).toBe(false);
    expect(countKind(r.findings, 'map-cell-not-rendered')).toBe(0);
  });
  it('is inconclusive when rendered features have no usable cell identifier', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 50)], {
      counts: counts({
        canonicalSupplied: 1,
        collected: 1,
        renderedQueried: 2,
        renderedMissingCellId: 1
      })
    }));
    expect(r.status).toBe('inconclusive');
    expect(countKind(r.findings, 'map-collection-skipped')).toBe(1);
  });
  it('reports rendered ids missing from the canonical list', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 50)], {
      counts: counts({ canonicalSupplied: 1, collected: 1, renderedNotInCanonical: ['GHOST'] })
    }));
    expect(countKind(r.findings, 'map-rendered-not-in-canonical')).toBe(1);
  });
  it('reports the minimum dimensions across cells', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 50, 30), cell('B', 200, 0, 20, 80)]));
    expect(r.minWidthPx).toBe(20);
    expect(r.minHeightPx).toBe(30);
  });
  it('emits rendered cells as spacing obstacles for the DOM pass', () => {
    const r = assessMapCells(coll([cell('A', 10, 20, 30, 40), cell('B', 200, 0, 50, 50, false)]));
    expect(r.obstacles).toHaveLength(1);
    expect(first(r.obstacles).id).toBe('map-cell:A');
    expect(first(r.obstacles).rect.left).toBe(10);
    expect(first(r.obstacles).rect.width).toBe(30);
  });
  it('emits no obstacles when nothing is rendered', () => {
    expect(assessMapCells(coll([cell('A', 0, 0, 50, 50, false)])).obstacles).toHaveLength(0);
  });
  it('carries the camera through to the assessment', () => {
    expect(assessMapCells(coll([cell('A', 0, 0, 50)])).camera?.zoom).toBe(8);
  });
  it('always publishes the caveats a reviewer needs', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 50)]));
    expect(r.caveats.some(c => c.includes('UPPER bound'))).toBe(true);
    expect(r.caveats.some(c => c.includes('monotonic in zoom'))).toBe(true);
  });
  it('gives two cells at the same zoom distinct finding ids', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 10), cell('B', 200, 0, 10)]));
    const ids = r.findings
      .filter(f => f.kind === 'map-cell-below-threshold' && f.severity === 'wcag-nonconformance')
      .map(f => f.id);
    expect(new Set(ids).size).toBe(2);
    expect(at(ids, 0)).not.toBe(at(ids, 1));
  });
});

describe('assessMapCells — status guards', () => {
  it('an empty cell list is inconclusive even when the status says "collected"', () => {
    const r = assessMapCells(coll([]));
    expect(r.status).toBe('inconclusive');
    expect(countKind(r.findings, 'map-inconclusive')).toBe(1);
  });
  it('a non-empty collection with "inconclusive" status is still treated as inconclusive', () => {
    const r = assessMapCells(coll([cell('A', 0, 0, 50)], { status: 'inconclusive', reason: 'partial' }));
    expect(r.status).toBe('inconclusive');
  });
});

describe('thresholds are reported independently', () => {
  it('a cell below 24px raises BOTH the WCAG and the 44px project finding', () => {
    const r = assessMapCells(coll([cell('TINY', 0, 0, 10)]));
    const wcag = r.findings.filter(f => f.severity === 'wcag-nonconformance');
    const project = r.findings.filter(f => f.severity === 'project-requirement');
    expect(wcag).toHaveLength(1);
    expect(project).toHaveLength(1);      // previously suppressed when the WCAG one fired
  });
  it('a cell between 24 and 44 raises only the project finding', () => {
    const r = assessMapCells(coll([cell('MID', 0, 0, 30)]));
    expect(r.findings.filter(f => f.severity === 'wcag-nonconformance')).toHaveLength(0);
    expect(r.findings.filter(f => f.severity === 'project-requirement')).toHaveLength(1);
  });
  it('a cell above 44 raises neither threshold finding', () => {
    const r = assessMapCells(coll([cell('BIG', 0, 0, 60)]));
    expect(r.findings.filter(f => f.kind === 'map-cell-below-threshold')).toHaveLength(0);
  });
});
