import { describe, expect, it } from "vitest";
import {
  CELL_BOUNDARY_COLOURS,
  CELL_BREAKS,
  CELL_COLOURS,
  LEGEND_BANDS,
  MAX_ZOOM,
  MIN_ZOOM,
  cellsFillLayer,
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

/** Representative light-basemap tones the fills are drawn over. */
const BASEMAP_TONES = ["#f8f4f0", "#cfe3ee", "#e6e1dc"] as const;

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

  it("keeps every cell boundary at 3:1 against its own fill (WCAG 1.4.11)", () => {
    // These cells are clickable, so the boundary is what identifies each one as
    // a distinct object. A single boundary colour cannot clear 3:1 across a
    // sequential ramp, which is why the boundary steps to white on the darkest
    // band — the previous dark-on-dark line measured 1.08:1 and was effectively
    // invisible on exactly the cells with the most records.
    const fillPaint = cellsFillLayer.paint as Record<string, unknown>;
    const fillOpacity = fillPaint["fill-opacity"] as number;
    const linePaint = cellsLineLayer.paint as Record<string, unknown>;
    expect(linePaint["line-opacity"]).toBe(1);

    for (const tone of BASEMAP_TONES) {
      CELL_COLOURS.forEach((fill, index) => {
        const rendered = over(rgb(fill), fillOpacity, rgb(tone));
        const boundary = rgb(CELL_BOUNDARY_COLOURS[index]!);
        expect(
          contrast(boundary, rendered),
          `band ${index} boundary over ${tone}`,
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
