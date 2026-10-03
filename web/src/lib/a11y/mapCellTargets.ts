import { makeFinding, type Finding } from './findings';
import { assertValidMin, type Obstacle, type TargetRect } from './targetSpacing';

/**
 * SC 2.5.8 for the selectable grid cells, which are WebGL features and NOT DOM elements,
 * so the DOM collector cannot see them.
 *
 * Measurement uses the application's own CANONICAL cell polygons, not
 * queryRenderedFeatures(). Rendered features are only currently-drawn geometry and may be
 * clipped or duplicated at tile boundaries, so they prove interactivity, not extent.
 * https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/#queryrenderedfeatures
 *
 * Split for the same serialisation reason as collectTargets:
 *   collectMapCellGeometry()  runs in the page, self-contained, returns plain data
 *   assessMapCells()          runs in Node, unit-tested, produces findings
 */

export interface Point { readonly x: number; readonly y: number }

export interface CollectedCell {
  readonly cellId: string;
  /** Canonical polygon corners, projected to screen pixels. */
  readonly corners: readonly Point[];
  /** Whether the cell is currently rendered and therefore actually selectable. */
  readonly rendered: boolean;
}

export interface CameraState {
  readonly zoom: number;
  readonly bearing: number;
  readonly pitch: number;
  readonly centerLng: number;
  readonly centerLat: number;
  readonly boundsWest: number;
  readonly boundsSouth: number;
  readonly boundsEast: number;
  readonly boundsNorth: number;
  readonly mapWidthPx: number;
  readonly mapHeightPx: number;
  /** Canvas position in viewport coordinates; map.project() itself is canvas-relative. */
  readonly mapLeftPx?: number;
  readonly mapTopPx?: number;
  readonly viewportWidth: number;
  readonly viewportHeight: number;
  readonly devicePixelRatio: number;
  readonly styleName: string;
  readonly sourceIds: string;
}

export interface CollectionCounts {
  readonly canonicalSupplied: number;
  readonly collected: number;
  readonly skipped: number;
  readonly skipReasons: Readonly<Record<string, number>>;
  readonly renderedQueried: number;
  /** Rendered features that could not be related to a canonical cell. */
  readonly renderedMissingCellId?: number;
  /** Rendered feature ids with no canonical counterpart — never silently ignored. */
  readonly renderedNotInCanonical: readonly string[];
}

export interface CellCollection {
  readonly status: 'collected' | 'inconclusive' | 'error';
  readonly reason: string | null;
  readonly camera: CameraState | null;
  readonly counts: CollectionCounts;
  readonly cells: readonly CollectedCell[];
}

interface MapLike {
  getZoom(): number;
  getBearing(): number;
  getPitch(): number;
  getCenter(): { lng: number; lat: number };
  getBounds(): { getWest(): number; getSouth(): number; getEast(): number; getNorth(): number };
  getCanvas(): {
    clientWidth: number;
    clientHeight: number;
    getBoundingClientRect?: () => {
      left: number; top: number; width: number; height: number;
    };
  };
  getStyle(): { name?: string; sources?: Record<string, unknown> };
  isStyleLoaded(): boolean;
  project(c: [number, number]): { x: number; y: number };
  queryRenderedFeatures(o: { layers: string[] }): Array<{ properties?: Record<string, unknown> }>;
}

interface CanonicalCell { cellId: unknown; ring: unknown }

/**
 * IN-PAGE. Self-contained by contract — no module-scope references.
 *
 * Non-production test adapter required:
 *   window.__brercMap            = mapRef.current.getMap()
 *   window.__brercCanonicalCells = [{ cellId, ring: [[lng,lat], ...] }, ...]
 *
 * Call only after the map has emitted 'idle'.
 */
