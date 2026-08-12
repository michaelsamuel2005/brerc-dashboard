import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

import {
  A11Y_CONFIG,
  A11Y_STATES,
  type A11yState
} from './a11y.config';
import { A11Y_PROJECT_NAMES } from './playwright.viewports';
import { collectTargets } from '../src/lib/a11y/collectTargets';
import { classifyTargets } from '../src/lib/a11y/targetSpacing';
import {
  assessMapCells,
  collectMapCellGeometry,
  type CellAssessment,
  type CollectionCounts
} from '../src/lib/a11y/mapCellTargets';
import {
  collectDragAlternatives,
  collectProvenance,
  collectReflow,
  toggleDomTextSpacing,
  toggleSvgTextSpacing
} from '../src/lib/a11y/diagnostics';
import {
  buildEvidence,
  summariseBySeverity,
  type RunContext
} from '../src/lib/a11y/evidence';
import { parseManualGateFile } from '../src/lib/a11y/manualGates';
import {
  parseResolutionLedger,
  type ResolutionScope,
  type ResolutionScopeVocabulary
} from '../src/lib/a11y/resolutionLedger';

const BASE_URL = 'http://127.0.0.1:4173';
const EVIDENCE_DIR = join(process.cwd(), 'test-results', 'a11y-evidence');
const DATA_MODE = A11Y_CONFIG.dataMode;

type Camera = (typeof A11Y_CONFIG.cameraSchedule)[number];

const EMPTY_COUNTS: CollectionCounts = {
  canonicalSupplied: 0,
  collected: 0,
  skipped: 0,
  skipReasons: {},
  renderedQueried: 0,
  renderedMissingCellId: 0,
  renderedNotInCanonical: []
};

function noMapAssessment(reason: string): CellAssessment {
  return {
    status: 'inconclusive',
    reason,
    camera: null,
    counts: EMPTY_COUNTS,
    cellsMeasured: 0,
    minWidthPx: null,
    minHeightPx: null,
    cells: [],
    findings: [],
    obstacles: [],
    caveats: []
  };
}

function gitInfo(): Pick<RunContext, 'branch' | 'commitSha' | 'treeClean'> {
  const run = (args: readonly string[]): string => {
    try {
      return execFileSync('git', args, {
        cwd: process.cwd(),
        encoding: 'utf8'
      }).trim();
    } catch {
      return 'unknown';
    }
  };
  const status = run(['status', '--porcelain']);
  return {
    branch: run(['rev-parse', '--abbrev-ref', 'HEAD']),
    commitSha: run(['rev-parse', 'HEAD']),
    treeClean: status !== 'unknown' && status === ''
  };
}

function dependencyVersions(): Record<string, string> {
  const lock = JSON.parse(
    readFileSync(join(process.cwd(), 'package-lock.json'), 'utf8')
  ) as {
    packages?: Record<string, { version?: string }>;
  };
  const wanted = [
    'react',
    'maplibre-gl',
    'react-map-gl',
    'recharts',
    '@playwright/test',
    'axe-core'
  ];
  return Object.fromEntries(wanted.map(name => {
    const version = lock.packages?.[`node_modules/${name}`]?.version ?? 'absent';
    return [name, version];
  }));
}

