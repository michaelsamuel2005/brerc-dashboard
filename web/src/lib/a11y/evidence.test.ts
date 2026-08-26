import { describe, it, expect } from 'vitest';
import {
  buildEvidence,
  summariseBySeverity,
  type ManualGateResults,
  type RunContext
} from './evidence';
import { classifyTargets } from './targetSpacing';
import { assessMapCells, type CellCollection, type CameraState } from './mapCellTargets';
import type { Provenance, ReflowReport, DragAlternativeReport } from './diagnostics';
import type { Resolution, ResolutionScope } from './resolutionLedger';
import { mk, resetIndexes, first } from './testUtil';

const CONTEXT: RunContext = {
  branch: 'michael/p3-frontend', commitSha: '2700a904178f707b6439ab1935d06d82eb2928cc',
  treeClean: true, dataMode: 'msw-mock', projectName: 'a11y-chromium-V1-320x640',
  browserName: 'chromium', browserVersion: '131.0',
  engine: 'Blink', platform: 'linux', viewportLabel: 'V1-320x640', stateLabel: 'cell-selected',
  cameraLabel: 'initial-z12',
  dependencyVersions: { 'maplibre-gl': '4.7.1', 'react-map-gl': '7.1.9' },
  inputHashes: { 'package-lock.json': 'sha256:test' }
};
const PROVENANCE: Provenance = {
  url: 'http://localhost:5173/', timestamp: '2026-07-26T09:00:00.000Z',
  innerWidth: 320, innerHeight: 640, devicePixelRatio: 2, colorScheme: 'light',
  reducedMotion: false, forcedColors: false, touchPoints: 5, hasTouch: true,
  documentLang: 'en-GB', title: 'BRERC species distribution', userAgent: 'test'
};
const REFLOW: ReflowReport = {
  innerWidth: 320, clientWidth: 320, scrollWidth: 320, rootHorizontalScroll: false,
  rootOverflowSuppressed: false, candidates: [], inScrollRegions: [], clippedTableCells: [],
  note: 'n/a'
};
const DRAG: DragAlternativeReport = {
  canvasTouchAction: 'pan-x pan-y', canvasTabIndex: '0', canvasRole: 'region',
  canvasAriaLabel: 'Map', containerClasses: 'maplibregl-canvas-container',
  cooperativeGesturesActive: true, controlButtons: [],
  declaredPanControls: [{ direction: 'north', name: 'Pan north' }],
  status: 'ok', note: 'n/a'
};
const CAMERA: CameraState = {
  zoom: 8, bearing: 0, pitch: 0, centerLng: -2.6, centerLat: 51.45,
  boundsWest: -3, boundsSouth: 51, boundsEast: -2, boundsNorth: 52,
  mapWidthPx: 320, mapHeightPx: 400, viewportWidth: 320, viewportHeight: 640,
  devicePixelRatio: 2, styleName: 'brerc', sourceIds: 'cells'
};
const cellsCollection = (widthPx: number): CellCollection => ({
  status: 'collected', reason: null, camera: CAMERA,
  counts: { canonicalSupplied: 1, collected: 1, skipped: 0, skipReasons: {},
            renderedQueried: 1, renderedNotInCanonical: [] },
  cells: [{ cellId: 'ST5872', rendered: true,
            corners: [{ x: 0, y: 0 }, { x: widthPx, y: 0 },
                      { x: widthPx, y: widthPx }, { x: 0, y: widthPx }] }]
});

const SCOPE: ResolutionScope = {
  project: CONTEXT.projectName,
  viewport: CONTEXT.viewportLabel,
  state: CONTEXT.stateLabel,
  camera: CONTEXT.cameraLabel,
  dataMode: CONTEXT.dataMode
};
const build = (targets: Parameters<typeof classifyTargets>[0], widthPx = 60,
               resolutions: Resolution[] = [],
               manual: ManualGateResults | undefined = undefined,
               reflow: ReflowReport = REFLOW,
               mapApplicable = true) => {
  const cells = assessMapCells(cellsCollection(widthPx));
  return buildEvidence({
    context: CONTEXT, provenance: PROVENANCE, reflow, dragAlternatives: DRAG,
    classification: classifyTargets(targets, { obstacles: cells.obstacles }),
    cells, mapApplicable, resolutions, scope: SCOPE,
    automated: {
      stateEntered: true,
      textSpacing: true,
      svgTextSpacing: true,
      panAlternative: true,
      axe: true
    },
    ...(manual ? { manual } : {})
  });
};

const attestation = {
  outcome: 'pass' as const,
  reviewer: 'Named accessibility reviewer',
  date: '2026-07-26',
  environment: 'Documented browser, device and assistive technology',
  evidence: 'Stored transcript, screenshots and completed manual procedure checklist.'
};
const ALL_MANUAL_PASSED: ManualGateResults = {
  screenReader: attestation,
  realDeviceTouch: attestation,
  textResize200: attestation,
  browserZoom400: attestation,
  contrastSweep: attestation,
  keyboardAndFocus: attestation,
  pointerCancellation: attestation,
  statusAnnouncements: attestation,
  orientation: attestation
};

