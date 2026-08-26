import { describe, expect, it } from "vitest";
import {
  aggregateOnlyRecordsFixture,
  recordsFixture,
} from "../../test/fixtures";
import { RecordPageSchema } from "./schemas";

const baseRow = {
  id: "public-record-1",
  scientificName: "Anguis fragilis",
  commonName: "Slow-worm",
  gridRef: "ST585725",
  precisionMetres: 100,
  place: null,
  year: 2024,
  source: "BRERC",
};

function page(overrides: Record<string, unknown> = {}) {
  return {
    publication: {
      mode: "individual-records",
      fields: {
        abundance: false,
        place: false,
        recordType: false,
        verification: false,
      },
    },
    items: [baseRow],
    page: 1,
    pageSize: 20,
    total: 1,
    ...overrides,
  };
}

describe("record publication contract", () => {
  it("keeps both synthetic publication modes aligned with the runtime schema", () => {
    expect(RecordPageSchema.parse(recordsFixture).publication.mode).toBe("individual-records");
    expect(RecordPageSchema.parse(aggregateOnlyRecordsFixture).publication.mode).toBe(
      "aggregates-only",
    );
  });

  it("represents aggregates-only honestly without pretending the species has no data", () => {
    const parsed = RecordPageSchema.parse({
      publication: {
        mode: "aggregates-only",
        fields: {
          abundance: false,
          place: false,
          recordType: false,
          verification: false,
        },
      },
      items: [],
      page: 1,
      pageSize: 20,
      total: 0,
    });

    expect(parsed.publication.mode).toBe("aggregates-only");
  });

  it("rejects any individual row or row-field capability in aggregates-only mode", () => {
    expect(() =>
      RecordPageSchema.parse({
        publication: {
          mode: "aggregates-only",
          fields: {
            abundance: false,
            place: false,
            recordType: false,
            verification: false,
          },
        },
        items: [baseRow],
        page: 1,
        pageSize: 20,
        total: 1,
      }),
    ).toThrow();

    for (const field of ["abundance", "place", "recordType", "verification"] as const) {
      expect(() =>
        RecordPageSchema.parse({
          publication: {
            mode: "aggregates-only",
            fields: {
              abundance: field === "abundance",
              place: field === "place",
              recordType: field === "recordType",
              verification: field === "verification",
            },
          },
          items: [],
          page: 1,
          pageSize: 20,
          total: 0,
        }),
      ).toThrow();
    }
  });

  it("accepts a minimal published row with disabled values absent or null", () => {
    const parsed = RecordPageSchema.parse(
      page({ items: [{ ...baseRow, abundance: null, recordType: null }] }),
    );
    expect(parsed.items[0]?.place).toBeNull();
    expect(parsed.items[0]?.abundance).toBeNull();
    expect(parsed.items[0]?.recordType).toBeNull();
    expect(parsed.items[0]).not.toHaveProperty("verified");
  });

  it("requires enabled fields and normalises verification only when it is available", () => {
    const parsed = RecordPageSchema.parse(
      page({
        publication: {
          mode: "individual-records",
          fields: {
            abundance: true,
            place: true,
            recordType: true,
            verification: true,
          },
        },
        items: [
          {
            ...baseRow,
            place: "Bristol",
            abundance: null,
            recordType: "field observation",
            verified: "Accepted – correct",
          },
        ],
      }),
    );
    expect(parsed.items[0]?.verified).toBe("accepted");

    expect(() =>
      RecordPageSchema.parse(
        page({
          publication: {
            mode: "individual-records",
            fields: {
              abundance: true,
              place: true,
              recordType: true,
              verification: true,
            },
          },
        }),
      ),
    ).toThrow();
  });

  it("rejects non-null values that the response says are not published or unavailable", () => {
    for (const value of [
      { abundance: "3" },
      { place: "Private garden" },
      { recordType: "nest" },
      { verified: "unknown" },
    ]) {
      expect(() => RecordPageSchema.parse(page({ items: [{ ...baseRow, ...value }] }))).toThrow();
    }
  });

  it("requires the explicit publication capability and keeps it strict", () => {
    const missing = page();
    delete (missing as { publication?: unknown }).publication;
    expect(() => RecordPageSchema.parse(missing)).toThrow();

    const extra = page({
      publication: {
        mode: "individual-records",
        fields: {
          abundance: false,
          place: false,
          recordType: false,
          verification: false,
        },
        inferred: true,
      },
    });
    expect(() => RecordPageSchema.parse(extra)).toThrow();
  });
});
