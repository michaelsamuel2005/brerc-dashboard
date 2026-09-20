import { describe, expect, it } from "vitest";
import fixture from "../../../../contracts/etl-browser-contract-fixture.json";
import { CellDistributionSchema, RecordPageSchema } from "./schemas";

describe("actual Python ETL payloads match the browser contract", () => {
  it("parses the verification-available payload", () => {
    const scenario = fixture.verifiedAvailable;
    expect(scenario.verificationAvailable).toBe(true);
    const cells = CellDistributionSchema.parse(scenario.cells);
    expect(cells.verificationAvailable).toBe(true);
    expect(cells.cells).not.toHaveLength(0);
    const records = RecordPageSchema.parse(scenario.records);
    expect(records.items).not.toHaveLength(0);
    expect(records.publication.fields.verification).toBe(true);
    expect(records.items.every((record) => record.verified !== undefined)).toBe(true);
  });

  it("omits rather than invents verification counts when the source has no verdict field", () => {
    const scenario = fixture.verifiedUnavailable;
    expect(scenario.verificationAvailable).toBe(false);
    const distribution = CellDistributionSchema.parse(scenario.cells);
    expect(distribution.verificationAvailable).toBe(false);
    expect(distribution.cells).not.toHaveLength(0);
    for (const cell of distribution.cells) {
      expect(cell).not.toHaveProperty("verifiedCount");
    }
    const records = RecordPageSchema.parse(scenario.records);
    expect(records.items).not.toHaveLength(0);
    expect(records.publication.fields.verification).toBe(false);
    for (const record of records.items) {
      expect(record).not.toHaveProperty("verified");
    }
  });
});
