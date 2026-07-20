// ---------------------------------------------------------------------------
// C2 CONTRACT GATE. Fails CI if any PII / precise-coordinate / sensitivity field can
// enter a parsed client payload, or if a record's gridRef is finer than its stated
// precision. This is the client-side net; server-side generalisation is the fix (A3/A4).
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { gridRefPrecisionMetres } from "../geo/gridref";
import {
  CellCollectionSchema,
  HealthSchema,
  ProvenanceSchema,
  RecordPageSchema,
  SpeciesDetailSchema,
  SpeciesListPageSchema,
  SummarySchema,
} from "./schemas";
import {
  cellsFixture,
  healthFixture,
  provenanceFixture,
  recordsFixture,
  speciesDetailFixture,
  speciesListFixture,
  summaryFixture,
} from "../../test/fixtures";

const FORBIDDEN = new Set([
  "recorder1", "bliss", "eastings", "northings", "comments", "sensitivity", "precisegridref", "precisedate",
]);

function collectKeys(value: unknown, acc: string[]): string[] {
  if (Array.isArray(value)) {
    for (const item of value) collectKeys(item, acc);
  } else if (value !== null && typeof value === "object") {
    for (const [key, val] of Object.entries(value)) {
      acc.push(key);
      collectKeys(val, acc);
    }
  }
  return acc;
}

const parsed = {
  health: HealthSchema.parse(healthFixture),
  species: SpeciesListPageSchema.parse(speciesListFixture),
  speciesDetail: SpeciesDetailSchema.parse(speciesDetailFixture),
  records: RecordPageSchema.parse(recordsFixture),
  cells: CellCollectionSchema.parse(cellsFixture),
  summary: SummarySchema.parse(summaryFixture),
  provenance: ProvenanceSchema.parse(provenanceFixture),
};

describe("C2 contract gate", () => {
  it("every parsed payload validates and carries NO forbidden field", () => {
    for (const [name, payload] of Object.entries(parsed)) {
      const keys = collectKeys(payload, []).map((k) => k.toLowerCase());
      const leaked = keys.filter((k) => FORBIDDEN.has(k));
      expect(leaked, `forbidden key(s) in ${name}`).toEqual([]);
    }
  });

  it("record gridRef precision EQUALS the stated precisionMetres (never finer)", () => {
    for (const row of parsed.records.items) {
      expect(gridRefPrecisionMetres(row.gridRef)).toBe(row.precisionMetres);
    }
  });

  it("normalises the raw verified value (handles the en-dash) into an enum", () => {
    expect(parsed.records.items[0]?.verified).toBe("accepted");
  });

  it("REJECTS a payload carrying a sensitivity marker", () => {
    const hostile = { ...healthFixture, sensitivity: "high" };
    expect(() => HealthSchema.parse(hostile)).toThrow();
  });

  it("REJECTS a record carrying precise Eastings/Northings", () => {
    const hostile = structuredClone(recordsFixture) as Record<string, unknown>;
    const items = hostile.items as Array<Record<string, unknown>>;
    if (items[0]) {
      items[0].Eastings = 366745;
      items[0].Northings = 188734;
    }
    expect(() => RecordPageSchema.parse(hostile)).toThrow();
  });

  it("REJECTS malformed data loudly (missing required fields)", () => {
    expect(() => SpeciesListPageSchema.parse({ items: [], page: 1 })).toThrow();
  });
});