function sha256(path: string): string {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function inputHashes(): Record<string, string> {
  const files = [
    'package-lock.json',
    'e2e/a11y.config.ts',
    'e2e/a11y-resolutions.json',
    'e2e/a11y-manual-results.json',
    'src/test/fixtures/index.ts'
  ];
  return Object.fromEntries(files.map(file => [
    file,
    `sha256:${sha256(join(process.cwd(), file))}`
  ]));
}

function allowedScopes(): ResolutionScopeVocabulary {
  const scopes: ResolutionScope[] = [];
  for (const project of A11Y_PROJECT_NAMES) {
    const viewport = /(\d+x\d+)$/.exec(project)?.[1];
    if (!viewport) throw new Error(`Project name lacks viewport identity: ${project}`);
    for (const state of A11Y_STATES) {
      const camera = A11Y_CONFIG.statesWithoutMap.includes(state)
        ? A11Y_CONFIG.noMapCameraId
        : A11Y_CONFIG.defaultCameraId;
      scopes.push({ project, viewport, state, camera, dataMode: DATA_MODE });
    }
    for (const camera of A11Y_CONFIG.cameraSchedule) {
      scopes.push({
        project,
        viewport,
        state: 'default',
        camera: camera.id,
        dataMode: DATA_MODE
      });
    }
  }
  return {
    projects: A11Y_PROJECT_NAMES,
    viewports: [...new Set(scopes.map(scope => scope.viewport))],
    states: A11Y_STATES,
    cameras: [
      A11Y_CONFIG.noMapCameraId,
      ...A11Y_CONFIG.cameraSchedule.map(camera => camera.id)
    ],
    dataModes: [DATA_MODE],
    scopes
  };
}

function loadResolutions() {
  const raw = JSON.parse(
    readFileSync(join(process.cwd(), 'e2e', 'a11y-resolutions.json'), 'utf8')
  ) as unknown;
  return parseResolutionLedger(raw, allowedScopes());
}

function loadManualResults() {
  const raw = JSON.parse(
    readFileSync(join(process.cwd(), 'e2e', 'a11y-manual-results.json'), 'utf8')
  ) as unknown;
  return parseManualGateFile(raw);
}

async function prepareScenario(page: Page, state: A11yState): Promise<void> {
  await page.context().clearCookies();
  if (state === 'loading' || state === 'empty' || state === 'error') {
    await page.context().addCookies([{
      name: A11Y_CONFIG.scenarioCookie,
      value: state,
      url: BASE_URL
    }]);
  }
}

async function waitForMapReady(page: Page): Promise<void> {
  await expect.poll(async () => page.evaluate((config) => {
    const globals = window as unknown as Record<string, unknown>;
    const map = globals[config.mapGlobal] as {
      isStyleLoaded?: () => boolean;
      getLayer?: (id: string) => unknown;
    } | undefined;
    return Boolean(
      map?.isStyleLoaded?.() &&
      config.layers.every(layer => Boolean(map.getLayer?.(layer)))
    );
  }, {
    mapGlobal: A11Y_CONFIG.map.global,
    layers: A11Y_CONFIG.map.selectableLayers
  }), {
    timeout: A11Y_CONFIG.mapIdleTimeoutMs,
    message: 'Map test adapter/style/layers never became ready'
  }).toBe(true);

  // Wait for one actual render without depending on third-party raster tiles becoming idle.
  await page.evaluate(async (mapGlobal) => {
    const globals = window as unknown as Record<string, unknown>;
    const map = globals[mapGlobal] as {
      once: (event: string, callback: () => void) => void;
      triggerRepaint: () => void;
    };
    await new Promise<void>((resolve) => {
      const timeout = window.setTimeout(resolve, 2000);
      map.once('render', () => {
        window.clearTimeout(timeout);
        resolve();
      });
      map.triggerRepaint();
    });
  }, A11Y_CONFIG.map.global);
}

async function applyCamera(page: Page, camera: Camera): Promise<void> {
  await page.evaluate(({ mapGlobal, value }) => {
    const globals = window as unknown as Record<string, unknown>;
    const map = globals[mapGlobal] as {
      jumpTo: (options: {
        center: [number, number];
        zoom: number;
        bearing: number;
        pitch: number;
      }) => void;
      triggerRepaint: () => void;
    };
    map.jumpTo(value);
    map.triggerRepaint();
  }, {
    mapGlobal: A11Y_CONFIG.map.global,
    value: {
      center: camera.center,
      zoom: camera.zoom,
      bearing: camera.bearing,
      pitch: camera.pitch
    }
  });

  await expect.poll(async () => page.evaluate((mapGlobal) => {
    const globals = window as unknown as Record<string, unknown>;
    const map = globals[mapGlobal] as {
      getZoom: () => number;
      getBearing: () => number;
      getPitch: () => number;
    };
    return [map.getZoom(), map.getBearing(), map.getPitch()];
  }, A11Y_CONFIG.map.global), {
    timeout: A11Y_CONFIG.mapIdleTimeoutMs
  }).toEqual([camera.zoom, camera.bearing, camera.pitch]);

  await waitForMapReady(page);
}

async function enterState(page: Page, state: A11yState): Promise<void> {
  await prepareScenario(page, state);
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: /Slow-worm/ })).toBeVisible();

  switch (state) {
    case 'default':
      await expect(page.locator(A11Y_CONFIG.selectors.mapCanvas).first()).toBeVisible();
      break;
    case 'attribution-expanded': {
      await waitForMapReady(page);
      await page.locator(A11Y_CONFIG.selectors.attributionToggle).first().click();
      await expect(page.locator(A11Y_CONFIG.selectors.attributionPanel).first())
        .toHaveClass(/maplibregl-compact-show/);
      break;
    }
    case 'chart-table-expanded':
      await page.locator(A11Y_CONFIG.selectors.chartTableToggle).click();
      await expect(page.locator(A11Y_CONFIG.selectors.chartTable)).toHaveAttribute('open', '');
      break;
    case 'cell-selected': {
      const cell = page.locator(A11Y_CONFIG.selectors.gridCell).first();
      await cell.click();
      await expect(cell).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator(A11Y_CONFIG.selectors.selectedCellId)).not.toHaveText('—');
      break;
    }
    case 'year-selected': {
      await page.locator(A11Y_CONFIG.selectors.chartTableToggle).click();
      const year = page.locator(A11Y_CONFIG.selectors.yearControl).first();
      await year.click();
      await expect(year).toHaveAttribute('aria-pressed', 'true');
      break;
    }
    case 'loading':
      await expect(page.getByRole('status').filter({ hasText: /Loading the map/ }))
        .toBeVisible();
      await expect(page.locator(A11Y_CONFIG.selectors.mapCanvas)).toHaveCount(0);
      break;
    case 'empty':
      await expect(page.getByText('No mapped records for this species yet.').first())
        .toBeVisible();
      await expect(page.locator(A11Y_CONFIG.selectors.mapCanvas)).toHaveCount(0);
      break;
    case 'error':
      await expect(page.locator('.map-card [role="alert"]')).toContainText(/503|failed|error/i);
      await expect(page.locator(A11Y_CONFIG.selectors.mapCanvas)).toHaveCount(0);
      break;
  }
}

