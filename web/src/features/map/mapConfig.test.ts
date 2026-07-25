import { describe, expect, it } from "vitest";
import { CELL_BREAKS, CELL_COLOURS, LEGEND_BANDS, MAX_ZOOM, cellsFillLayer } from "./mapConfig";

describe("mapConfig", () => {
  it("caps zoom so cells never imply a false precision", () => {
    expect(MAX_ZOOM).toBeLessThanOrEqual(14);
  });

  it("has one more colour than breaks, and a labelled legend band per colour", () => {
    expect(CELL_COLOURS).toHaveLength(CELL_BREAKS.length + 1);
    expect(LEGEND_BANDS).toHaveLength(CELL_COLOURS.length);
    for (const band of LEGEND_BANDS) expect(band.label).toMatch(/record/);
  });

  it("colours cells by record count using a step expression", () => {
    const paint = cellsFillLayer.paint as Record<string, unknown> | undefined;
    const fillColor = paint?.["fill-color"];
    expect(Array.isArray(fillColor)).toBe(true);
    expect((fillColor as unknown[])[0]).toBe("step");
  });
});
