import {
  INITIAL_VIEW,
  MAX_ZOOM,
  MIN_ZOOM
} from '../src/features/map/mapConstants';

/**
 * Application contract for the executable accessibility suite.
 *
 * The runner imports this file; these are not documentation-only guesses. State-entry
 * assertions make a stale selector fail before any geometry is treated as evidence.
 */

export const A11Y_STATES = [
  'default',
  'attribution-expanded',
  'chart-table-expanded',
  'cell-selected',
  'year-selected',
  'loading',
  'empty',
  'error'
] as const;

export type A11yState = (typeof A11Y_STATES)[number];

export const A11Y_CONFIG = {
  dataMode: 'msw-mock' as const,
  scenarioCookie: 'brerc-a11y-scenario',
  map: {
    global: '__brercMap',
    canonicalCellsGlobal: '__brercCanonicalCells',
    cellIdProperty: 'cellId',
    selectableLayers: ['cells-fill']
  },
  selectors: {
    attributionToggle: '.maplibregl-ctrl-attrib-button',
    attributionPanel: '.maplibregl-ctrl-attrib',
    chartTableToggle: '.chart-table > summary',
    chartTable: '.chart-table',
    gridCell: '[data-a11y-pointer-target^="grid-cell-"]',
    yearControl: '.chart-table button',
    selectedCellId: '.cell-card__id',
    mapCanvas: '.maplibregl-canvas',
    panControl: (direction: string) => `[data-map-pan="${direction}"]`
  },
  statesWithoutMap: ['loading', 'empty', 'error'] as readonly A11yState[],
  cameraSchedule: [
    {
      id: `minimum-z${String(MIN_ZOOM).replace('.', '_')}`,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude] as [number, number],
      zoom: MIN_ZOOM,
      bearing: 0,
      pitch: 0
    },
    {
      id: `initial-z${String(INITIAL_VIEW.zoom).replace('.', '_')}`,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude] as [number, number],
      zoom: INITIAL_VIEW.zoom,
      bearing: 0,
      pitch: 0
    },
    {
      id: `maximum-z${String(MAX_ZOOM).replace('.', '_')}`,
      center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude] as [number, number],
      zoom: MAX_ZOOM,
      bearing: 0,
      pitch: 0
    }
  ],
  defaultCameraId: `initial-z${String(INITIAL_VIEW.zoom).replace('.', '_')}`,
  noMapCameraId: 'not-applicable',
  mapIdleTimeoutMs: 10_000
} as const;
