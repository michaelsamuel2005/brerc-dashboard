import { describe, expect, it } from "vitest";
import { gridRefCentroid, gridRefToPolygon, parseGridRef } from "./osgb";

describe("osgb grid-ref geometry", () => {
  it("parses a 1 km grid ref to its SW easting/northing and size", () => {
    expect(parseGridRef("ST5872")).toEqual({ easting: 358000, northing: 172000, size: 1000 });
  });

  it("rejects an unparseable ref", () => {
    expect(parseGridRef("not-a-ref")).toBeNull();
  });

  it("derives the WGS84 SW corner matching the authoritative (pyproj) value", () => {
    const ring = gridRefToPolygon("ST5872");
    expect(ring).not.toBeNull();
    const sw = (ring as number[][])[0] as number[];
    expect(sw[0]).toBeCloseTo(-2.605729, 4);
    expect(sw[1]).toBeCloseTo(51.445422, 4);
  });

  it("returns a closed 5-point ring", () => {
    const ring = gridRefToPolygon("ST5872") as number[][];
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[4]);
  });

  it("gives a centroid inside the square", () => {
    const c = gridRefCentroid("ST5872") as number[];
    expect(c[0]).toBeGreaterThan(-2.606);
    expect(c[0]).toBeLessThan(-2.591);
  });
});
