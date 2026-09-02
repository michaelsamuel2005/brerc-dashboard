// Every advertised species must resolve through every public endpoint, and every view
// must reconcile to the same cell × year source. These are dead-link and false-total gates.
import { describe, expect, it } from "vitest";
import {
  CellDistributionSchema,
  RecordPageSchema,
  SpeciesDetailSchema,
  SpeciesListPageSchema,
  SummarySchema,
} from "../../lib/api/schemas";
import {
  YEARS,
  buildSpeciesListPage,
  cellsFor,
  cellsForSpecies,
  overallRecordsByYear,
  provenanceFixture,
  fixtureReleaseIdentity,
  recordsByYear,
  recordsByYearForSpecies,
  recordsFixture,
  recordsForSpecies,
  speciesDetailFixture,
  speciesDetailFor,
  speciesGroupFacets,
  speciesListItems,
  speciesSummaryFixture,
  speciesSummaryFor,
  summaryFixture,
} from "./index";

function totalCells(speciesId: string, year?: number) {
  return cellsForSpecies(speciesId, year).reduce((total, cell) => total + cell.recordCount, 0);
}

function parentCell(gridRef: string) {
  return gridRef.slice(0, 4) + gridRef.slice(5, 7);
}

describe("fixture coherence (single source of truth)", () => {
  it("keeps the original Slow-worm map, chart, tables and detail totals equal", () => {
    const allCells = cellsFor();
    const total = allCells.reduce((sum, cell) => sum + cell.recordCount, 0);
    expect(speciesDetailFixture.stats.recordCount).toBe(total);
    expect(recordsByYear().reduce((sum, entry) => sum + entry.count, 0)).toBe(total);
    expect(speciesSummaryFixture.totalRecords).toBe(total);

    for (const { year, count } of recordsByYear()) {
      expect(cellsFor(year).reduce((sum, cell) => sum + cell.recordCount, 0), `year ${year}`).toBe(count);
    }
    for (const cell of allCells) {
      expect(cell.verifiedCount ?? 0).toBeLessThanOrEqual(cell.recordCount);
    }
    for (const year of YEARS) {
      for (const cell of cellsFor(year)) {
        expect(cell.verifiedCount ?? 0).toBeLessThanOrEqual(cell.recordCount);
      }
    }
    expect(speciesDetailFixture.stats.yearRange).toEqual([YEARS[0], YEARS[YEARS.length - 1]]);
    for (const record of recordsFixture.items) {
      expect(cellsFor(record.year).some((cell) => cell.cellId === parentCell(record.gridRef))).toBe(true);
    }
  });

  it("gives every directory result a coherent detail, summary, map and complete record set", () => {
    for (const listed of speciesListItems) {
      const detailInput = speciesDetailFor(listed.speciesId);
      const summaryInput = speciesSummaryFor(listed.speciesId);
      if (!detailInput || !summaryInput) throw new Error(`Missing fixture for ${listed.speciesId}`);

      const detail = SpeciesDetailSchema.parse(detailInput);
      const summary = SummarySchema.parse(summaryInput);
      const cells = CellDistributionSchema.parse({
        ...fixtureReleaseIdentity,
        verificationAvailable: true,
        cells: cellsForSpecies(listed.speciesId),
      });
      const recordPage = RecordPageSchema.parse(recordsForSpecies(listed.speciesId, undefined, 1, 2000));
      const cellTotal = cells.cells.reduce((total, cell) => total + cell.recordCount, 0);
      const verifiedTotal = cells.cells.reduce((total, cell) => total + (cell.verifiedCount ?? 0), 0);

      expect(detail.speciesId).toBe(listed.speciesId);
      expect(detail.slug).toBe(listed.slug);
      expect(detail.group).toBe(listed.group);
      expect(Boolean(detail.image)).toBe(listed.hasImage);
      expect(detail.stats.recordCount).toBe(listed.recordCount);
      expect(detail.stats.recordCount).toBe(cellTotal);
      expect(detail.stats.verifiedCount).toBe(verifiedTotal);
      expect(summary.totalRecords).toBe(cellTotal);
      expect(summary.recordsByYear.reduce((total, entry) => total + entry.count, 0)).toBe(cellTotal);
      expect(recordPage.total).toBe(cellTotal);
      expect(recordPage.items).toHaveLength(cellTotal);
      expect(recordPage.items.filter((record) => record.verified === "accepted")).toHaveLength(verifiedTotal);

      for (const { year, count } of recordsByYearForSpecies(listed.speciesId)) {
        expect(totalCells(listed.speciesId, year), `${listed.speciesId} @ ${year}`).toBe(count);
        const yearPage = RecordPageSchema.parse(recordsForSpecies(listed.speciesId, year, 1, 2000));
        expect(yearPage.total).toBe(count);
        expect(yearPage.items).toHaveLength(count);
        for (const record of yearPage.items) {
          expect(cellsForSpecies(listed.speciesId, year).some((cell) => cell.cellId === parentCell(record.gridRef))).toBe(true);
        }
      }
    }
  });

  it("keeps catalog identities, slugs and global facets unique and truthful", () => {
    expect(new Set(speciesListItems.map((species) => species.speciesId)).size).toBe(speciesListItems.length);
    expect(new Set(speciesListItems.map((species) => species.slug)).size).toBe(speciesListItems.length);
    for (const facet of speciesGroupFacets) {
      expect(facet.speciesCount).toBe(speciesListItems.filter((species) => species.group === facet.value).length);
    }
    expect(() => SpeciesListPageSchema.parse(buildSpeciesListPage())).not.toThrow();
  });

  it("searches, filters, sorts and paginates deterministically", () => {
    expect(buildSpeciesListPage({ q: "VIPERA" }).items.map((species) => species.speciesId)).toEqual(["DEMO-002"]);
    expect(buildSpeciesListPage({ group: "mammal" }).items.map((species) => species.speciesId)).toEqual(["DEMO-004"]);
    expect(buildSpeciesListPage({ sort: "records-desc" }).items.map((species) => species.speciesId)).toEqual([
      "DEMO-004",
      "DEMO-003",
      "DEMO-001",
      "DEMO-002",
    ]);
    const pageOne = buildSpeciesListPage({ page: 1, pageSize: 3 });
    const pageTwo = buildSpeciesListPage({ page: 2, pageSize: 3 });
    expect(pageOne.total).toBe(4);
    expect(pageTwo.total).toBe(4);
    expect(pageOne.items).toHaveLength(3);
    expect(pageTwo.items).toHaveLength(1);
    expect(pageOne.items.map((species) => species.speciesId)).not.toContain(pageTwo.items[0]?.speciesId);
  });

  it("derives the overall summary and provenance from the same four-species catalog", () => {
    const parsed = SummarySchema.parse(summaryFixture);
    const total = speciesListItems.reduce((sum, species) => sum + species.recordCount, 0);
    expect(parsed.totalSpecies).toBe(speciesListItems.length);
    expect(parsed.totalRecords).toBe(total);
    expect(overallRecordsByYear.reduce((sum, entry) => sum + entry.count, 0)).toBe(total);
    expect(provenanceFixture.recordTotal).toBe(total);
    expect(parsed.topGroups.reduce((sum, group) => sum + group.count, 0)).toBe(total);
  });
});
