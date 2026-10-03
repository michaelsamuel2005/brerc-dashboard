import { describe, expect, it } from "vitest";
import {
  cellsWithinRadius,
  circleRing,
  distanceToCellMetres,
  radiusIsFinerThanData,
} from "./radius";
import { gridRefToPolygon } from "./osgb";

/** A real 1 km square from the region, via the same derivation the map uses. */
function cell(gridRef: string, precisionMetres = 1000) {
  const ring = gridRefToPolygon(gridRef);
  if (!ring) throw new Error(`fixture grid ref did not resolve: ${gridRef}`);
  return { cellId: gridRef, ring, precisionMetres };
}

const ST5872 = cell("ST5872");
const ST5972 = cell("ST5972");
const ST5873 = cell("ST5873");

/** The centre of a square, from its own derived ring. */
function centreOf(c: { ring: readonly (readonly number[])[] }): [number, number] {
  const xs = c.ring.flatMap((p) => (typeof p[0] === "number" ? [p[0]] : []));
  const ys = c.ring.flatMap((p) => (typeof p[1] === "number" ? [p[1]] : []));
  return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
}

describe("distanceToCellMetres", () => {
  it("is zero when the point is inside the square", () => {
    expect(distanceToCellMetres(ST5872, centreOf(ST5872))).toBe(0);
  });

  it("is zero anywhere inside, not only at the centre", () => {
    const [cx, cy] = centreOf(ST5872);
    // A quarter of the way toward a corner is still inside a 1 km square.
    expect(distanceToCellMetres(ST5872, [cx + 0.001, cy + 0.001])).toBe(0);
  });

  it("measures roughly a kilometre to the next square along", () => {
    const distance = distanceToCellMetres(ST5972, centreOf(ST5872));
    // Centre of one 1 km square to the near edge of its neighbour: about 500 m.
    expect(distance).toBeGreaterThan(400);
    expect(distance).toBeLessThan(600);
  });

  it("grows with separation", () => {
    const near = distanceToCellMetres(ST5972, centreOf(ST5872)) ?? 0;
    const far = distanceToCellMetres(cell("ST6572"), centreOf(ST5872)) ?? 0;
    expect(far).toBeGreaterThan(near);
  });

  it("returns null for a cell with no geometry rather than a misleading zero", () => {
    expect(distanceToCellMetres({ ring: [] }, [-2.6, 51.45])).toBeNull();
  });
});

describe("cellsWithinRadius", () => {
  const all = [ST5872, ST5972, ST5873, cell("ST6572")];
  const centre = centreOf(ST5872);

  it("returns the square the point is in, even for a tiny radius", () => {
    // The important honesty case: asking a 50 m question of 1 km data cannot narrow
    // the answer below 1 km, and the whole square must come back.
    const hits = cellsWithinRadius(all, centre, 50);
    expect(hits.map((h) => h.cellId)).toEqual(["ST5872"]);
  });

  it("includes squares the circle merely overlaps, not only those it contains", () => {
    const hits = cellsWithinRadius(all, centre, 800);
    expect(hits.map((h) => h.cellId).sort()).toEqual(["ST5872", "ST5873", "ST5972"]);
  });

  it("excludes squares beyond the radius", () => {
    expect(cellsWithinRadius(all, centre, 800).map((h) => h.cellId)).not.toContain("ST6572");
  });

  it("orders nearest first, with the containing square at zero", () => {
    const hits = cellsWithinRadius(all, centre, 10_000);
    expect(hits[0]?.cellId).toBe("ST5872");
    expect(hits[0]?.distanceMetres).toBe(0);
    const distances = hits.map((h) => h.distanceMetres);
    expect(distances).toEqual([...distances].sort((a, b) => a - b));
  });

  it("returns nothing for a non-positive or non-finite radius", () => {
    for (const radius of [0, -1, Number.NaN]) {
      expect(cellsWithinRadius(all, centre, radius)).toEqual([]);
    }
  });

  it("returns nothing when there are no cells", () => {
    expect(cellsWithinRadius([], centre, 5000)).toEqual([]);
  });

  it("does not mutate the input array or its cells", () => {
    const snapshot = JSON.stringify(all);
    cellsWithinRadius(all, centre, 5000);
    expect(JSON.stringify(all)).toBe(snapshot);
  });
});

describe("radiusIsFinerThanData", () => {
  it("is true when the question is sharper than the answer can be", () => {
    expect(radiusIsFinerThanData(100, [ST5872])).toBe(true);
    expect(radiusIsFinerThanData(999, [ST5872])).toBe(true);
  });

  it("is false once the radius reaches the coarsest square", () => {
    expect(radiusIsFinerThanData(1000, [ST5872])).toBe(false);
    expect(radiusIsFinerThanData(5000, [ST5872])).toBe(false);
  });

  it("judges against the COARSEST square, not the finest", () => {
    // A mixed release must not be described as precise because one square happens to be.
    const mixed = [{ precisionMetres: 100 }, { precisionMetres: 1000 }];
    expect(radiusIsFinerThanData(500, mixed)).toBe(true);
  });

  it("is false with nothing to compare against", () => {
    expect(radiusIsFinerThanData(100, [])).toBe(false);
  });
});

describe("circleRing", () => {
  it("closes the ring", () => {
    const ring = circleRing([-2.6, 51.45], 500);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
  });

  it("draws every vertex at the requested radius", () => {
    const centre: [number, number] = [-2.6, 51.45];
    const radius = 500;
    for (const vertex of circleRing(centre, radius, 16)) {
      // Each vertex sits on the circle, so its distance from the centre is the radius.
      const distance = distanceToCellMetres({ ring: [vertex] }, centre) ?? 0;
      expect(distance).toBeCloseTo(radius, 0);
    }
  });

  it("scales with the radius", () => {
    const centre: [number, number] = [-2.6, 51.45];
    const small = circleRing(centre, 100, 8);
    const large = circleRing(centre, 1000, 8);
    const spread = (ring: [number, number][]) =>
      Math.max(...ring.map((p) => p[0])) - Math.min(...ring.map((p) => p[0]));
    expect(spread(large)).toBeGreaterThan(spread(small) * 9);
  });
});
