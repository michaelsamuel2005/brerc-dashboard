// ---------------------------------------------------------------------------
// C2 CONTRACT GATE. Fails CI if a named private/source identifier, precise-coordinate or
// sensitivity FIELD can enter a parsed payload, or if a record's gridRef is finer than its
// stated precision. It cannot detect PII embedded in an otherwise allowed text value; the
// server must construct those values from controlled policy labels. Server-side
// generalisation remains the location-safety boundary (A3/A4).
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
  "recorder1",
  "bliss",
  "easting",
  "eastings",
  "northing",
  "northings",
  "comments",
  "uniqueno",
  "recordkey",
  "sensitive",
  "sensitivity",
  "precisegridref",
  "precisedate",
]);

function normaliseFieldName(key: string): string {
  return key.normalize("NFKC").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

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
      const keys = collectKeys(payload, []).map(normaliseFieldName);
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
    for (const key of ["sensitive", "sensitivity"]) {
      const hostile = { ...healthFixture, [key]: "high" };
      expect(() => HealthSchema.parse(hostile)).toThrow();
    }
  });

  it("REJECTS every singular, plural, case and separator variant from the source", () => {
    const variants = [
      "easting",
      "Easting",
      "east_ing",
      "east-ing",
      "eastings",
      "EAST_INGS",
      "northing",
      "Northing",
      "north-ing",
      "northings",
      "NORTH INGS",
      "sensitive",
      "Sensitive",
      "sensi-tive",
      "sensitivity",
      "SENSI_TIVITY",
      "unique_no",
      "UniqueNo",
      "UNIQUE-NO",
      "RecordKey",
      "record_key",
      "RECORD-KEY",
    ];
    for (const key of variants) {
      expect(FORBIDDEN.has(normaliseFieldName(key))).toBe(true);
      const hostile = structuredClone(recordsFixture) as Record<string, unknown>;
      const items = hostile.items as Array<Record<string, unknown>>;
      if (items[0]) items[0][key] = "hostile";
      expect(() => RecordPageSchema.parse(hostile)).toThrow();
    }
  });

  it("uses exact alias matching without weakening the strict public allow-list", () => {
    for (const key of ["sensitivityPolicy", "eastingLabel", "northingLabel"]) {
      expect(FORBIDDEN.has(normaliseFieldName(key))).toBe(false);
    }

    // Not being a private-source alias does not make a new field public. The
    // response schemas remain strict and still reject an unapproved extension.
    const extra = structuredClone(recordsFixture) as Record<string, unknown>;
    const items = extra.items as Array<Record<string, unknown>>;
    if (items[0]) items[0].eastingLabel = "anything";
    expect(() => RecordPageSchema.parse(extra)).toThrow();
  });

  it("REJECTS malformed data loudly (missing required fields)", () => {
    expect(() => SpeciesListPageSchema.parse({ items: [], page: 1 })).toThrow();
  });

  it("REJECTS directory identity, facet, paging and year inconsistencies", () => {
    const invalidSlug = structuredClone(speciesListFixture);
    if (invalidSlug.items[0]) invalidSlug.items[0].slug = "Anguis fragilis";
    expect(() => SpeciesListPageSchema.parse(invalidSlug)).toThrow();

    const duplicateFacet = structuredClone(speciesListFixture);
    const firstFacet = duplicateFacet.facets.groups[0];
    if (firstFacet) duplicateFacet.facets.groups.push(firstFacet);
    expect(() => SpeciesListPageSchema.parse(duplicateFacet)).toThrow();

    const unknownGroup = structuredClone(speciesListFixture);
    if (unknownGroup.items[0]) unknownGroup.items[0].group = "not-in-facets";
    expect(() => SpeciesListPageSchema.parse(unknownGroup)).toThrow();

    const pageOverflow = structuredClone(speciesListFixture);
    pageOverflow.pageSize = 1;
    expect(() => SpeciesListPageSchema.parse(pageOverflow)).toThrow();

    const zeroWithYears = structuredClone(speciesListFixture);
    if (zeroWithYears.items[0]) zeroWithYears.items[0].recordCount = 0;
    expect(() => SpeciesListPageSchema.parse(zeroWithYears)).toThrow();

    const recordsWithoutBothYears = structuredClone(speciesListFixture);
    if (recordsWithoutBothYears.items[0]) recordsWithoutBothYears.items[0].lastYear = null;
    expect(() => SpeciesListPageSchema.parse(recordsWithoutBothYears)).toThrow();
  });

  it("REJECTS impossible species detail statistics", () => {
    const excessVerified = structuredClone(speciesDetailFixture);
    excessVerified.stats.verifiedCount = excessVerified.stats.recordCount + 1;
    expect(() => SpeciesDetailSchema.parse(excessVerified)).toThrow();

    const reversedYears = structuredClone(speciesDetailFixture);
    reversedYears.stats.yearRange = [2024, 1995];
    expect(() => SpeciesDetailSchema.parse(reversedYears)).toThrow();

    const zeroWithRange = structuredClone(speciesDetailFixture);
    zeroWithRange.stats.recordCount = 0;
    zeroWithRange.stats.verifiedCount = 0;
    expect(() => SpeciesDetailSchema.parse(zeroWithRange)).toThrow();

    const unavailableWithCount = structuredClone(speciesDetailFixture);
    unavailableWithCount.stats.verificationAvailable = false;
    expect(() => SpeciesDetailSchema.parse(unavailableWithCount)).toThrow();

    const availableWithoutCount = {
      ...structuredClone(speciesDetailFixture),
      stats: { ...speciesDetailFixture.stats, verifiedCount: null },
    };
    expect(() => SpeciesDetailSchema.parse(availableWithoutCount)).toThrow();

    const honestlyUnavailable = {
      ...structuredClone(speciesDetailFixture),
      stats: {
        ...speciesDetailFixture.stats,
        verificationAvailable: false,
        verifiedCount: null,
      },
    };
    expect(() => SpeciesDetailSchema.parse(honestlyUnavailable)).not.toThrow();
  });

  it("requires an explicit, evidence-backed species-image publication mode", () => {
    const syntheticImage = {
      url: "https://images.example.test/species.jpg",
      attributionText: "Photograph: Example Naturalist",
      licence: "CC0 1.0",
      licenceUrl: "https://creativecommons.org/publicdomain/zero/1.0/",
      sourceUrl: "https://images.example.test/species",
      approvalReference: "BRERC-ASSET-0001",
      alt: "Synthetic test image of a species",
    };

    expect(() =>
      SpeciesDetailSchema.parse({ ...speciesDetailFixture, image: syntheticImage }),
    ).toThrow();
    expect(() =>
      SpeciesDetailSchema.parse({
        ...speciesDetailFixture,
        imagePublication: "approved-assets",
      }),
    ).toThrow();
    expect(() =>
      SpeciesDetailSchema.parse({
        ...speciesDetailFixture,
        imagePublication: "approved-assets",
        image: syntheticImage,
      }),
    ).not.toThrow();
    expect(() =>
      SpeciesDetailSchema.parse({
        ...speciesDetailFixture,
        imagePublication: "approved-assets",
        image: { ...syntheticImage, approvalReference: "" },
      }),
    ).toThrow();
  });

  it("never publishes an uncredited species description", () => {
    const withoutSource = structuredClone(speciesDetailFixture) as Record<string, unknown>;
    delete withoutSource.descriptionSource;
    expect(() => SpeciesDetailSchema.parse(withoutSource)).toThrow();

    const withoutDescription = structuredClone(speciesDetailFixture) as Record<string, unknown>;
    delete withoutDescription.description;
    expect(() => SpeciesDetailSchema.parse(withoutDescription)).toThrow();

    expect(() =>
      SpeciesDetailSchema.parse({
        ...speciesDetailFixture,
        descriptionSource: {
          ...speciesDetailFixture.descriptionSource,
          approvalReference: "",
        },
      }),
    ).toThrow();

    expect(() => SpeciesDetailSchema.parse(speciesDetailFixture)).not.toThrow();
  });

  it("REJECTS summaries whose yearly figures do not reconcile, but supports an honest empty result", () => {
    const wrongTotal = structuredClone(summaryFixture);
    wrongTotal.totalRecords += 1;
    expect(() => SummarySchema.parse(wrongTotal)).toThrow();

    const reversedRange = structuredClone(summaryFixture);
    if (reversedRange.yearRange) {
      reversedRange.yearRange = { min: reversedRange.yearRange.max, max: reversedRange.yearRange.min };
    }
    expect(() => SummarySchema.parse(reversedRange)).toThrow();

    expect(() =>
      SummarySchema.parse({
        totalRecords: 0,
        totalSpecies: 0,
        yearRange: null,
        recordsByYear: [],
        topGroups: [],
        coverageCaveat: "No public records match this view.",
      }),
    ).not.toThrow();
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
  it("REJECTS live-view private fields on the map path", () => {
    for (const key of ["easting", "northing", "sensitive"]) {
      const hostile = structuredClone(cellsFixture) as Record<string, unknown>;
      const cells = hostile.cells as Array<Record<string, unknown>>;
      if (cells[0]) cells[0][key] = "hostile";
      expect(() => CellDistributionSchema.parse(hostile)).toThrow();
    }
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

  it("binds cell verification counts to explicit source availability", () => {
    const unavailableWithCounts = {
      ...structuredClone(cellsFixture),
      verificationAvailable: false,
    };
    expect(() => CellDistributionSchema.parse(unavailableWithCounts)).toThrow();

    const cellsWithoutCounts = structuredClone(cellsFixture.cells) as Array<
      Partial<(typeof cellsFixture.cells)[number]>
    >;
    cellsWithoutCounts.forEach((cell) => delete cell.verifiedCount);
    const availableWithoutCounts = {
      verificationAvailable: true,
      cells: cellsWithoutCounts,
    };
    expect(() => CellDistributionSchema.parse(availableWithoutCounts)).toThrow();

    expect(() =>
      CellDistributionSchema.parse({
        verificationAvailable: false,
        cells: cellsWithoutCounts,
      }),
    ).not.toThrow();
  });
});
