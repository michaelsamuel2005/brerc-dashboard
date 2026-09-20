import { describe, expect, it } from "vitest";
import {
  CELL_BOUNDARY_COLOURS,
  CELL_BOUNDARY_DARK,
  CELL_BOUNDARY_LIGHT,
  CELL_BREAKS,
  CELL_COLOURS,
  CELL_FILL_OPACITY,
  LEGEND_BANDS,
  MAX_ZOOM,
  MIN_ZOOM,
  cellsFillLayer,
  cellsLineCasingLayer,
  cellsLineLayer,
} from "./mapConfig";

/** sRGB relative luminance, per the WCAG definition. */
function luminance([r, g, b]: readonly [number, number, number]): number {
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function rgb(hex: string): readonly [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ] as const;
}

function contrast(a: readonly [number, number, number], b: readonly [number, number, number]): number {
  const la = luminance(a);
  const lb = luminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

/** Alpha-blend a colour over a background, as the renderer does. */
function over(
  fg: readonly [number, number, number],
  alpha: number,
  bg: readonly [number, number, number],
): readonly [number, number, number] {
  return [
    Math.round(alpha * fg[0] + (1 - alpha) * bg[0]),
    Math.round(alpha * fg[1] + (1 - alpha) * bg[1]),
    Math.round(alpha * fg[2] + (1 - alpha) * bg[2]),
  ] as const;
}

/** Representative light and dark cartographic tones the fills can cross. */
const BASEMAP_TONES = ["#000000", "#1f2933", "#6b7280", "#f8f4f0", "#cfe3ee", "#e6e1dc", "#ffffff"] as const;

describe("mapConfig", () => {
  it("caps zoom at the product-supported basemap detail", () => {
    expect(MAX_ZOOM).toBeLessThanOrEqual(14);
  });

  it("prevents zooming below the product-approved 44px cell boundary", () => {
    expect(MIN_ZOOM).toBeGreaterThanOrEqual(11.2);
    expect(MIN_ZOOM).toBeLessThan(MAX_ZOOM);
  });

  it("has one more colour than breaks, and a labelled legend band per colour", () => {
    expect(CELL_COLOURS).toHaveLength(CELL_BREAKS.length + 1);
    expect(LEGEND_BANDS).toHaveLength(CELL_COLOURS.length);
    for (const band of LEGEND_BANDS) expect(band.label).toMatch(/record/);
  });

  it("keeps the map cells highly translucent while retaining explicit boundaries", () => {
    const fillPaint = cellsFillLayer.paint as Record<string, unknown>;
    expect(fillPaint["fill-opacity"]).toBe(CELL_FILL_OPACITY);
    expect(CELL_FILL_OPACITY).toBeGreaterThanOrEqual(0.2);
    expect(CELL_FILL_OPACITY).toBeLessThanOrEqual(0.3);
  });

  it("keeps a two-tone cell edge at 3:1 across light and dark basemap tones (WCAG 1.4.11)", () => {
    // These cells are clickable, so the boundary is what identifies each one as
    // a distinct object. The boundary must clear 3:1 after each translucent
    // band is composited onto every representative basemap tone.
    const fillPaint = cellsFillLayer.paint as Record<string, unknown>;
    const fillOpacity = fillPaint["fill-opacity"] as number;
    const linePaint = cellsLineLayer.paint as Record<string, unknown>;
    const casingPaint = cellsLineCasingLayer.paint as Record<string, unknown>;
    expect(linePaint["line-opacity"]).toBe(1);
    expect(linePaint["line-color"]).toBeDefined();
    expect(casingPaint["line-color"]).toBe(CELL_BOUNDARY_LIGHT);
    expect(casingPaint["line-width"]).toBeGreaterThan(linePaint["line-width"] as number);

    for (const tone of BASEMAP_TONES) {
      CELL_COLOURS.forEach((fill, index) => {
        const rendered = over(rgb(fill), fillOpacity, rgb(tone));
        const darkEdge = rgb(CELL_BOUNDARY_DARK);
        const lightEdge = rgb(CELL_BOUNDARY_LIGHT);
        expect(
          Math.max(contrast(darkEdge, rendered), contrast(lightEdge, rendered)),
          `band ${index} two-tone edge over ${tone}`,
        ).toBeGreaterThanOrEqual(3);
      });
    }
  });

  it("has one boundary colour per band", () => {
    expect(CELL_BOUNDARY_COLOURS).toHaveLength(CELL_COLOURS.length);
  });

  it("colours cells by record count using a step expression", () => {
    const paint = cellsFillLayer.paint as Record<string, unknown> | undefined;
    const fillColor = paint?.["fill-color"];
    expect(Array.isArray(fillColor)).toBe(true);
    expect((fillColor as unknown[])[0]).toBe("step");
  });
});
