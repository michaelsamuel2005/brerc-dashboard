// Map configuration for the distribution map. Kept out of the component so the values
// (basemap, colour ramp, zoom range) are testable and centralised.
import type { StyleSpecification, ExpressionSpecification } from "maplibre-gl";
import type { LayerProps } from "react-map-gl/maplibre";
export { INITIAL_VIEW, MAX_ZOOM, MIN_ZOOM } from "./mapConstants";

// A no-key light basemap (CARTO Voyager raster). The evidence runner uses a local,
// network-independent background with the same attribution semantics; third-party tile
// availability must never decide whether an accessibility test passes.
const A11Y_TEST_MODE = import.meta.env.VITE_A11Y_TEST_MODE === "true";
export const MAP_STYLE: StyleSpecification = A11Y_TEST_MODE
  ? {
      version: 8,
      sources: {
        credits: {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
          attribution: "© OpenStreetMap contributors © CARTO",
        },
      },
      layers: [{ id: "base", type: "background", paint: { "background-color": "#f2efe5" } }],
    }
  : {
      version: 8,
      sources: {
        carto: {
          type: "raster",
          tiles: ["https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors © CARTO",
        },
      },
      layers: [{ id: "base", type: "raster", source: "carto" }],
    };

// Sequential single-hue blue ramp. Single-hue sequential is the conventional
// choice for a quantitative choropleth and is safe for every common form of
// colour vision deficiency, because the bands differ in LIGHTNESS rather than
// hue. Green was also colour-blind-safe, but on a biodiversity map green fill
// reads as landcover — a user can reasonably take it for vegetation rather than
// record density. Meaning is carried by the legend labels regardless (WCAG 1.4.1).
//
// These specific values were chosen by measurement, not taste: see
// CELL_BOUNDARY_COLOURS for the WCAG 1.4.11 contrast that constrains them.
export const CELL_COLOURS: readonly [string, string, string, string] = ["#e3eef8", "#a8cee4", "#6bafd6", "#08306b"];
export const CELL_BREAKS: readonly [number, number, number] = [6, 21, 51]; // bands 1–5, 6–20, 21–50, 51+

const cellColourExpression: ExpressionSpecification = [
  "step",
  ["get", "recordCount"],
  CELL_COLOURS[0],
  CELL_BREAKS[0],
  CELL_COLOURS[1],
  CELL_BREAKS[1],
  CELL_COLOURS[2],
  CELL_BREAKS[2],
  CELL_COLOURS[3],
];

// react-map-gl <Layer> props; the source is inferred from the enclosing <Source>.
export const cellsFillLayer: LayerProps = {
  id: "cells-fill",
  type: "fill",
  // 0.88 rather than a lighter wash: the basemap still reads through, but the
  // fill is close enough to its nominal colour that the measured contrast below
  // holds. A thinner fill drifts toward the basemap and the boundary contrast
  // collapses with it.
  paint: { "fill-color": cellColourExpression, "fill-opacity": 0.88 },
};

// WCAG 1.4.11 requires 3:1 for the graphics needed to understand content, and
// these cells are also clickable, so the boundary is what identifies each one.
//
// A SINGLE boundary colour cannot satisfy that across a sequential ramp: the
// same line cannot contrast with both the lightest and the darkest band. The
// previous dark-on-dark line measured 1.08:1 against the darkest fill — a
// boundary that was, in practice, invisible exactly where cells matter most.
//
// So the boundary switches to white on the darkest band. Measured against the
// composited fill over pale land, water and road basemap tones, the worst case
// is 5.01:1. The measurement lives in mapConfig.test.ts so a future palette
// change cannot quietly drop below the threshold.
export const CELL_BOUNDARY_DARK = "#0b3d66";
export const CELL_BOUNDARY_LIGHT = "#ffffff";
export const CELL_BOUNDARY_COLOURS: readonly [string, string, string, string] = [
  CELL_BOUNDARY_DARK,
  CELL_BOUNDARY_DARK,
  CELL_BOUNDARY_DARK,
  CELL_BOUNDARY_LIGHT,
];

const cellBoundaryExpression: ExpressionSpecification = [
  "step",
  ["get", "recordCount"],
  CELL_BOUNDARY_COLOURS[0],
  CELL_BREAKS[0],
  CELL_BOUNDARY_COLOURS[1],
  CELL_BREAKS[1],
  CELL_BOUNDARY_COLOURS[2],
  CELL_BREAKS[2],
  CELL_BOUNDARY_COLOURS[3],
];

export const cellsLineLayer: LayerProps = {
  id: "cells-line",
  type: "line",
  // Fully opaque: the previous 0.55 diluted the line into the fill beneath it,
  // which is part of why the old boundary failed its contrast requirement.
  paint: { "line-color": cellBoundaryExpression, "line-width": 0.8, "line-opacity": 1 },
};

export const LEGEND_BANDS: readonly { colour: string; label: string }[] = [
  { colour: CELL_COLOURS[0], label: "1–5 records" },
  { colour: CELL_COLOURS[1], label: "6–20 records" },
  { colour: CELL_COLOURS[2], label: "21–50 records" },
  { colour: CELL_COLOURS[3], label: "51+ records" },
];