describe('evidence bundle', () => {
  it('merges DOM and map findings into one list', () => {
    // The control sits 5px below a 60px map cell, so its 24px circle (radius 12)
    // intersects the cell: this exercises the cross-surface obstacle path.
    resetIndexes();
    const e = build([mk(0, 65, 10, 10)]);
    expect(e.findings.some(f => f.kind === 'target-undersized')).toBe(true);
    expect(e.findings.some(f => f.kind.startsWith('map-'))).toBe(true);
  });
  it('feeds map cells into the DOM spacing calculation as obstacles', () => {
    resetIndexes();
    const near = build([mk(0, 65, 10, 10)]);
    expect(near.domTargets.obstacleCount).toBe(1);
    expect(near.domTargets.rescuedBySpacing).toBe(0);      // the cell blocks the rescue

    resetIndexes();
    const far = build([mk(0, 500, 10, 10)]);
    expect(far.domTargets.rescuedBySpacing).toBe(1);       // same control, cell out of range
  });
  it('records the full run context for reproducibility', () => {
    resetIndexes();
    const e = build([mk(0, 500, 44, 44)]);
    expect(e.context.commitSha).toBe('2700a904178f707b6439ab1935d06d82eb2928cc');
    expect(e.context.viewportLabel).toBe('V1-320x640');
    expect(e.provenance.devicePixelRatio).toBe(2);
    expect(e.mapCells.camera?.styleName).toBe('brerc');
  });
  it('refuses approval while anything is unresolved', () => {
    resetIndexes();
    const e = build([mk(0, 500, 10, 10)]);
    expect(e.releaseGatesPassed).toBe(false);
    expect(e.blockers.release.length).toBeGreaterThan(0);
  });
  it('a missing manual gate blocks release, but not automated CI', () => {
    resetIndexes();
    const e = build([mk(0, 500, 44, 44)]);
    expect(e.gates.release.manual.screenReader.status).toBe('not-assessed');
    expect(e.automatedGatesPassed).toBe(true);
    expect(e.releaseGatesPassed).toBe(false);
  });
  it('a clean ledger alone is not approval', () => {
    resetIndexes();
    const dry = build([mk(0, 500, 44, 44)]);
    const resolutions: Resolution[] = dry.findings.map(f => ({
      findingId: f.id, fingerprint: f.fingerprint, outcome: 'dismissed' as const,
      reviewer: 'Michael Samuel', date: '2026-07-26',
      justification: 'Reviewed against the rendered dashboard at this zoom; hit area confirmed.',
      scope: SCOPE
    }));
    resetIndexes();
    const e = build([mk(0, 500, 44, 44)], 60, resolutions);
    expect(e.gates.release.ledgerResolved.status).toBe('pass');
    expect(e.releaseGatesPassed).toBe(false);
  });
  it('one failing gate is enough to block', () => {
    resetIndexes();
    const e = build([mk(0, 500, 44, 44)], 60, [], {
      ...ALL_MANUAL_PASSED,
      contrastSweep: { ...attestation, outcome: 'fail' }
    });
    expect(e.releaseGatesPassed).toBe(false);
  });
  it('approves only when the ledger is clear AND every gate is explicitly true', () => {
    resetIndexes();
    const dry = build([mk(0, 500, 44, 44)]);
    const resolutions: Resolution[] = dry.findings.map(f => ({
      findingId: f.id, fingerprint: f.fingerprint, outcome: 'dismissed' as const,
      reviewer: 'Michael Samuel', date: '2026-07-26',
      justification: 'Reviewed against the rendered dashboard at this zoom; hit area confirmed.',
      scope: SCOPE
    }));
    resetIndexes();
    const signed = build([mk(0, 500, 44, 44)], 60, resolutions, ALL_MANUAL_PASSED);
    expect(signed.ledger.unresolved).toHaveLength(0);
    expect(signed.blockers.automated).toHaveLength(0);
    expect(signed.blockers.release).toHaveLength(0);
    expect(signed.automatedGatesPassed).toBe(true);
    expect(signed.releaseGatesPassed).toBe(true);
  });
  it('carries the reflow and drag diagnostics into the artefact', () => {
    resetIndexes();
    const e = build([mk(0, 500, 44, 44)]);
    expect(e.reflow.rootHorizontalScroll).toBe(false);
    expect(first(e.dragAlternatives.declaredPanControls).direction).toBe('north');
  });
  it('counts passed and rescued DOM targets', () => {
    resetIndexes();
    const e = build([mk(0, 500, 44, 44), mk(200, 500, 44, 44)]);
    expect(e.domTargets.total).toBe(2);
    expect(e.domTargets.passed).toBe(2);
  });
  it('reports map status and raw minimum dimensions', () => {
    resetIndexes();
    const e = build([mk(0, 500, 44, 44)], 23.96);
    expect(e.mapCells.status).toBe('measured');
    expect(e.mapCells.minWidthPx).toBeCloseTo(23.96, 6);
  });
  it('models an expected absent map as not applicable rather than as a failure', () => {
    resetIndexes();
    const e = build([mk(0, 500, 44, 44)], 60, [], undefined, REFLOW, false);
    expect(e.mapCells.status).toBe('not-applicable');
    expect(e.gates.automated.mapCollectionConclusive.status).toBe('not-applicable');
    expect(e.automatedGatesPassed).toBe(true);
  });
  it('includes root scrolling and suppressed overflow in the evidence verdict', () => {
    resetIndexes();
    const badReflow: ReflowReport = {
      ...REFLOW,
      rootHorizontalScroll: true,
      rootOverflowSuppressed: true
    };
    const e = build([mk(0, 500, 44, 44)], 60, [], ALL_MANUAL_PASSED, badReflow);
    expect(e.gates.automated.reflowClean.status).toBe('fail');
    expect(e.automatedGatesPassed).toBe(false);
    expect(e.releaseGatesPassed).toBe(false);
  });
});

describe('severity summary', () => {
  it('groups findings by severity', () => {
    resetIndexes();
    const e = build([mk(0, 500, 10, 10)]);
    const s = summariseBySeverity(e.findings);
    expect(Object.values(s).reduce((a, b) => a + b, 0)).toBe(e.findings.length);
  });
  it('returns an empty object for no findings', () => {
    expect(summariseBySeverity([])).toEqual({});
  });
});
