import { afterEach, describe, expect, it } from "vitest";
import type { Map as MapLibreMap } from "maplibre-gl";
import {
  installA11yTestAdapter,
  removeA11yTestAdapter,
} from "./a11yTestAdapter";

const map = {} as MapLibreMap;
const config = {
  map,
  canonicalCells: [
    {
      cellId: "ST5872",
      ring: [[-2.6, 51.45] as const],
    },
  ],
  selectableLayers: ["cells-fill"],
} as const;

afterEach(removeA11yTestAdapter);

describe("a11y test adapter", () => {
  it("does nothing unless the compile-time call-site guard enables it", () => {
    installA11yTestAdapter(config, false);
    expect(window.__brercMap).toBeUndefined();
    expect(window.__brercA11yBridgeReady).toBeUndefined();
  });

  it("publishes one coherent bridge when explicitly enabled", () => {
    installA11yTestAdapter(config, true);
    expect(window.__brercMap).toBe(map);
    expect(window.__brercCanonicalCells).toEqual(config.canonicalCells);
    expect(window.__brercSelectableLayers).toEqual(["cells-fill"]);
    expect(window.__brercA11yBridgeReady).toBe(true);
  });

  it("removes every published global", () => {
    installA11yTestAdapter(config, true);
    removeA11yTestAdapter();
    expect(window.__brercMap).toBeUndefined();
    expect(window.__brercCanonicalCells).toBeUndefined();
    expect(window.__brercSelectableLayers).toBeUndefined();
    expect(window.__brercA11yBridgeReady).toBeUndefined();
  });
});
