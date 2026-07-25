// ---------------------------------------------------------------------------
// C2 CONTRACT GATE. Fails CI if any PII / precise-coordinate / sensitivity field can
// enter a parsed client payload, or if a record's gridRef is finer than its stated
// precision. This is the client-side net; server-side generalisation is the fix (A3/A4).
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { gridRefPrecisionMetres } from "../geo/gridref";
import {
  CellDistributionSchema,
  normaliseVerified,
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
  cells: CellDistributionSchema.parse(cellsFixture),
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

  it("classifies a negative verdict as rejected, never accepted (adversarial phrasing)", () => {
    expect(normaliseVerified("Rejected – not accepted")).toBe("rejected");
    expect(normaliseVerified("rejected (was accepted in error)")).toBe("rejected");
    expect(normaliseVerified("Accepted – correct")).toBe("accepted");
    expect(normaliseVerified("Accepted – considered correct")).toBe("accepted");
    expect(normaliseVerified("Unconfirmed")).toBe("unconfirmed");
    expect(normaliseVerified("Pending review")).toBe("unconfirmed");
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

  it("REJECTS a record finer than the 100 m public floor (runtime, not just fixture)", () => {
    const hostile = structuredClone(recordsFixture) as Record<string, unknown>;
    const items = hostile.items as Array<Record<string, unknown>>;
    if (items[0]) {
      items[0].gridRef = "ST59722885"; // 10 m reference
      items[0].precisionMetres = 10;
    }
    expect(() => RecordPageSchema.parse(hostile)).toThrow();
  });

  it("REJECTS a record whose gridRef precision disagrees with precisionMetres", () => {
    const hostile = structuredClone(recordsFixture) as Record<string, unknown>;
    const items = hostile.items as Array<Record<string, unknown>>;
    if (items[0]) {
      items[0].gridRef = "ST597728"; // 100 m
      items[0].precisionMetres = 1000; // claims 1 km — inconsistent
    }
    expect(() => RecordPageSchema.parse(hostile)).toThrow();
  });

  it("REJECTS a non-https (javascript:) attribution URL", () => {
    const hostile = structuredClone(provenanceFixture) as Record<string, unknown>;
    const attrs = hostile.attributions as Array<Record<string, unknown>>;
    if (attrs[0]) attrs[0].url = "javascript:alert(1)";
    expect(() => ProvenanceSchema.parse(hostile)).toThrow();
  });

  // Wire-level C2 gate for the MAP data path: cells are ID + counts (geometry is derived
  // client-side), so the ID must match the precision and no forbidden field can enter.
  it("REJECTS a grid cell carrying a forbidden property (map path)", () => {
    const hostile = structuredClone(cellsFixture) as Record<string, unknown>;
    const cells = hostile.cells as Array<Record<string, unknown>>;
    if (cells[0]) cells[0].Eastings = 359000;
    expect(() => CellDistributionSchema.parse(hostile)).toThrow();
  });

  it("REJECTS a cell whose cellId precision disagrees with precisionMetres (anti-spoof)", () => {
    const hostile = structuredClone(cellsFixture) as Record<string, unknown>;
    const cells = hostile.cells as Array<Record<string, unknown>>;
    if (cells[0]) cells[0].cellId = "ST585725"; // a 100 m ref still claiming precisionMetres 1000
    expect(() => CellDistributionSchema.parse(hostile)).toThrow();
  });

  it("REJECTS a cell finer than the 100 m public floor (map path)", () => {
    const hostile = structuredClone(cellsFixture) as Record<string, unknown>;
    const cells = hostile.cells as Array<Record<string, unknown>>;
    if (cells[0]) {
      cells[0].cellId = "ST59722885"; // 10 m ref
      cells[0].precisionMetres = 10;
    }
    expect(() => CellDistributionSchema.parse(hostile)).toThrow();
  });
});