export function collectMapCellGeometry(
  config: { mapGlobal: string; canonicalCellsGlobal: string; layers: string[]; cellIdProperty: string }
): CellCollection {
  // SELF-CONTAINED BY CONTRACT. Everything this function needs is declared INSIDE it.
  // Playwright serialises only the function source; module-scope bindings do not exist in
  // the page. An earlier version referenced module-level `usableId` and `EMPTY_COUNTS` and
  // threw "ReferenceError: usableId is not defined" the moment it ran in a browser.
  // serialization.pw.test.ts now exercises every collector through real Chromium so this
  // cannot regress silently.
  const emptyCounts: CollectionCounts = {
    canonicalSupplied: 0, collected: 0, skipped: 0, skipReasons: {},
    renderedQueried: 0, renderedMissingCellId: 0, renderedNotInCanonical: []
  };
  /** A feature id is usable only if it is a non-empty string or a finite number. */
  const usableId = (v: unknown): string | null => {
    if (typeof v === 'string') return v.length > 0 ? v : null;
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : null;
    return null;
  };
  const fail = (reason: string, camera: CameraState | null): CellCollection =>
    ({ status: 'error', reason, camera, counts: emptyCounts, cells: [] });

  const w = window as unknown as Record<string, unknown>;
  const map = w[config.mapGlobal] as MapLike | undefined;
  if (!map) return fail(`No map adapter at window.${config.mapGlobal}`, null);
  if (typeof map.isStyleLoaded !== 'function' || !map.isStyleLoaded()) {
    return fail('Style not loaded — wait for the map "idle" event before collecting', null);
  }
  if (config.layers.length === 0) return fail('No selectable layer ids supplied', null);

  let camera: CameraState;
  try {
    const centre = map.getCenter();
    const b = map.getBounds();
    const canvas = map.getCanvas();
    const canvasRect = typeof canvas.getBoundingClientRect === 'function'
      ? canvas.getBoundingClientRect()
      : { left: 0, top: 0, width: canvas.clientWidth, height: canvas.clientHeight };
    const style = map.getStyle();
    camera = {
      zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch(),
      centerLng: centre.lng, centerLat: centre.lat,
      boundsWest: b.getWest(), boundsSouth: b.getSouth(),
      boundsEast: b.getEast(), boundsNorth: b.getNorth(),
      mapWidthPx: canvasRect.width, mapHeightPx: canvasRect.height,
      mapLeftPx: canvasRect.left, mapTopPx: canvasRect.top,
      viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
      styleName: typeof style.name === 'string' ? style.name : '(unnamed)',
      sourceIds: style.sources ? Object.keys(style.sources).sort().join(',') : ''
    };
  } catch (e) {
    return fail(`Could not read camera state: ${String(e)}`, null);
  }

  const canonicalRaw = w[config.canonicalCellsGlobal];
  if (!Array.isArray(canonicalRaw)) {
    return fail(
      `No canonical cells at window.${config.canonicalCellsGlobal}. Rendered features alone ` +
      'cannot prove a cell\'s full extent, so measurement cannot proceed.', camera);
  }
  const canonical = canonicalRaw as CanonicalCell[];

  // Which cells are actually rendered (interactivity confirmation only).
  const renderedIds = new Set<string>();
  let renderedQueried = 0;
  let renderedMissingCellId = 0;
  try {
    const feats = map.queryRenderedFeatures({ layers: config.layers });
    renderedQueried = feats.length;
    for (const f of feats) {
      const props = f.properties;
      const id = props ? usableId(props[config.cellIdProperty]) : null;
      if (id !== null) renderedIds.add(id);
      else renderedMissingCellId++;
    }
  } catch (e) {
    return fail(`queryRenderedFeatures failed: ${String(e)}`, camera);
  }

  const skipReasons: Record<string, number> = {};
  const skip = (why: string): void => { skipReasons[why] = (skipReasons[why] ?? 0) + 1; };
  const seen = new Set<string>();
  const cells: CollectedCell[] = [];

  for (const c of canonical) {
    if (c === null || typeof c !== 'object') { skip('missing-cellId'); continue; }
    const cellId = usableId(c.cellId);
    if (cellId === null) { skip('missing-cellId'); continue; }
    if (seen.has(cellId)) { skip('duplicate-cellId'); continue; }
    if (!Array.isArray(c.ring) || c.ring.length < 4) { skip('malformed-ring'); continue; }

    const corners: Point[] = [];
    let bad = false;
    for (const pairRaw of c.ring as unknown[]) {
      if (!Array.isArray(pairRaw) || pairRaw.length < 2) { bad = true; break; }
      const lng = Number(pairRaw[0]);
      const lat = Number(pairRaw[1]);
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) { bad = true; break; }
      let p: { x: number; y: number };
      try {
        p = map.project([lng, lat]);   // never let a projection throw escape as a crash
      } catch { bad = true; break; }
      if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) { bad = true; break; }
      // map.project() is relative to the canvas. DOM target rectangles are viewport
      // coordinates, so add the canvas offset before using cells as spacing obstacles.
      corners.push({
        x: p.x + (camera.mapLeftPx ?? 0),
        y: p.y + (camera.mapTopPx ?? 0)
      });
    }
    if (bad) { skip('malformed-coordinates'); continue; }

    seen.add(cellId);
    cells.push({ cellId, corners, rendered: renderedIds.has(cellId) });
  }

  const orphans: string[] = [];
  for (const id of renderedIds) if (!seen.has(id)) orphans.push(id);
  orphans.sort();

  const counts: CollectionCounts = {
    canonicalSupplied: canonical.length,
    collected: cells.length,
    skipped: canonical.length - cells.length,
    skipReasons,
    renderedQueried,
    renderedMissingCellId,
    renderedNotInCanonical: orphans
  };

  if (cells.length === 0) {
    return { status: 'inconclusive', reason: 'No cells collected', camera, counts, cells: [] };
  }
  return { status: 'collected', reason: null, camera, counts, cells };
}