async function verifyPanAlternative(page: Page): Promise<Record<string, number>> {
  const movements: Record<string, number> = {};
  const cases = [
    { direction: 'north', axis: 'lat', sign: 1 },
    { direction: 'south', axis: 'lat', sign: -1 },
    { direction: 'east', axis: 'lng', sign: 1 },
    { direction: 'west', axis: 'lng', sign: -1 }
  ] as const;

  for (const item of cases) {
    await applyCamera(page, A11Y_CONFIG.cameraSchedule[1]);
    const before = await page.evaluate((mapGlobal) => {
      const globals = window as unknown as Record<string, unknown>;
      const map = globals[mapGlobal] as {
        getCenter: () => { lng: number; lat: number };
        getZoom: () => number;
        getBearing: () => number;
        getPitch: () => number;
      };
      const center = map.getCenter();
      return {
        lng: center.lng,
        lat: center.lat,
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch()
      };
    }, A11Y_CONFIG.map.global);

    await page.locator(A11Y_CONFIG.selectors.panControl(item.direction)).click();
    await expect.poll(async () => page.evaluate(({ mapGlobal, axis, beforeValue }) => {
      const globals = window as unknown as Record<string, unknown>;
      const map = globals[mapGlobal] as {
        getCenter: () => { lng: number; lat: number };
      };
      const delta = map.getCenter()[axis] - beforeValue;
      return Math.abs(delta) > 1e-6 ? Math.sign(delta) : 0;
    }, {
      mapGlobal: A11Y_CONFIG.map.global,
      axis: item.axis,
      beforeValue: before[item.axis]
    }), {
      timeout: 5000,
      message: `Pan ${item.direction} did not move far enough in the expected direction`
    }).toBe(item.sign);

    const after = await page.evaluate((mapGlobal) => {
      const globals = window as unknown as Record<string, unknown>;
      const map = globals[mapGlobal] as {
        getCenter: () => { lng: number; lat: number };
        getZoom: () => number;
        getBearing: () => number;
        getPitch: () => number;
      };
      const center = map.getCenter();
      return {
        lng: center.lng,
        lat: center.lat,
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch()
      };
    }, A11Y_CONFIG.map.global);
    movements[item.direction] = after[item.axis] - before[item.axis];
    expect(after.zoom).toBeCloseTo(before.zoom, 7);
    expect(after.bearing).toBeCloseTo(before.bearing, 7);
    expect(after.pitch).toBeCloseTo(before.pitch, 7);
  }
  await applyCamera(page, A11Y_CONFIG.cameraSchedule[1]);
  return movements;
}

async function spacingDiagnostics(page: Page, testInfo: TestInfo) {
  let domApplied = false;
  let svgApplied = false;
  try {
    const dom = await page.evaluate(toggleDomTextSpacing);
    domApplied = dom.applied;
    const svg = await page.evaluate(toggleSvgTextSpacing);
    svgApplied = svg.applied;
    await testInfo.attach('text-spacing-screenshot', {
      body: await page.screenshot({ fullPage: true }),
      contentType: 'image/png'
    });
    return { dom, svg };
  } finally {
    if (svgApplied) await page.evaluate(toggleSvgTextSpacing);
    if (domApplied) await page.evaluate(toggleDomTextSpacing);
  }
}

