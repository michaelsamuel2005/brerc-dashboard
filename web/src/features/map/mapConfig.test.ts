import { describe, expect, it } from "vitest";
import { CELL_BREAKS, CELL_COLOURS, CELL_FILL_OPACITIES, LEGEND_BANDS, MAX_ZOOM, cellsFillLayer, cellsLineLayer } from "./mapConfig";

describe("mapConfig", () => {
  it("caps zoom so cells never imply a false precision", () => {
    expect(MAX_ZOOM).toBeLessThanOrEqual(14);
  });

  it("has one more colour than breaks, and a labelled legend band per colour", () => {
    expect(CELL_COLOURS).toHaveLength(CELL_BREAKS.length + 1);
    expect(CELL_FILL_OPACITIES).toHaveLength(CELL_COLOURS.length);
    expect(LEGEND_BANDS).toHaveLength(CELL_COLOURS.length);
    for (const band of LEGEND_BANDS) expect(band.label).toMatch(/record/);
  });

  it("uses increasingly visible density bands without obscuring the basemap", () => {
    const paint = cellsFillLayer.paint as Record<string, unknown>;
    expect(paint["fill-opacity"]).toEqual([
      "step", ["get", "recordCount"],
      CELL_FILL_OPACITIES[0], CELL_BREAKS[0], CELL_FILL_OPACITIES[1],
      CELL_BREAKS[1], CELL_FILL_OPACITIES[2], CELL_BREAKS[2], CELL_FILL_OPACITIES[3],
    ]);
    expect(CELL_FILL_OPACITIES.every((value) => value >= 0.2 && value <= 0.3)).toBe(true);
    expect([...CELL_FILL_OPACITIES].sort((a, b) => a - b)).toEqual(CELL_FILL_OPACITIES);
    expect(LEGEND_BANDS.map((band) => band.opacity)).toEqual(CELL_FILL_OPACITIES);
  });

  it("reduces cell outlines at low zoom without disabling fill selection", () => {
    const paint = cellsLineLayer.paint as Record<string, unknown>;
    expect(paint["line-width"]).toBeLessThan(1);
    expect(paint["line-opacity"]).toEqual([
      "interpolate", ["linear"], ["zoom"], 10, 0, 12, 0.25, 14, 0.45,
    ]);
    expect(cellsFillLayer.id).toBe("cells-fill");
  });

  it("colours cells by record count using a step expression", () => {
    const paint = cellsFillLayer.paint as Record<string, unknown> | undefined;
    const fillColor = paint?.["fill-color"];
    expect(Array.isArray(fillColor)).toBe(true);
    expect((fillColor as unknown[])[0]).toBe("step");
  });
});
