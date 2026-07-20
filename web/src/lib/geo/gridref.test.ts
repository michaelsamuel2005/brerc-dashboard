import { describe, expect, it } from "vitest";
import { gridRefPrecisionMetres, precisionLabel } from "./gridref";

describe("gridRefPrecisionMetres", () => {
  it("parses each OS resolution correctly", () => {
    expect(gridRefPrecisionMetres("ST59")).toBe(10000);       // 2 digits -> 10km
    expect(gridRefPrecisionMetres("ST5972")).toBe(1000);      // 4-figure -> 1km
    expect(gridRefPrecisionMetres("ST 5972")).toBe(1000);     // whitespace tolerated
    expect(gridRefPrecisionMetres("ST597727")).toBe(100);     // 6-figure -> 100m
    expect(gridRefPrecisionMetres("ST59722885")).toBe(10);    // 8-figure -> 10m
    expect(gridRefPrecisionMetres("ST6674588734")).toBe(1);   // 10-figure -> 1m
  });

  it("returns null for unparseable or odd-digit refs", () => {
    expect(gridRefPrecisionMetres("not-a-ref")).toBeNull();
    expect(gridRefPrecisionMetres("ST597")).toBeNull();       // odd number of digits
  });
});

describe("precisionLabel", () => {
  it("labels metres and kilometres", () => {
    expect(precisionLabel(1000)).toBe("1 km square");
    expect(precisionLabel(100)).toBe("100 m square");
  });
});