async function writeEvidence(
  page: Page,
  testInfo: TestInfo,
  state: A11yState,
  camera: Camera | null,
  mapApplicable: boolean,
  panMovements: Record<string, number> | null
): Promise<void> {
  const provenance = await page.evaluate(collectProvenance);
  const reflow = await page.evaluate(collectReflow);
  const dragAlternatives = await page.evaluate(collectDragAlternatives);
  const domTargets = await page.evaluate(collectTargets);

  const cells = mapApplicable
    ? assessMapCells(await page.evaluate(collectMapCellGeometry, {
        mapGlobal: A11Y_CONFIG.map.global,
        canonicalCellsGlobal: A11Y_CONFIG.map.canonicalCellsGlobal,
        layers: [...A11Y_CONFIG.map.selectableLayers],
        cellIdProperty: A11Y_CONFIG.map.cellIdProperty
      }))
    : noMapAssessment(`Map intentionally absent in the ${state} state.`);

  const classification = classifyTargets(domTargets, {
    obstacles: mapApplicable ? cells.obstacles : []
  });
  const spacing = await spacingDiagnostics(page, testInfo);
  const axe = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();

  const browserName = testInfo.project.use.defaultBrowserType ?? 'unknown';
  const cameraLabel = camera?.id ?? A11Y_CONFIG.noMapCameraId;
  const context: RunContext = {
    ...gitInfo(),
    dataMode: DATA_MODE,
    projectName: testInfo.project.name,
    browserName,
    browserVersion: page.context().browser()?.version() ?? 'unknown',
    engine: browserName === 'chromium'
      ? 'Blink'
      : browserName === 'firefox' ? 'Gecko' : browserName === 'webkit' ? 'WebKit' : 'unknown',
    platform: process.platform,
    viewportLabel: `${provenance.innerWidth}x${provenance.innerHeight}`,
    stateLabel: state,
    cameraLabel,
    dependencyVersions: dependencyVersions(),
    inputHashes: inputHashes()
  };
  const scope: ResolutionScope = {
    project: context.projectName,
    viewport: context.viewportLabel,
    state,
    camera: cameraLabel,
    dataMode: DATA_MODE
  };

  const evidence = buildEvidence({
    context,
    provenance,
    reflow,
    dragAlternatives,
    classification,
    cells,
    mapApplicable,
    ...(!mapApplicable
      ? { mapNotApplicableReason: `Map intentionally absent in the ${state} state.` }
      : {}),
    automated: {
      stateEntered: true,
      textSpacing: spacing.dom.clippedCandidates.length === 0,
      svgTextSpacing: spacing.svg.svgTextCount === 0
        ? 'not-applicable'
        : spacing.svg.escaping.length === 0,
      panAlternative: panMovements === null ? 'not-applicable' : true,
      axe: axe.violations.length === 0,
      textSpacingReport: spacing.dom,
      svgTextSpacingReport: spacing.svg,
      axeViolations: axe.violations.map(violation => ({
        id: violation.id,
        impact: violation.impact ?? null,
        description: violation.description,
        nodes: violation.nodes.length
      })),
      ...(panMovements ? { panMovements } : {})
    },
    resolutions: loadResolutions(),
    scope,
    manual: loadManualResults()
  });

  mkdirSync(EVIDENCE_DIR, { recursive: true });
  const slug = [
    testInfo.project.name,
    context.viewportLabel,
    state,
    cameraLabel
  ].join('__').replace(/[^a-zA-Z0-9_.-]+/g, '-');
  const json = JSON.stringify(evidence, null, 2);
  writeFileSync(join(EVIDENCE_DIR, `${slug}.json`), json, 'utf8');
  await testInfo.attach(`a11y-evidence-${slug}`, {
    body: json,
    contentType: 'application/json'
  });
  await testInfo.attach(`screenshot-${slug}`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png'
  });
  await testInfo.attach(`aria-snapshot-${slug}`, {
    body: await page.locator('body').ariaSnapshot(),
    contentType: 'text/plain'
  });

  expect(
    evidence.automatedGatesPassed,
    `Automated blockers:\n${evidence.blockers.automated.join('\n')}\n\n` +
    `Severity summary: ${JSON.stringify(summariseBySeverity(evidence.findings))}\n\n` +
    'Manual/reviewer gates are recorded separately and are not asserted by CI.'
  ).toBe(true);
}

test.describe('BRERC accessibility evidence matrix', () => {
  for (const state of A11Y_STATES) {
    test(`state: ${state}`, async ({ page }, testInfo) => {
      await enterState(page, state);
      const mapApplicable = !A11Y_CONFIG.statesWithoutMap.includes(state);
      let camera: Camera | null = null;
      let panMovements: Record<string, number> | null = null;
      if (mapApplicable) {
        await waitForMapReady(page);
        camera = A11Y_CONFIG.cameraSchedule[1];
        await applyCamera(page, camera);
        if (state === 'default') panMovements = await verifyPanAlternative(page);
      }
      await writeEvidence(
        page,
        testInfo,
        state,
        camera,
        mapApplicable,
        panMovements
      );
    });
  }

  test('camera schedule: minimum and maximum supported zoom', async ({ page }, testInfo) => {
    await enterState(page, 'default');
    await waitForMapReady(page);
    for (const camera of A11Y_CONFIG.cameraSchedule) {
      if (camera.id === A11Y_CONFIG.defaultCameraId) continue;
      await applyCamera(page, camera);
      await writeEvidence(page, testInfo, 'default', camera, true, null);
    }
  });
});
