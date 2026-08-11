// Map configuration for the distribution map. Kept out of the component so the values
// (basemap, colour ramp, zoom range) are testable and centralised.
import type { StyleSpecification, ExpressionSpecification } from "maplibre-gl";
import type { LayerProps } from "react-map-gl/maplibre";

// A no-key light basemap (CARTO Voyager raster). Clean cartography that lets the green
// data cells stand out — the same family the mid-review prototype validated.
export const MAP_STYLE: StyleSpecification = {
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

// Framed on the demo cells (south Bristol). Cells are always drawn at their true 1 km
// extent, so zoom only magnifies them — MAX_ZOOM is a basemap-detail bound, not an
// honesty device (the honesty is that we draw squares, never points).
export const INITIAL_VIEW = { longitude: -2.585, latitude: 51.454, zoom: 12 };
export const MAX_ZOOM = 14;

// Colour-blind-safe sequential green ramp. Meaning is ALSO carried by the legend labels.
export const CELL_COLOURS: readonly [string, string, string, string] = ["#cfe8c9", "#8fcf93", "#3f9e63", "#1c6b40"];
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
  paint: { "fill-color": cellColourExpression, "fill-opacity": 0.72 },
};

export const cellsLineLayer: LayerProps = {
  id: "cells-line",
  type: "line",
  paint: { "line-color": "#0e4a2c", "line-width": 0.6, "line-opacity": 0.55 },
};

export const LEGEND_BANDS: readonly { colour: string; label: string }[] = [
  { colour: CELL_COLOURS[0], label: "1–5 records" },
  { colour: CELL_COLOURS[1], label: "6–20 records" },
  { colour: CELL_COLOURS[2], label: "21–50 records" },
  { colour: CELL_COLOURS[3], label: "51+ records" },
];
