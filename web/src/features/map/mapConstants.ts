/**
 * Pure map camera constants.
 *
 * This module intentionally contains no `import.meta.env` access so it can be imported
 * by both the Vite application and Playwright's Node-side configuration.
 */
export const INITIAL_VIEW = {
  longitude: -2.585,
  latitude: 51.454,
  zoom: 12,
} as const;

// At this latitude a 1 km cell is about 50 CSS px wide at z11.25. Preventing users
// from zooming farther out keeps every selectable cell above BRERC's stricter 44 px
// target rule; the browser camera schedule measures this boundary.
export const MIN_ZOOM = 11.25;
export const MAX_ZOOM = 14;