export type CellVerdict = 'fail' | 'manual-review';

export interface CellMeasurement {
  readonly cellId: string;
  /** Raw and unrounded. A 23.96px cell must never be reported as 24. */
  readonly widthPx: number;
  readonly heightPx: number;
  readonly rendered: boolean;
  /** Whether the canonical polygon's projected box intersects the map canvas. */
  readonly intersectsCanvas: boolean;
  readonly verdictAA: CellVerdict;
  readonly verdictProject: CellVerdict;
}

export interface CellAssessment {
  readonly status: 'measured' | 'inconclusive' | 'error';
  readonly reason: string | null;
  readonly camera: CameraState | null;
  readonly counts: CollectionCounts;
  readonly cellsMeasured: number;
  readonly minWidthPx: number | null;
  readonly minHeightPx: number | null;
  readonly cells: readonly CellMeasurement[];
  readonly findings: readonly Finding[];
  /** Screen-space obstacles for the DOM spacing calculation. */
  readonly obstacles: readonly Obstacle[];
  readonly caveats: readonly string[];
}

const CAVEATS: readonly string[] = [
  'Measured from CANONICAL polygons. queryRenderedFeatures only confirms which cells are drawn.',
  'A projected bounding box is an UPPER bound on a sheared cell\'s hit area: only failures are certain.',
  'Cell pixel size is monotonic in zoom, so MINIMUM supported zoom is the worst case.',
  'Constrain bearing and pitch to 0 — rotation and tilt change the projected box.',
  'A measured failure cannot be dismissed. Fix the hit area or minimum zoom; document any ' +
  'separate WCAG exception claim as a reviewer-attested human decision.'
];

export function assessMapCells(
  collection: CellCollection, aaMin = 24, projectMin = 44
): CellAssessment {
  assertValidMin(aaMin, 'aaMin');
  assertValidMin(projectMin, 'projectMin');

  const cameraEvidence = (): Record<string, string | number | boolean | null> =>
    collection.camera
      ? {
          zoom: collection.camera.zoom,
          bearing: collection.camera.bearing,
          pitch: collection.camera.pitch,
          centerLng: collection.camera.centerLng,
          centerLat: collection.camera.centerLat,
          boundsWest: collection.camera.boundsWest,
          boundsSouth: collection.camera.boundsSouth,
          boundsEast: collection.camera.boundsEast,
          boundsNorth: collection.camera.boundsNorth,
          mapWidthPx: collection.camera.mapWidthPx,
          mapHeightPx: collection.camera.mapHeightPx,
          mapLeftPx: collection.camera.mapLeftPx ?? 0,
          mapTopPx: collection.camera.mapTopPx ?? 0,
          viewportWidth: collection.camera.viewportWidth,
          viewportHeight: collection.camera.viewportHeight,
          devicePixelRatio: collection.camera.devicePixelRatio,
          styleName: collection.camera.styleName,
          sourceIds: collection.camera.sourceIds
        }
      : {
          zoom: null, bearing: null, pitch: null, centerLng: null, centerLat: null,
          boundsWest: null, boundsSouth: null, boundsEast: null, boundsNorth: null,
          mapWidthPx: null, mapHeightPx: null, mapLeftPx: null, mapTopPx: null,
          viewportWidth: null, viewportHeight: null, devicePixelRatio: null,
          styleName: null, sourceIds: null
        };

  if (collection.status === 'error') {
    const reason = collection.reason ?? 'Unknown collection error';
    return {
      status: 'error', reason, camera: collection.camera, counts: collection.counts,
      cellsMeasured: 0, minWidthPx: null, minHeightPx: null, cells: [],
      obstacles: [], caveats: CAVEATS,
      findings: [makeFinding({
        kind: 'map-error', severity: 'data-quality', sc: '2.5.8',
        detail: `Map cell collection failed: ${reason}`,
        evidence: { reason }
      }, ['reason'])]
    };
  }

  if (collection.status === 'inconclusive' || collection.cells.length === 0) {
    const reason = collection.reason ?? 'No cells collected';
    return {
      status: 'inconclusive', reason, camera: collection.camera, counts: collection.counts,
      cellsMeasured: 0, minWidthPx: null, minHeightPx: null, cells: [],
      obstacles: [], caveats: CAVEATS,
      findings: [makeFinding({
        kind: 'map-inconclusive', severity: 'data-quality', sc: '2.5.8',
        detail: `Zero cells measured (${reason}). This is inconclusive, not a pass — check the ` +
                'adapter, layer ids, viewport and idle state.',
        evidence: { ...cameraEvidence(), reason }
      }, ['reason', 'zoom'])]
    };
  }

  const verdict = (w: number, h: number, min: number): CellVerdict =>
    (w < min || h < min) ? 'fail' : 'manual-review';

  const cells: CellMeasurement[] = [];
  const obstacles: Obstacle[] = [];
  const canvasLeft = collection.camera?.mapLeftPx ?? 0;
  const canvasTop = collection.camera?.mapTopPx ?? 0;
  const canvasRight = canvasLeft + (collection.camera?.mapWidthPx ?? 0);
  const canvasBottom = canvasTop + (collection.camera?.mapHeightPx ?? 0);
  for (const c of collection.cells) {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of c.corners) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }
    const widthPx = maxX - minX;
    const heightPx = maxY - minY;
    const intersectsCanvas =
      maxX > canvasLeft && minX < canvasRight && maxY > canvasTop && minY < canvasBottom;
    cells.push({
      cellId: c.cellId, widthPx, heightPx, rendered: c.rendered, intersectsCanvas,
      verdictAA: verdict(widthPx, heightPx, aaMin),
      verdictProject: verdict(widthPx, heightPx, projectMin)
    });
    if (c.rendered) {
      const rect: TargetRect = {
        left: minX, top: minY, right: maxX, bottom: maxY, width: widthPx, height: heightPx
      };
      obstacles.push({ id: `map-cell:${c.cellId}`, rect, source: 'map-cell' });
    }
  }

  const findings: Finding[] = [];
  for (const c of cells) {
    if (c.verdictAA === 'fail') {
      findings.push(makeFinding({
        kind: 'map-cell-below-threshold', severity: 'wcag-nonconformance', sc: '2.5.8',
        detail: `Cell ${c.cellId} renders at ${c.widthPx.toFixed(2)}x${c.heightPx.toFixed(2)}px, ` +
                `below ${aaMin}x${aaMin}. This measured failure must be fixed; it cannot be ` +
                'dismissed through the resolution ledger.',
        evidence: { cellId: c.cellId, widthPx: c.widthPx, heightPx: c.heightPx, ...cameraEvidence() }
      }, ['cellId', 'zoom']));
    } else {
      findings.push(makeFinding({
        kind: 'map-cell-manual-review', severity: 'needs-human-decision', sc: '2.5.8',
        detail: `Cell ${c.cellId} clears ${aaMin}px by projected bounding box, which overstates a ` +
                'sheared cell\'s hit area. A reviewer must confirm the real hit area.',
        evidence: { cellId: c.cellId, widthPx: c.widthPx, heightPx: c.heightPx, ...cameraEvidence() }
      }, ['cellId', 'zoom']));
    }
    // Reported independently: a cell can breach BOTH the WCAG minimum and the stricter
    // BRERC build-brief rule, and suppressing the second hides a project requirement.
    if (c.verdictProject === 'fail') {
      findings.push(makeFinding({
        kind: 'map-cell-below-threshold', severity: 'project-requirement', sc: null,
        detail: `Cell ${c.cellId} is below the ${projectMin}px BRERC build-brief minimum.`,
        evidence: { cellId: c.cellId, widthPx: c.widthPx, heightPx: c.heightPx, threshold: projectMin }
      }, ['cellId', 'threshold']));
    }
    if (c.intersectsCanvas && !c.rendered) {
      findings.push(makeFinding({
        kind: 'map-cell-not-rendered', severity: 'data-quality', sc: null,
        detail: `Cell ${c.cellId} is in the canonical list but was not rendered, so its ` +
                'interactivity was not confirmed at this camera position.',
        evidence: { cellId: c.cellId, ...cameraEvidence() }
      }, ['cellId', 'zoom']));
    }
  }

  for (const orphan of collection.counts.renderedNotInCanonical) {
    findings.push(makeFinding({
      kind: 'map-rendered-not-in-canonical', severity: 'data-quality', sc: null,
      detail: `Rendered feature "${orphan}" has no canonical polygon, so it was never measured.`,
      evidence: { cellId: orphan }
    }, ['cellId']));
  }

  const renderedMissingCellId = collection.counts.renderedMissingCellId ?? 0;
  if (renderedMissingCellId > 0) {
    findings.push(makeFinding({
      kind: 'map-collection-skipped', severity: 'data-quality', sc: null,
      detail: `${renderedMissingCellId} rendered feature(s) had no usable ` +
              'cell identifier and could not be matched to canonical geometry.',
      evidence: { renderedMissingCellId }
    }, ['renderedMissingCellId']));
  }

  const partial = collection.counts.skipped > 0 || renderedMissingCellId > 0;
  if (collection.counts.skipped > 0) {
    findings.push(makeFinding({
      kind: 'map-collection-skipped', severity: 'data-quality', sc: null,
      detail: `${collection.counts.skipped} canonical cell(s) were skipped and never assessed: ` +
              `${JSON.stringify(collection.counts.skipReasons)}`,
      evidence: { skipped: collection.counts.skipped,
                  reasons: JSON.stringify(collection.counts.skipReasons) }
    }, ['reasons']));
  }

  const widths = cells.map(c => c.widthPx);
  const heights = cells.map(c => c.heightPx);

  return {
    status: partial ? 'inconclusive' : 'measured',
    reason: partial
      ? [
          collection.counts.skipped > 0
            ? `${collection.counts.skipped} canonical cell(s) skipped: ` +
              JSON.stringify(collection.counts.skipReasons)
            : null,
          renderedMissingCellId > 0
            ? `${renderedMissingCellId} rendered feature(s) lacked a usable cell id`
            : null
        ].filter(Boolean).join('; ')
      : null,
    camera: collection.camera,
    counts: collection.counts,
    cellsMeasured: cells.length,
    minWidthPx: Math.min(...widths),
    minHeightPx: Math.min(...heights),
    cells, findings, obstacles, caveats: CAVEATS
  };
}
